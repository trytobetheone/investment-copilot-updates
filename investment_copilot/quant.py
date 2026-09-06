from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .market import fetch_prices_in_base
from .schema import (
    AllocationLine,
    CandidatePortfolio,
    CandidateQuantResult,
    CandidateSet,
    ClientProfile,
    MacroReport,
    ProductUniverse,
    QuantMetrics,
)

TRADING_DAYS = 252


def _max_drawdown(series: pd.Series) -> float:
    wealth = (1.0 + series.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    drawdown = wealth / peak - 1.0
    return float(drawdown.min())


def _risk_contributions(cov: np.ndarray, weights: np.ndarray) -> np.ndarray:
    port_var = float(weights.T @ cov @ weights)
    if port_var <= 0:
        return np.zeros_like(weights)
    marginal = cov @ weights
    return weights * marginal / port_var


def _cap_and_redistribute(weights: dict[str, float], cap: float = 0.35) -> dict[str, float]:
    w = dict(weights)
    for _ in range(20):
        over = {k: v for k, v in w.items() if v > cap + 1e-12}
        if not over:
            break
        excess = sum(v - cap for v in over.values())
        for k in over:
            w[k] = cap
        under = [k for k, v in w.items() if v < cap - 1e-12]
        room = sum(cap - w[k] for k in under)
        if not under or room <= 0:
            break
        for k in under:
            w[k] += excess * (cap - w[k]) / room
    total = sum(w.values())
    return {k: v / total for k, v in w.items()} if total > 0 else w


def construct_candidates(
    profile: ClientProfile,
    product: ProductUniverse,
    macro: MacroReport,
    years: int = 5,
) -> CandidateSet:
    ideas = [p for p in product.products if p.ticker != "CASH"]
    instruments = {p.ticker: p.currency for p in ideas}
    prices, warnings = fetch_prices_in_base(instruments, profile.base_currency, years=years)
    usable = [p for p in ideas if p.ticker in prices.columns and prices[p.ticker].dropna().shape[0] >= 120]
    if len(usable) < 2:
        raise RuntimeError("정량 후보를 만들 수 있는 가격 이력이 있는 상품이 2개 미만입니다. Product Agent 결과 또는 ticker를 검토하세요.")

    aligned = prices[[p.ticker for p in usable]].ffill().dropna()
    returns = aligned.pct_change().dropna()
    vols = returns.std(ddof=1) * math.sqrt(TRADING_DAYS)

    tilt_mult = {"UNDERWEIGHT": 0.85, "NEUTRAL": 1.0, "OVERWEIGHT": 1.15}
    macro_tilts = {item.asset_class: item.view for item in macro.asset_tilts}
    posture_mult = {
        "defensive": {
            "US_EQUITY": 0.7, "KR_EQUITY": 0.7, "DM_EQUITY": 0.75, "EM_EQUITY": 0.65,
            "GOV_BOND": 1.45, "IG_CREDIT": 1.25, "HY_CREDIT": 0.8, "GOLD": 1.15,
            "COMMODITY": 0.8, "REIT": 0.75, "OTHER": 0.8,
        },
        "balanced": {},
        "growth": {
            "US_EQUITY": 1.3, "KR_EQUITY": 1.25, "DM_EQUITY": 1.2, "EM_EQUITY": 1.15,
            "GOV_BOND": 0.7, "IG_CREDIT": 0.8, "HY_CREDIT": 1.0, "GOLD": 0.85,
            "COMMODITY": 0.95, "REIT": 1.0, "OTHER": 1.0,
        },
    }

    base_target_vol = float(np.clip(profile.max_tolerable_loss_pct / 2.0, 4.0, 18.0)) / 100.0
    specs = [
        ("C1", "Defensive", "defensive", 0.75),
        ("C2", "Balanced", "balanced", 1.00),
        ("C3", "Growth-tilted", "growth", 1.25),
    ]
    candidates: list[CandidatePortfolio] = []

    for cid, label, posture, target_mult in specs:
        raw: dict[str, float] = {}
        for p in usable:
            vol = float(vols.get(p.ticker, np.nan))
            if not np.isfinite(vol) or vol <= 0:
                continue
            macro_view = macro_tilts.get(p.asset_class, "NEUTRAL")
            raw[p.ticker] = (1.0 / vol) * tilt_mult.get(macro_view, 1.0) * posture_mult[posture].get(p.asset_class, 1.0)
        if len(raw) < 2:
            continue
        total_raw = sum(raw.values())
        risky_weights = {k: v / total_raw for k, v in raw.items()}
        risky_weights = _cap_and_redistribute(risky_weights, cap=0.35)

        tickers = list(risky_weights)
        w_vec = np.array([risky_weights[t] for t in tickers])
        cov = returns[tickers].cov().to_numpy() * TRADING_DAYS
        risky_vol = math.sqrt(max(float(w_vec.T @ cov @ w_vec), 0.0))
        target_vol = min(base_target_vol * target_mult, 0.22)
        min_cash = profile.minimum_liquidity_pct / 100.0
        max_risky = max(0.0, 1.0 - min_cash)
        risky_fraction = max_risky if risky_vol <= 1e-9 else min(max_risky, target_vol / risky_vol)
        risky_fraction = max(0.0, risky_fraction)
        cash_weight = 1.0 - risky_fraction

        pmap = {p.ticker: p for p in usable}
        allocations: list[AllocationLine] = []
        for t in tickers:
            p = pmap[t]
            weight_pct = risky_weights[t] * risky_fraction * 100.0
            if weight_pct >= 0.25:
                allocations.append(
                    AllocationLine(
                        ticker=t,
                        name=p.name,
                        asset_class=p.asset_class,
                        currency=p.currency,
                        weight=round(weight_pct, 4),
                        role=p.role,
                    )
                )
        allocations.append(
            AllocationLine(
                ticker="CASH",
                name=f"Cash / cash-equivalent ({profile.base_currency})",
                asset_class="CASH",
                currency=profile.base_currency,
                weight=round(cash_weight * 100.0, 4),
                role="liquidity and volatility buffer",
            )
        )
        residue = round(100.0 - sum(a.weight for a in allocations), 4)
        allocations[-1].weight = round(allocations[-1].weight + residue, 4)
        note = (
            f"Local engine: inverse-vol diversification, 35% single-line cap, base-currency ({profile.base_currency}) risk targeting; "
            f"target historical vol ≈ {target_vol*100:.1f}%; this does NOT guarantee the client max-loss limit."
        )
        if warnings:
            note += " Data warnings: " + " / ".join(warnings)
        candidates.append(
            CandidatePortfolio(
                candidate_id=cid,
                label=label,
                thesis=f"{label} posture generated deterministically from client loss tolerance, minimum liquidity, product universe, and bounded macro tilts.",
                allocations=allocations,
                implementation_notes=[note, f"Construction data: {aligned.index.min().date()} to {aligned.index.max().date()}."],
            )
        )

    if len(candidates) < 2:
        raise RuntimeError("유효한 후보 포트폴리오를 2개 이상 구성하지 못했습니다.")
    return CandidateSet(candidates=candidates[:3])


def analyze_candidate(
    candidate: CandidatePortfolio,
    base_currency: str,
    years: int = 5,
    risk_free_rate_pct: float = 3.0,
) -> CandidateQuantResult:
    total = candidate.total_weight()
    warnings: list[str] = []
    if not math.isclose(total, 100.0, abs_tol=0.25):
        warnings.append(f"Weights sum to {total:.2f}%, not 100%.")

    non_cash = [a for a in candidate.allocations if a.ticker.upper() != "CASH"]
    instruments = {a.ticker: a.currency for a in non_cash}
    prices, price_warnings = fetch_prices_in_base(instruments, base_currency, years=years)
    warnings.extend(price_warnings)
    if prices.empty:
        return CandidateQuantResult(candidate_id=candidate.candidate_id, metrics=QuantMetrics(status="FAILED", warnings=warnings or ["No price data."]))

    usable = [a for a in non_cash if a.ticker in prices.columns and not prices[a.ticker].dropna().empty]
    if not usable:
        return CandidateQuantResult(candidate_id=candidate.candidate_id, metrics=QuantMetrics(status="FAILED", warnings=warnings + ["No usable ticker history."]))

    use_tickers = [a.ticker for a in usable]
    aligned = prices[use_tickers].ffill().dropna()
    if len(aligned) < 60:
        return CandidateQuantResult(candidate_id=candidate.candidate_id, metrics=QuantMetrics(status="FAILED", observations=len(aligned), warnings=warnings + ["Less than 60 aligned price observations."]))

    returns = aligned.pct_change().dropna()
    weights = np.array([a.weight / 100.0 for a in usable], dtype=float)
    cash_weight = sum(a.weight for a in candidate.allocations if a.ticker.upper() == "CASH") / 100.0
    represented_weight = float(weights.sum() + cash_weight)
    missing_weight = max(0.0, 1.0 - represented_weight)
    if missing_weight > 0.005:
        warnings.append(f"{missing_weight*100:.2f}% of portfolio is omitted due to unavailable price/FX data.")

    cash_daily = (1 + risk_free_rate_pct / 100.0) ** (1 / TRADING_DAYS) - 1
    port = returns.mul(weights, axis=1).sum(axis=1) + cash_weight * cash_daily
    n = len(port)
    cumulative = float((1 + port).prod())
    years_observed = n / TRADING_DAYS
    ann_return = cumulative ** (1 / years_observed) - 1 if cumulative > 0 and years_observed > 0 else np.nan
    ann_vol = float(port.std(ddof=1) * math.sqrt(TRADING_DAYS))
    rf = risk_free_rate_pct / 100.0
    sharpe = (ann_return - rf) / ann_vol if ann_vol > 1e-12 and np.isfinite(ann_return) else np.nan
    max_dd = _max_drawdown(port)
    q05 = float(port.quantile(0.05))
    cvar = float(port[port <= q05].mean()) if (port <= q05).any() else q05
    rolling20 = (1 + port).rolling(20).apply(np.prod, raw=True) - 1
    worst20 = float(rolling20.min()) if rolling20.notna().any() else np.nan

    cov = returns.cov().to_numpy() * TRADING_DAYS
    rc = _risk_contributions(cov, weights)
    rc_map = {ticker: round(float(v * 100), 2) for ticker, v in zip(use_tickers, rc)}
    if cash_weight > 0:
        rc_map["CASH"] = 0.0

    status = "OK" if missing_weight <= 0.005 and not price_warnings else "PARTIAL"
    metrics = QuantMetrics(
        status=status,
        annualized_return_pct=round(float(ann_return * 100), 2) if np.isfinite(ann_return) else None,
        annualized_volatility_pct=round(ann_vol * 100, 2),
        sharpe_ratio=round(float(sharpe), 2) if np.isfinite(sharpe) else None,
        max_drawdown_pct=round(max_dd * 100, 2),
        var_95_daily_pct=round(q05 * 100, 2),
        cvar_95_daily_pct=round(cvar * 100, 2),
        worst_20d_pct=round(float(worst20 * 100), 2) if np.isfinite(worst20) else None,
        observations=n,
        data_start=str(returns.index.min().date()),
        data_end=str(returns.index.max().date()),
        warnings=warnings,
        risk_contributions_pct=rc_map,
    )
    return CandidateQuantResult(candidate_id=candidate.candidate_id, metrics=metrics)


def analyze_candidates(candidates: list[CandidatePortfolio], base_currency: str, years: int = 5, risk_free_rate_pct: float = 3.0) -> list[CandidateQuantResult]:
    return [analyze_candidate(c, base_currency=base_currency, years=years, risk_free_rate_pct=risk_free_rate_pct) for c in candidates]
