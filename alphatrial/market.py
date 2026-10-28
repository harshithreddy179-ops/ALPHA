"""Live Indian market data (NSE / BSE stocks and indices) from Yahoo Finance's public
chart endpoint. No API key is needed; results are cached in memory and on disk."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .data import DataError, clean_ohlcv

LIVE_PREFIX = "YF:"
CACHE_TTL = 6 * 3600
_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_CACHE_DIR = Path(os.environ.get("ALPHATRIAL_CACHE", "/tmp/alphatrial_cache"))
_MEM: dict[str, tuple[float, pd.DataFrame]] = {}

INDICES = [
    ("^NSEI", "NIFTY 50"),
    ("^BSESN", "S&P BSE SENSEX"),
    ("^NSEBANK", "NIFTY BANK"),
    ("^CNXIT", "NIFTY IT"),
    ("^NSMIDCP", "NIFTY NEXT 50"),
    ("^CNXAUTO", "NIFTY AUTO"),
    ("^CNXPHARMA", "NIFTY PHARMA"),
    ("^CNXFMCG", "NIFTY FMCG"),
]

# NIFTY 50 constituents (NSE symbol, company, sector). Index membership changes twice a
# year; edit this list to match the latest NSE factsheet.
NIFTY50 = [
    ("ADANIENT", "Adani Enterprises", "Metals & Mining"),
    ("ADANIPORTS", "Adani Ports & SEZ", "Services"),
    ("APOLLOHOSP", "Apollo Hospitals", "Healthcare"),
    ("ASIANPAINT", "Asian Paints", "Consumer Durables"),
    ("AXISBANK", "Axis Bank", "Financial Services"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Automobile"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services"),
    ("BEL", "Bharat Electronics", "Capital Goods"),
    ("BHARTIARTL", "Bharti Airtel", "Telecommunication"),
    ("CIPLA", "Cipla", "Healthcare"),
    ("COALINDIA", "Coal India", "Oil, Gas & Fuels"),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Healthcare"),
    ("EICHERMOT", "Eicher Motors", "Automobile"),
    ("ETERNAL", "Eternal (Zomato)", "Consumer Services"),
    ("GRASIM", "Grasim Industries", "Construction Materials"),
    ("HCLTECH", "HCL Technologies", "Information Technology"),
    ("HDFCBANK", "HDFC Bank", "Financial Services"),
    ("HDFCLIFE", "HDFC Life Insurance", "Financial Services"),
    ("HINDALCO", "Hindalco Industries", "Metals & Mining"),
    ("HINDUNILVR", "Hindustan Unilever", "FMCG"),
    ("ICICIBANK", "ICICI Bank", "Financial Services"),
    ("INDIGO", "InterGlobe Aviation", "Services"),
    ("INFY", "Infosys", "Information Technology"),
    ("ITC", "ITC", "FMCG"),
    ("JIOFIN", "Jio Financial Services", "Financial Services"),
    ("JSWSTEEL", "JSW Steel", "Metals & Mining"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services"),
    ("LT", "Larsen & Toubro", "Construction"),
    ("M&M", "Mahindra & Mahindra", "Automobile"),
    ("MARUTI", "Maruti Suzuki", "Automobile"),
    ("MAXHEALTH", "Max Healthcare", "Healthcare"),
    ("NESTLEIND", "Nestle India", "FMCG"),
    ("NTPC", "NTPC", "Power"),
    ("ONGC", "ONGC", "Oil, Gas & Fuels"),
    ("POWERGRID", "Power Grid Corp", "Power"),
    ("RELIANCE", "Reliance Industries", "Oil, Gas & Fuels"),
    ("SBILIFE", "SBI Life Insurance", "Financial Services"),
    ("SBIN", "State Bank of India", "Financial Services"),
    ("SHRIRAMFIN", "Shriram Finance", "Financial Services"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare"),
    ("TATACONSUM", "Tata Consumer Products", "FMCG"),
    ("TMPV", "Tata Motors (Passenger Vehicles)", "Automobile"),
    ("TATASTEEL", "Tata Steel", "Metals & Mining"),
    ("TCS", "Tata Consultancy Services", "Information Technology"),
    ("TECHM", "Tech Mahindra", "Information Technology"),
    ("TITAN", "Titan Company", "Consumer Durables"),
    ("TRENT", "Trent", "Consumer Services"),
    ("ULTRACEMCO", "UltraTech Cement", "Construction Materials"),
    ("WIPRO", "Wipro", "Information Technology"),
]

_SYMBOL_RE = re.compile(r"^\^?[A-Z0-9&\-_.]{1,25}$")


def is_live(name: str) -> bool:
    return name.upper().startswith(LIVE_PREFIX)


def to_symbol(name: str) -> str:
    sym = name[len(LIVE_PREFIX):] if is_live(name) else name
    sym = sym.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise DataError(f"Invalid symbol '{sym}'")
    return sym


def normalise(symbol: str, exchange: str = "NSE") -> str:
    """'reliance' + NSE -> 'RELIANCE.NS'; leaves indices and suffixed symbols alone."""
    s = symbol.strip().upper()
    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    return s + (".BO" if exchange.upper() == "BSE" else ".NS")


def universe() -> dict:
    return {
        "indices": [{"symbol": s, "name": n} for s, n in INDICES],
        "nifty50": [{"symbol": s, "name": n, "sector": sec} for s, n, sec in NIFTY50],
    }


def parse_chart(payload: dict) -> pd.DataFrame:
    """Turn a Yahoo v8 chart response into split/dividend-adjusted OHLCV."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise DataError(chart["error"].get("description") or "Symbol not found")
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise DataError("No price history returned for this symbol")
    q = res["indicators"]["quote"][0]
    offset = int(res.get("meta", {}).get("gmtoffset") or 0)
    dates = pd.to_datetime(np.asarray(res["timestamp"], dtype="int64") + offset, unit="s").normalize()
    df = pd.DataFrame({
        "Date": dates,
        "Open": q.get("open"), "High": q.get("high"), "Low": q.get("low"),
        "Close": q.get("close"), "Volume": q.get("volume"),
    })
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    if adj is not None:
        factor = pd.Series(adj, dtype=float) / df["Close"].astype(float)
        factor = factor.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        for c in ("Open", "High", "Low", "Close"):
            df[c] = df[c].astype(float) * factor
    df = df.dropna(subset=["Close"])
    return clean_ohlcv(df)


