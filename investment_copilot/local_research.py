from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .market import fetch_prices
from .schema import ClientProfile

# LOCAL mode deliberately uses a bounded universe. This avoids hallucinated tickers while
# still allowing a diversified ETF core plus individual-stock satellite positions.
CORE_ETF_CATALOG: list[dict[str, str]] = [
    {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_class": "US_EQUITY", "currency": "USD", "role": "[ETF] 미국 대형주 코어"},
    {"ticker": "VTI", "name": "Vanguard Total Stock Market ETF", "asset_class": "US_EQUITY", "currency": "USD", "role": "[ETF] 미국 전체 주식시장 코어"},
    {"ticker": "069500.KS", "name": "KODEX 200", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[ETF] 한국 대형주 코어"},
    {"ticker": "VEA", "name": "Vanguard FTSE Developed Markets ETF", "asset_class": "DM_EQUITY", "currency": "USD", "role": "[ETF] 미국 제외 선진국 분산"},
    {"ticker": "VWO", "name": "Vanguard FTSE Emerging Markets ETF", "asset_class": "EM_EQUITY", "currency": "USD", "role": "[ETF] 신흥국 분산"},
    {"ticker": "SGOV", "name": "iShares 0-3 Month Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "[ETF] 초단기 미국 국채·유동성"},
    {"ticker": "IEF", "name": "iShares 7-10 Year Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "[ETF] 중기 미국 국채 듀레이션"},
    {"ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "GOV_BOND", "currency": "USD", "role": "[ETF] 장기 미국 국채 듀레이션"},
    {"ticker": "LQD", "name": "iShares iBoxx $ Investment Grade Corporate Bond ETF", "asset_class": "IG_CREDIT", "currency": "USD", "role": "[ETF] 미국 투자등급 회사채"},
    {"ticker": "HYG", "name": "iShares iBoxx $ High Yield Corporate Bond ETF", "asset_class": "HY_CREDIT", "currency": "USD", "role": "[ETF] 미국 하이일드 회사채"},
    {"ticker": "IAU", "name": "iShares Gold Trust", "asset_class": "GOLD", "currency": "USD", "role": "[ETF] 금 분산자산"},
    {"ticker": "DBC", "name": "Invesco DB Commodity Index Tracking Fund", "asset_class": "COMMODITY", "currency": "USD", "role": "[ETF] 광범위 원자재 노출; 구조·세금은 사람 검증 필요"},
    {"ticker": "VNQ", "name": "Vanguard Real Estate ETF", "asset_class": "REIT", "currency": "USD", "role": "[ETF] 미국 상장 리츠"},
]

# Large/liquid individual-stock candidates. Inclusion in this catalog is NOT a buy rating.
# LOCAL mode has no live fundamental research, so price statistics are supplied separately
# and financial statements/valuation/catalysts must be human-verified before client use.
CORE_STOCK_CATALOG: list[dict[str, str]] = [
    {"ticker": "MSFT", "name": "Microsoft", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 미국 대형 기술주"},
    {"ticker": "GOOGL", "name": "Alphabet Class A", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 미국 대형 인터넷/AI"},
    {"ticker": "AMZN", "name": "Amazon", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 미국 소비/클라우드"},
    {"ticker": "META", "name": "Meta Platforms", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 미국 플랫폼/광고"},
    {"ticker": "AVGO", "name": "Broadcom", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 반도체/인프라 소프트웨어"},
    {"ticker": "BRK-B", "name": "Berkshire Hathaway Class B", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 복합 금융/산업"},
    {"ticker": "JPM", "name": "JPMorgan Chase", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 미국 대형 은행"},
    {"ticker": "COST", "name": "Costco Wholesale", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 소비/리테일"},
    {"ticker": "LLY", "name": "Eli Lilly", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 헬스케어"},
    {"ticker": "XOM", "name": "Exxon Mobil", "asset_class": "US_EQUITY", "currency": "USD", "role": "[STOCK] 개별주 후보 · 에너지"},
    {"ticker": "005930.KS", "name": "삼성전자", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 한국 반도체/IT"},
    {"ticker": "000660.KS", "name": "SK하이닉스", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 한국 메모리 반도체"},
    {"ticker": "005380.KS", "name": "현대차", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 자동차"},
    {"ticker": "000270.KS", "name": "기아", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 자동차"},
    {"ticker": "055550.KS", "name": "신한지주", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 금융지주"},
    {"ticker": "105560.KS", "name": "KB금융", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 금융지주"},
    {"ticker": "035420.KS", "name": "NAVER", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 인터넷/플랫폼"},
    {"ticker": "207940.KS", "name": "삼성바이오로직스", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 바이오 CDMO"},
    {"ticker": "012330.KS", "name": "현대모비스", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 자동차 부품"},
    {"ticker": "047050.KS", "name": "포스코인터내셔널", "asset_class": "KR_EQUITY", "currency": "KRW", "role": "[STOCK] 개별주 후보 · 상사/에너지"},
]

STOCK_TICKERS = {x["ticker"] for x in CORE_STOCK_CATALOG}

BENCHMARKS = {
    "SPY": "미국 주식",
    "069500.KS": "한국 주식",
    "VEA": "미국 제외 선진국",
    "VWO": "신흥국 주식",
    "IEF": "미국 국채 7-10년",
    "TLT": "미국 장기국채",
    "LQD": "미국 투자등급 회사채",
    "HYG": "미국 하이일드",
    "IAU": "금",
    "DBC": "광범위 원자재",
    "VNQ": "미국 리츠",
}

ALLOWED_ASSET_CLASSES = {"US_EQUITY", "KR_EQUITY", "DM_EQUITY", "EM_EQUITY", "GOV_BOND", "IG_CREDIT", "HY_CREDIT", "GOLD", "COMMODITY", "REIT", "CASH", "OTHER"}


def build_product_catalog(profile: ClientProfile) -> list[dict[str, Any]]:
    style = getattr(profile, "product_style", "MIXED")
    source = list(CORE_ETF_CATALOG)
    if style in {"MIXED", "STOCK_ACTIVE"}:
        source += CORE_STOCK_CATALOG
    by_ticker: dict[str, dict[str, Any]] = {x["ticker"]: dict(x) for x in source}
    restrictions_upper = (profile.restrictions or "").upper()
    if "PTP" in restrictions_upper:
        by_ticker.pop("DBC", None)
    for h in profile.holdings:
        ticker = h.ticker.upper().strip()
        if not ticker or ticker == "CASH" or ticker in by_ticker:
            continue
        by_ticker[ticker] = {
            "ticker": ticker,
            "name": h.name or "고객 기존 보유자산",
            "asset_class": (h.asset_class or "OTHER").upper() if (h.asset_class or "OTHER").upper() in ALLOWED_ASSET_CLASSES else "OTHER",
            "currency": h.currency or profile.base_currency,
            "role": "[EXISTING] 고객 기존 보유자산 · LOCAL 모드에서는 상품 정체/구조를 사람 검증 필요",
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


def _snapshot_rows(tickers_to_labels: dict[str, str], years: int) -> tuple[list[dict[str, Any]], list[str]]:
    prices, warnings = fetch_prices(list(tickers_to_labels), years=max(2, years))
    rows: list[dict[str, Any]] = []
    if not prices.empty:
        for ticker, label in tickers_to_labels.items():
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
    return rows, warnings


def build_market_snapshot(years: int = 2) -> dict[str, Any]:
    rows, warnings = _snapshot_rows(BENCHMARKS, years)
    return {
        "generated_at_local": datetime.now().isoformat(timespec="seconds"),
        "method": "Yahoo Finance 수정주가 기반 벤치마크 스냅샷; 설명용 과거통계이며 예측값이 아님",
        "benchmarks": rows,
        "warnings": warnings,
    }


def build_stock_snapshot(profile: ClientProfile, years: int = 2) -> dict[str, Any]:
    if getattr(profile, "product_style", "MIXED") == "ETF_ONLY":
        return {"method": "개별주 미사용 설정", "stocks": [], "warnings": []}
    labels = {x["ticker"]: x["name"] for x in CORE_STOCK_CATALOG}
    rows, warnings = _snapshot_rows(labels, years)
    return {
        "generated_at_local": datetime.now().isoformat(timespec="seconds"),
        "method": "대형·유동성 개별주 후보의 Yahoo Finance 가격기반 스크린. 펀더멘털/밸류에이션/실적 전망은 별도 사람 검증 필요",
        "stocks": rows,
        "warnings": warnings,
    }


def _round_or_none(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 2)
