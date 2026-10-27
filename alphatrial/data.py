"""Loading, validating and generating OHLCV price data."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ["Open", "High", "Low", "Close", "Volume"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_ALIASES = {
    "date": "Date", "datetime": "Date", "timestamp": "Date", "time": "Date",
    "open": "Open", "high": "High", "low": "Low", "close": "Close",
    "adj close": "Adj Close", "adj_close": "Adj Close", "adjclose": "Adj Close",
    "volume": "Volume", "vol": "Volume",
}


class DataError(ValueError):
    pass


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names, parse dates, sort, de-duplicate and fill gaps."""
    df = df.rename(columns={c: _ALIASES.get(str(c).strip().lower(), str(c).strip()) for c in df.columns})
    if "Date" not in df.columns:
        raise DataError("CSV must contain a Date column")
    if "Close" not in df.columns:
        if "Adj Close" in df.columns:
            df["Close"] = df["Adj Close"]
        else:
            raise DataError("CSV must contain a Close column")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.dropna(subset=["Date"]).sort_values("Date").drop_duplicates("Date", keep="last")
    df = df.set_index("Date")

    # Only Close is strictly required; reconstruct the rest if absent.
    for col in ["Open", "High", "Low"]:
        if col not in df.columns:
            df[col] = df["Close"]
    if "Volume" not in df.columns:
        df["Volume"] = 0.0

    df = df[REQUIRED].apply(pd.to_numeric, errors="coerce")
    df = df.ffill(limit=5).dropna(subset=["Close"])
    df["Open"] = df["Open"].fillna(df["Close"])
    df["High"] = df[["High", "Open", "Close"]].max(axis=1)
    df["Low"] = df[["Low", "Open", "Close"]].min(axis=1)
    df["Volume"] = df["Volume"].fillna(0.0)
    df = df[df["Close"] > 0]

    if len(df) < 60:
        raise DataError(f"Need at least 60 rows of data, got {len(df)}")
    return df


def load_csv(source: str | Path | bytes) -> pd.DataFrame:
    if isinstance(source, (bytes, bytearray)):
        raw = pd.read_csv(io.BytesIO(source))
    else:
        raw = pd.read_csv(source)
    return clean_ohlcv(raw)


def list_datasets() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.csv"))


def load_dataset(name: str) -> pd.DataFrame:
    path = DATA_DIR / f"{Path(name).stem}.csv"
    if not path.exists():
        raise DataError(f"Unknown dataset '{name}'")
    return load_csv(path)


# Regime-switching sample generator ------------------------------------------------

_REGIMES = {
    # name: (annual drift, annual vol, mean length in days)
    "bull": (0.22, 0.14, 260),
    "bear": (-0.28, 0.30, 110),
    "sideways": (0.02, 0.16, 180),
    "crash": (-1.8, 0.65, 18),
}
_TRANSITIONS = {
    "bull": {"sideways": 0.5, "bear": 0.35, "crash": 0.15},
    "bear": {"sideways": 0.45, "bull": 0.45, "crash": 0.10},
    "sideways": {"bull": 0.55, "bear": 0.35, "crash": 0.10},
    "crash": {"bear": 0.5, "sideways": 0.2, "bull": 0.3},
}


def generate_prices(n_days: int = 2520, start_price: float = 100.0, seed: int = 7,
                    start: str = "2015-01-02", drift_scale: float = 1.0,
                    vol_scale: float = 1.0) -> pd.DataFrame:
    """Synthetic OHLCV with regime switching, volatility clustering and fat tails."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=n_days)
    regime = "bull"
    remaining = int(rng.exponential(_REGIMES[regime][2])) + 5
    rets, labels = np.empty(n_days), []
    garch_var = 1.0
    prev_shock = 0.0
    for i in range(n_days):
        if remaining <= 0:
            nxt = _TRANSITIONS[regime]
            regime = rng.choice(list(nxt), p=list(nxt.values()))
            remaining = int(rng.exponential(_REGIMES[regime][2])) + 5
        mu, sigma, _ = _REGIMES[regime]
        mu, sigma = mu * drift_scale, sigma * vol_scale
        garch_var = min(0.05 + 0.85 * garch_var + 0.10 * prev_shock ** 2, 4.0)
        shock = float(np.clip(rng.standard_t(df=5) / np.sqrt(5 / 3), -6, 6))
        prev_shock = shock
        rets[i] = mu / 252 + sigma / np.sqrt(252) * np.sqrt(garch_var) * shock
        labels.append(regime)
        remaining -= 1

    close = start_price * np.exp(np.cumsum(rets))
    prev_close = np.concatenate([[start_price], close[:-1]])
    gap = rng.normal(0, 0.003, n_days)
    open_ = prev_close * np.exp(gap)
    intraday = np.abs(rng.normal(0, 0.008, n_days)) * vol_scale
    high = np.maximum(open_, close) * (1 + intraday)
    low = np.minimum(open_, close) * (1 - intraday)
    base_vol = 2_000_000
    volume = base_vol * (1 + 8 * np.abs(rets)) * rng.lognormal(0, 0.25, n_days)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                       "Volume": volume.round()}, index=pd.Index(dates, name="Date"))
    df["TrueRegime"] = labels
    return df


SAMPLES = {
    # Growth stock: strong uptrend with sharp corrections.
    "ALPHA_TECH": dict(seed=4, start_price=120.0, drift_scale=1.1, vol_scale=1.2),
    # Financial: long bull runs interrupted by a deep crisis.
    "BETA_BANK": dict(seed=9, start_price=60.0, drift_scale=1.0, vol_scale=1.0),
    # Cyclical: boom-bust, mean-reverting behaviour.
    "GAMMA_ENERGY": dict(seed=2, start_price=45.0, drift_scale=0.8, vol_scale=1.3),
    # Broad index: lower volatility, steady drift.
    "DELTA_INDEX": dict(seed=1, start_price=2000.0, drift_scale=0.9, vol_scale=0.75),
}


def write_samples() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for name, kw in SAMPLES.items():
        df = generate_prices(**kw).drop(columns="TrueRegime")
        df.round(4).to_csv(DATA_DIR / f"{name}.csv")


if __name__ == "__main__":
    write_samples()
    print("Wrote", list_datasets())
