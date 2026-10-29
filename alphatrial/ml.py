"""Walk-forward machine-learning direction model.

The model predicts whether tomorrow's close will be above today's close. It's
retrained on a rolling window, and a prediction for day t only ever uses a model
fitted on rows whose labels were already known at the close of t.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import indicators as ind
from .strategies import Param, Strategy

FEATURES = ["ret_1", "ret_5", "ret_10", "ret_20", "rsi_14", "dist_sma20", "dist_sma50",
            "dist_sma200", "vol_20", "vol_ratio", "volume_z", "range_pct"]


def make_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    r = c.pct_change()
    f = pd.DataFrame(index=df.index)
    for n in (1, 5, 10, 20):
        f[f"ret_{n}"] = c.pct_change(n)
    f["rsi_14"] = ind.rsi(c, 14) / 100
    for n in (20, 50, 200):
        f[f"dist_sma{n}"] = c / ind.sma(c, n) - 1
    f["vol_20"] = r.rolling(20).std() * np.sqrt(252)
    f["vol_ratio"] = r.rolling(10).std() / r.rolling(60).std()
    v = df["Volume"].replace(0, np.nan)
    f["volume_z"] = ((v - v.rolling(20).mean()) / v.rolling(20).std()).fillna(0)
    f["range_pct"] = (df["High"] - df["Low"]) / c
    return f


def make_label(df: pd.DataFrame) -> pd.Series:
    """1 if the next close is higher. Row t's label becomes known at close t+1."""
    nxt = df["Close"].shift(-1)
    return (nxt > df["Close"]).astype(float).where(nxt.notna())


def _model(kind: str):
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=100, max_depth=4, min_samples_leaf=20,
                                      random_state=0, n_jobs=1)
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))


_CACHE: dict[tuple, tuple] = {}


def walk_forward_predict(df: pd.DataFrame, model: str = "logistic", train_window: int = 756,
                         retrain_every: int = 63, min_train: int = 378):
    """Out-of-sample probability that the next close is up, for every row (memoised)."""
    key = (int(pd.util.hash_pandas_object(df[["Open", "High", "Low", "Close", "Volume"]]).sum()),
           model, int(train_window), int(retrain_every), int(min_train))
    if key not in _CACHE:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = _walk_forward_predict(df, model, train_window, retrain_every, min_train)
    proba, imp, fits = _CACHE[key]
    return proba.copy(), dict(imp), fits


def _walk_forward_predict(df, model, train_window, retrain_every, min_train):
    X = make_features(df)
    y = make_label(df)
    valid = X.notna().all(axis=1).to_numpy()
    Xv, yv = X.to_numpy(), y.to_numpy()
    proba = np.full(len(df), np.nan)
    importances, fits = np.zeros(len(FEATURES)), 0

    first_valid = int(np.argmax(valid)) if valid.any() else len(df)
    t0 = first_valid + min_train
    while t0 < len(df):
        t1 = min(t0 + retrain_every, len(df))
        # Labels for rows <= t0-1 are known at close t0 (they need close t0 at most).
        lo = max(first_valid, t0 - train_window)
        tr = np.arange(lo, t0)
        tr = tr[valid[tr] & ~np.isnan(yv[tr])]
        if len(tr) >= 100 and len(np.unique(yv[tr])) == 2:
            m = _model(model).fit(Xv[tr], yv[tr])
            pr = np.arange(t0, t1)
            pr = pr[valid[pr]]
            if len(pr):
                proba[pr] = m.predict_proba(Xv[pr])[:, 1]
            importances += _importance(m)
            fits += 1
        t0 = t1

    imp = importances / max(fits, 1)
    if imp.sum() > 0:
        imp = imp / imp.sum()
    return pd.Series(proba, index=df.index), dict(zip(FEATURES, np.round(imp, 4).tolist())), fits


def _importance(m) -> np.ndarray:
    est = m[-1] if hasattr(m, "steps") else m
    if hasattr(est, "feature_importances_"):
        return est.feature_importances_
    return np.abs(est.coef_[0])


def ml_signals(df, model="logistic", threshold=0.52, train_window=756, retrain_every=63):
    proba, _, _ = walk_forward_predict(df, model, train_window, retrain_every)
    # Hysteresis band: stay long until probability falls clearly below 0.5.
    entry = proba > threshold
    exit_ = proba < (1 - threshold)
    pos = np.zeros(len(proba))
    held = 0.0
    for i, (e, x) in enumerate(zip(entry.to_numpy(), exit_.to_numpy())):
        if held == 0 and e:
            held = 1.0
        elif held == 1 and x:
            held = 0.0
        pos[i] = held
    return pd.Series(pos, index=df.index)


ML_STRATEGY = Strategy(
    "ml", "ML Direction Model",
    "Walk-forward classifier (logistic regression or random forest) that predicts "
    "next-day direction from technical features; goes long when P(up) > threshold.",
    [Param("model", "logistic", ["logistic", "random_forest"], "Model", "choice"),
     Param("threshold", 0.52, [0.50, 0.52, 0.55], "P(up) threshold", "float"),
     Param("train_window", 756, [504, 756], "Train window (days)"),
     Param("retrain_every", 63, [63], "Retrain every (days)")],
    ml_signals)


def ml_report(df: pd.DataFrame, model: str = "logistic", threshold: float = 0.52,
              train_window: int = 756, retrain_every: int = 63) -> dict:
    proba, imp, fits = walk_forward_predict(df, model, train_window, retrain_every)
    y = make_label(df)
    mask = proba.notna() & y.notna()
    p, yt = proba[mask], y[mask]
    pred = (p > 0.5).astype(int)
    base = float(max(yt.mean(), 1 - yt.mean())) if len(yt) else 0.0
    out = {
        "model": model, "fits": fits, "oos_predictions": int(mask.sum()),
        "accuracy": round(float(accuracy_score(yt, pred)) * 100, 2) if len(yt) else None,
        "precision_up": round(float(precision_score(yt, pred, zero_division=0)) * 100, 2) if len(yt) else None,
        "auc": round(float(roc_auc_score(yt, p)), 4) if len(np.unique(yt)) == 2 else None,
        "baseline_accuracy": round(base * 100, 2),
        "up_day_ratio": round(float(yt.mean()) * 100, 2) if len(yt) else None,
        "feature_importance": dict(sorted(imp.items(), key=lambda kv: -kv[1])),
        "dates": [d.strftime("%Y-%m-%d") for d in proba.index],
        "proba": [None if np.isnan(v) else round(float(v), 4) for v in proba.to_numpy()],
    }
    return out