def _get(url: str, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _query(symbol: str, params: str) -> pd.DataFrame:
    path = (f"/v8/finance/chart/{urllib.parse.quote(symbol)}?{params}&interval=1d"
            "&includeAdjustedClose=true&events=div%2Csplits")
    last = None
    for host in _HOSTS:
        try:
            return parse_chart(_get(host + path))
        except DataError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise DataError(f"{symbol}: symbol not found")
            last = e
        except Exception as e:  # network problems: try the next host
            last = e
    raise ConnectionError(f"Could not download {symbol} from Yahoo Finance ({last})")


def _years(rng: str) -> int:
    m = re.fullmatch(r"(\d+)y", rng)
    return int(m.group(1)) if m else 10


def _download(symbol: str, rng: str) -> pd.DataFrame:
    """Some feeds (notably BSE '.BO' symbols) ignore `range` and return a single bar, so
    fall back to explicit period1/period2 timestamps and finally to the full history."""
    now = int(time.time())
    years = _years(rng)
    attempts = [f"range={rng}",
                f"period1={now - years * 366 * 86400}&period2={now}",
                "range=max"]
    errors = []
    for params in attempts:
        try:
            df = _query(symbol, params)
        except ConnectionError as e:
            raise DataError(str(e))
        except DataError as e:
            if "not found" in str(e).lower():
                raise
            errors.append(str(e))
            continue
        cutoff = df.index[-1] - pd.DateOffset(years=years)
        trimmed = df[df.index >= cutoff]
        return trimmed if len(trimmed) >= 60 else df
    raise DataError(f"{symbol}: {errors[-1] if errors else 'no data'}")


def fetch(symbol: str, rng: str = "10y") -> pd.DataFrame:
    symbol = to_symbol(symbol)
    key = f"{symbol}|{rng}"
    now = time.time()
    hit = _MEM.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    disk = _CACHE_DIR / (re.sub(r"[^A-Z0-9_.-]", "_", key) + ".csv")
    if disk.exists() and now - disk.stat().st_mtime < CACHE_TTL:
        df = clean_ohlcv(pd.read_csv(disk))
    else:
        try:
            df = _download(symbol, rng)
        except DataError:
            if disk.exists():  # stale cache beats nothing
                df = clean_ohlcv(pd.read_csv(disk))
            else:
                raise
        else:
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                df.to_csv(disk)
            except OSError:
                pass
    _MEM[key] = (now, df)
    return df


def snapshot(symbols: list[str], rng: str = "1y") -> list[dict]:
    """Latest price and trailing returns for many symbols, fetched in parallel."""
    def one(sym: str) -> dict:
        try:
            df = fetch(sym, rng)
        except DataError as e:
            return {"symbol": sym, "error": str(e)}
        c = df["Close"]
        r = c.pct_change().dropna()

        def ret(n):
            return round(float(c.iloc[-1] / c.iloc[-n - 1] - 1) * 100, 2) if len(c) > n else None

        return {
            "symbol": sym, "date": df.index[-1].strftime("%Y-%m-%d"),
            "close": round(float(c.iloc[-1]), 2),
            "chg_1d": ret(1), "chg_1w": ret(5), "chg_1m": ret(21), "chg_3m": ret(63),
            "chg_1y": round(float(c.iloc[-1] / c.iloc[0] - 1) * 100, 2),
            "vol_1y": round(float(r.std() * np.sqrt(252)) * 100, 2) if len(r) > 2 else None,
            "high_52w": round(float(df["High"].max()), 2), "low_52w": round(float(df["Low"].min()), 2),
            "spark": np.round(c.iloc[-60:].to_numpy(), 2).tolist(),
        }

    with ThreadPoolExecutor(max_workers=12) as ex:
        return list(ex.map(one, symbols))
