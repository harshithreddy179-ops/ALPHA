"""Market-regime classification and per-regime performance attribution."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

from . import indicators as ind
from .metrics import TRADING_DAYS

TREND_LABELS = ("Bull", "Sideways", "Bear")


def classify_rule_based(df: pd.DataFrame, trend_window: int = 100, vol_window: int = 20,
                        band: float = 0.05) -> pd.DataFrame:
    """Trend × volatility regimes from trailing data only.

    Trend: Bull if price is more than `band` above its SMA and the SMA is rising, Bear if
    more than `band` below and falling, else Sideways. Volatility: High if 20-day realised
    vol exceeds its expanding median (so the threshold itself never peeks ahead).
    """
    c = df["Close"]
    s = ind.sma(c, trend_window)
    slope = s.diff(20)
    dist = c / s - 1
    trend = np.where((dist > band) & (slope > 0), "Bull",
                     np.where((dist < -band) & (slope < 0), "Bear", "Sideways"))
    vol = ind.volatility(c, vol_window)
    vol_med = vol.expanding(min_periods=60).median()
    volr = np.where(vol > vol_med, "High Vol", "Low Vol")
    out = pd.DataFrame({"trend": trend, "vol": volr}, index=df.index)
    out.loc[s.isna(), "trend"] = "Unknown"
    out.loc[vol_med.isna(), "vol"] = "Unknown"
    out["regime"] = out["trend"] + " / " + out["vol"]
    out.loc[(out["trend"] == "Unknown") | (out["vol"] == "Unknown"), "regime"] = "Unknown"
    return out


def classify_gmm(df: pd.DataFrame, n_states: int = 3, train_frac: float = 0.5,
                 seed: int = 0) -> pd.Series:
    """Unsupervised regimes: a Gaussian mixture on (20d return, 20d vol), fitted on the
    first `train_frac` of history only and then applied forward. States are named by
    their mean return so that labels are comparable with the rule-based ones."""
    c = df["Close"]
    r = c.pct_change()
    X = pd.DataFrame({"ret": r.rolling(20).mean() * TRADING_DAYS,
                      "vol": r.rolling(20).std() * np.sqrt(TRADING_DAYS)}).dropna()
    cut = int(len(X) * train_frac)
    gm = GaussianMixture(n_components=n_states, random_state=seed, n_init=3).fit(X.iloc[:cut])
    states = gm.predict(X)
    order = np.argsort(-gm.means_[:, 0])
    names = {order[0]: "Bull", order[-1]: "Bear"}
    for k in order[1:-1]:
        names[k] = "Sideways"
    lab = pd.Series([names[s] for s in states], index=X.index)
    return lab.reindex(df.index).fillna("Unknown")


def regime_performance(strategy_returns: dict[str, pd.Series], labels: pd.Series) -> list[dict]:
    """Annualised return / Sharpe of each strategy inside each regime.

    A day's return is attributed to the regime observed at the previous close, i.e. the
    regime the strategy was actually trading into.
    """
    lab = labels.shift(1)
    rows = []
    for regime in sorted(x for x in lab.dropna().unique() if "Unknown" not in str(x)):
        mask = lab == regime
        row = {"regime": regime, "days": int(mask.sum()),
               "pct_time": round(float(mask.mean()) * 100, 1)}
        for name, r in strategy_returns.items():
            rr = r.reindex(lab.index)[mask].dropna()
            if len(rr) < 5:
                row[name] = {"ann_return": None, "sharpe": None, "hit_rate": None}
                continue
            sd = rr.std(ddof=1)
            row[name] = {
                "ann_return": round(float(rr.mean() * TRADING_DAYS * 100), 2),
                "sharpe": round(float(rr.mean() / sd * np.sqrt(TRADING_DAYS)), 2) if sd > 0 else 0.0,
                "hit_rate": round(float((rr > 0).mean() * 100), 1),
            }
        rows.append(row)
    return rows


def yearly_returns(strategy_returns: dict[str, pd.Series]) -> list[dict]:
    frame = pd.DataFrame(strategy_returns)
    yr = (1 + frame).groupby(frame.index.year).prod() - 1
    return [{"year": int(y), **{k: round(float(v) * 100, 2) for k, v in row.items()}}
            for y, row in yr.iterrows()]
