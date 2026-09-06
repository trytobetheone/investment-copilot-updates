from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .market import fetch_prices
from .schema import ClientProfile

# A deliberately small, stable catalog. Local mode may select only from this catalog
# (plus user-supplied current holdings). No fees/yields are hard-coded because those change.
CORE_PRODUCT_CATALOG: list[dict[str, str]] = [
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_class": "US_EQUITY", "currency": "USD", "role": "US large-cap equity core"},
    {"ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "asset_class": "US_EQUITY", "currency": "USD", "role": "broad US equity core"},
    {"ticker": "069500.KS", "name": "KODEX 200", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "Korea large-cap equity core"},
    {"ticker": "VEA", "name": "Vanguard FTSE Developed Markets ETF", "asset_class": "DM_EQUITY", "currency": "USD", "role": "developed ex-US equity"},
    {"ticker": "VWO", "name": "Vanguard FTSE Emerging Markets ETF", "asset_class": "EM_EQUITY", "currency": "USD", "role": "emerging-market equity"},
    {"ticker": "SGOV", "name": "iShares 0-3 Month Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "very short US Treasury exposure"},
    {"ticker": "IEF", "name": "iShares 7-10 Year Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "intermediate US Treasury duration"},
    {"ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "long US Treasury duration"},
    {"ticker": "LQD", "name": "iShares iBoxx $ Investment Grade Corporate Bond ETF", "asset_class": "IG_CREDIT", "currency": "USD", "role": "investment-grade corporate credit"},
    {"ticker": "HYG", "name": "iShares iBoxx $ High Yield Corporate Bond ETF", "asset_class": "HY_CREDIT", "currency": "USD", "role": "high-yield corporate credit"},
    {"ticker": "IAU", "name": "iShares Gold Trust", "asset_class": "GOLD", "currency": "USD", "role": "gold diversifier"},
    {"ticker": "DBC", "name": "Invesco DB Commodity Index Tracking Fund", "asset_class": "COMMODITY", "currency": "USD", "role": "broad commodity exposure; structure/tax requires human verification"},
    {"ticker": "VNQ", "name": "Vanguard Real Estate ETF", "asset_class": "REIT", "currency": "USD", "role": "US listed real estate"},
]

BENCHMARKS = {
    "SPY": "US equity",
    "069500.KS": "Korea equity",
    "VEA": "Developed ex-US equity",
    "VWO": "Emerging equity",
    "IEF": "US Treasury 7-10Y",
    "TLT": "US Treasury 20Y+",
    "LQD": "US IG credit",
    "HYG": "US HY credit",
    "IAU": "Gold",
    "DBC": "Broad commodities",
    "VNQ": "US REIT",
}


ALLOWED_ASSET_CLASSES = {"US_EQUITY", "KR_EQUITY", "DM_EQUITY", "EM_EQUITY", "GOV_BOND", "IG_CREDIT", "HY_CREDIT", "GOLD", "COMMODITY", "REIT", "CASH", "OTHER"}


def build_product_catalog(profile: ClientProfile) -> list[dict[str, Any]]:
    by_ticker: dict[str, dict[str, Any]] = {x["ticker"]: dict(x) for x in CORE_PRODUCT_CATALOG}
    restrictions_upper = (profile.restrictions or "").upper()
    # Conservative local guardrail: do not surface the commodity-pool candidate when PTP is explicitly prohibited.
    if "PTP" in restrictions_upper:
        by_ticker.pop("DBC", None)
    for h in profile.holdings:
        ticker = h.ticker.upper().strip()
        if not ticker or ticker == "CASH" or ticker in by_ticker:
            continue
        by_ticker[ticker] = {
            "ticker": ticker,
            "name": h.name or "User-supplied holding",
            "asset_class": (h.asset_class or "OTHER").upper() if (h.asset_class or "OTHER").upper() in ALLOWED_ASSET_CLASSES else "OTHER",
            "currency": h.currency or profile.base_currency,
            "role": "existing client holding; identity/structure must be human-verified in LOCAL mode",
            "user_supplied": True,
        }
    return list(by_ticker.values())


def _safe_return(series: pd.Series, days: int) -> float | None:
    s = series.dropna()
    if len(s) <= days or float(s.iloc[-days - 1]) == 0:
        return None
    return float((s.iloc[-1] / s.iloc[-days - 1] - 1.0) * 100.0)


def _safe_vol(series: pd.Series, days: int = 63) -> float | None:
    r = series.dropna().pct_change().dropna().tail(days)
    if len(r) < max(20, days // 3):
        return None
    return float(r.std(ddof=1) * math.sqrt(252) * 100.0)


def _drawdown(series: pd.Series, days: int = 252) -> float | None:
    s = series.dropna().tail(days)
    if len(s) < 20:
        return None
    peak = s.cummax()
    dd = s / peak - 1.0
    return float(dd.min() * 100.0)


def build_market_snapshot(years: int = 2) -> dict[str, Any]:
    tickers = list(BENCHMARKS)
    prices, warnings = fetch_prices(tickers, years=max(2, years))
    rows: list[dict[str, Any]] = []
    if not prices.empty:
        for ticker, label in BENCHMARKS.items():
            if ticker not in prices.columns or prices[ticker].dropna().empty:
                continue
            s = prices[ticker]
            rows.append(
                {
                    "ticker": ticker,
                    "label": label,
                    "return_1m_pct": _round_or_none(_safe_return(s, 21)),
                    "return_3m_pct": _round_or_none(_safe_return(s, 63)),
                    "return_12m_pct": _round_or_none(_safe_return(s, 252)),
                    "vol_3m_ann_pct": _round_or_none(_safe_vol(s, 63)),
                    "max_drawdown_12m_pct": _round_or_none(_drawdown(s, 252)),
                    "last_observation": str(s.dropna().index[-1].date()),
                }
            )
    return {
        "generated_at_local": datetime.now().isoformat(timespec="seconds"),
        "method": "Yahoo Finance adjusted-close benchmark snapshot; descriptive, not a forecast",
        "benchmarks": rows,
        "warnings": warnings,
    }


def _round_or_none(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 2)
