from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf


def fetch_prices(tickers: list[str], years: int = 5) -> tuple[pd.DataFrame, list[str]]:
    clean = sorted({t.strip().upper() for t in tickers if t and t.strip() and t.upper() != "CASH"})
    if not clean:
        return pd.DataFrame(), []

    end = datetime.today()
    start = end - timedelta(days=int(years * 365.25) + 30)
    warnings: list[str] = []

    try:
        raw = yf.download(
            clean,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            group_by="column",
            threads=True,
        )
    except Exception as exc:
        return pd.DataFrame(), [f"Price download failed: {exc}"]

    if raw is None or len(raw) == 0:
        return pd.DataFrame(), ["No market price data returned."]

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            prices = raw["Close"].copy()
        elif "Adj Close" in raw.columns.get_level_values(0):
            prices = raw["Adj Close"].copy()
        else:
            return pd.DataFrame(), ["Could not locate Close prices in market data response."]
    else:
        col = "Close" if "Close" in raw.columns else ("Adj Close" if "Adj Close" in raw.columns else None)
        if col is None:
            return pd.DataFrame(), ["Could not locate Close prices in market data response."]
        prices = raw[[col]].copy()
        prices.columns = [clean[0]]

    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=clean[0])

    prices = prices.sort_index().dropna(how="all")
    missing = [t for t in clean if t not in prices.columns or prices[t].dropna().empty]
    if missing:
        warnings.append("Missing price history for: " + ", ".join(missing))
    return prices, warnings


def _fx_candidates(from_ccy: str, to_ccy: str) -> tuple[list[str], list[str]]:
    f, t = from_ccy.upper(), to_ccy.upper()
    if f == t:
        return [], []
    direct = [f"{f}{t}=X"]
    inverse = [f"{t}{f}=X"]
    if f == "USD" and t == "KRW":
        direct.insert(0, "KRW=X")
    if f == "KRW" and t == "USD":
        inverse.insert(0, "KRW=X")
    return direct, inverse


def fetch_prices_in_base(
    instruments: dict[str, str], base_currency: str, years: int = 5
) -> tuple[pd.DataFrame, list[str]]:
    tickers = list(instruments.keys())
    prices, warnings = fetch_prices(tickers, years=years)
    if prices.empty:
        return prices, warnings

    out = pd.DataFrame(index=prices.index)
    for ticker, ccy in instruments.items():
        if ticker not in prices.columns or prices[ticker].dropna().empty:
            continue
        if ccy.upper() == base_currency.upper():
            out[ticker] = prices[ticker]
            continue

        direct, inverse = _fx_candidates(ccy, base_currency)
        fx_series = None
        for symbol in direct:
            fx, _ = fetch_prices([symbol], years=years)
            if not fx.empty and symbol in fx.columns and not fx[symbol].dropna().empty:
                fx_series = fx[symbol]
                break
        if fx_series is not None:
            joined = pd.concat([prices[ticker], fx_series], axis=1).ffill().dropna()
            out[ticker] = joined.iloc[:, 0] * joined.iloc[:, 1]
            continue

        for symbol in inverse:
            fx, _ = fetch_prices([symbol], years=years)
            if not fx.empty and symbol in fx.columns and not fx[symbol].dropna().empty:
                fx_series = fx[symbol]
                break
        if fx_series is not None:
            joined = pd.concat([prices[ticker], fx_series], axis=1).ffill().dropna()
            out[ticker] = joined.iloc[:, 0] / joined.iloc[:, 1]
            continue

        warnings.append(f"FX conversion unavailable for {ticker}: {ccy}->{base_currency}; ticker omitted from base-currency quant.")

    return out.sort_index().dropna(how="all"), warnings
