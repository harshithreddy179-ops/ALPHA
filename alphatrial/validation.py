"""Parameter optimisation, in-sample vs out-of-sample tests and walk-forward analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtester import CostModel, run_backtest
from .metrics import TRADING_DAYS, sharpe
from .strategies import Strategy

OBJECTIVES = {"sharpe", "total_return", "calmar", "sortino"}


def _score(metrics: dict, objective: str) -> float:
    v = metrics.get(objective)
    return float(v) if v is not None else -1e9


def optimize(df: pd.DataFrame, strategy: Strategy, start=None, end=None,
             objective: str = "sharpe", costs: CostModel | None = None,
             capital: float = 100_000.0, grid: list[dict] | None = None,
             min_trades: int = 3, max_combos: int = 400) -> dict:
    """Grid-search the strategy's parameter grid on [start, end] only."""
    grid = (grid or strategy.grid())[:max_combos]
    rows = []
    for params in grid:
        res = run_backtest(df, strategy, params, start, end, capital, costs)
        m = res.metrics
        score = _score(m, objective) if m["num_trades"] >= min_trades else -1e9
        rows.append({"params": params, "score": score, **{k: m[k] for k in
                     ("sharpe", "total_return", "cagr", "max_drawdown", "num_trades", "win_rate", "calmar")}})
    rows.sort(key=lambda r: -r["score"])
    return {"best": rows[0]["params"] if rows else strategy.defaults(), "results": rows,
            "objective": objective}


def _pkey(p: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in p.items())


def verdict(is_sharpe: float, oos_sharpe: float) -> tuple[str, float]:
    """Classify the in-sample → out-of-sample decay."""
    if is_sharpe <= 0:
        return ("No Edge", 0.0)
    decay = 1 - oos_sharpe / is_sharpe
    if oos_sharpe <= 0:
        return ("Overfit", round(decay * 100, 1))
    if decay > 0.5:
        return ("Degraded", round(decay * 100, 1))
    return ("Robust", round(decay * 100, 1))


def train_test(df: pd.DataFrame, strategy: Strategy, split: str | None = None,
               train_ratio: float = 0.6, objective: str = "sharpe",
               costs: CostModel | None = None, capital: float = 100_000.0) -> dict:
    """Optimise on the training period, then evaluate on the unseen test period."""
    if split is None:
        split = df.index[int(len(df) * train_ratio)]
    split = pd.Timestamp(split)
    train_end = df.index[df.index < split][-1]
    test_start = df.index[df.index >= split][0]

    opt = optimize(df, strategy, None, train_end, objective, costs, capital)
    best = opt["best"]
    is_res = run_backtest(df, strategy, best, None, train_end, capital, costs)
    oos_res = run_backtest(df, strategy, best, test_start, None, capital, costs)
    default_oos = run_backtest(df, strategy, strategy.defaults(), test_start, None, capital, costs)

    label, decay = verdict(is_res.metrics["sharpe"], oos_res.metrics["sharpe"])

    return {
        "split_date": test_start.strftime("%Y-%m-%d"),
        "train_period": [df.index[0].strftime("%Y-%m-%d"), train_end.strftime("%Y-%m-%d")],
        "test_period": [test_start.strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d")],
        "best_params": best, "objective": objective,
        "in_sample": is_res.to_dict(), "out_of_sample": oos_res.to_dict(),
        "default_params_oos": default_oos.metrics,
        "verdict": label, "sharpe_decay_pct": decay,
        "combos_tested": len(opt["results"]),
        "top_in_sample": [{**r, "params": _pkey(r["params"])} for r in opt["results"][:10]],
        "heatmap": heatmap(strategy, opt["results"]),
    }


def heatmap(strategy: Strategy, results: list[dict]) -> dict | None:
    """2-D Sharpe surface over the first two numeric parameters (best over the rest)."""
    numeric = [p.name for p in strategy.params if p.kind != "choice"]
    if len(numeric) < 2:
        return None
    a, b = numeric[0], numeric[1]
    xs = sorted({r["params"][a] for r in results})
    ys = sorted({r["params"][b] for r in results})
    z = [[None] * len(xs) for _ in ys]
    for r in results:
        i, j = ys.index(r["params"][b]), xs.index(r["params"][a])
        if z[i][j] is None or r["sharpe"] > z[i][j]:
            z[i][j] = r["sharpe"]
    return {"x_name": a, "y_name": b, "x": xs, "y": ys, "z": z}


def walk_forward(df: pd.DataFrame, strategy: Strategy, train_days: int = 504,
                 test_days: int = 126, anchored: bool = False, objective: str = "sharpe",
                 costs: CostModel | None = None, capital: float = 100_000.0) -> dict:
    """Roll an optimise-then-test window across history and stitch the test segments
    into one genuinely out-of-sample equity curve."""
    idx = df.index
    windows, oos_rets = [], []
    start = 0
    while start + train_days + 20 <= len(idx):
        tr_lo = 0 if anchored else start
        tr_hi = start + train_days - 1
        te_lo = tr_hi + 1
        te_hi = min(te_lo + test_days - 1, len(idx) - 1)
        opt = optimize(df, strategy, idx[tr_lo], idx[tr_hi], objective, costs, capital)
        best = opt["best"]
        is_res = run_backtest(df, strategy, best, idx[tr_lo], idx[tr_hi], capital, costs)
        oos = run_backtest(df, strategy, best, idx[te_lo], idx[te_hi], capital, costs)
        windows.append({
            "train": [idx[tr_lo].strftime("%Y-%m-%d"), idx[tr_hi].strftime("%Y-%m-%d")],
            "test": [idx[te_lo].strftime("%Y-%m-%d"), idx[te_hi].strftime("%Y-%m-%d")],
            "params": _pkey(best),
            "is_sharpe": is_res.metrics["sharpe"], "oos_sharpe": oos.metrics["sharpe"],
            "is_return": is_res.metrics["total_return"], "oos_return": oos.metrics["total_return"],
            "oos_trades": oos.metrics["num_trades"],
        })
        # First day's return relative to starting capital, then daily returns.
        r = oos.equity.pct_change()
        r.iloc[0] = oos.equity.iloc[0] / capital - 1
        oos_rets.append(r)
        start += test_days
        if te_hi >= len(idx) - 1:
            break

    if not windows:
        raise ValueError("Not enough data for walk-forward with these window sizes")

    stitched = pd.concat(oos_rets)
    stitched = stitched[~stitched.index.duplicated()]
    equity = capital * (1 + stitched).cumprod()
    peak = equity.cummax()
    is_mean = float(np.mean([w["is_sharpe"] for w in windows]))
    oos_mean = float(np.mean([w["oos_sharpe"] for w in windows]))
    years = len(stitched) / TRADING_DAYS
    oos_cagr = (equity.iloc[-1] / capital) ** (1 / years) - 1 if years > 0 else 0

    return {
        "windows": windows,
        "dates": [d.strftime("%Y-%m-%d") for d in equity.index],
        "equity": np.round(equity.to_numpy(), 2).tolist(),
        "drawdown": np.round(((equity / peak - 1) * 100).to_numpy(), 3).tolist(),
        "summary": {
            "n_windows": len(windows),
            "oos_total_return": round(float(equity.iloc[-1] / capital - 1) * 100, 2),
            "oos_cagr": round(float(oos_cagr) * 100, 2),
            "oos_sharpe": round(sharpe(stitched), 3),
            "oos_max_drawdown": round(float((equity / peak - 1).min()) * 100, 2),
            "mean_is_sharpe": round(is_mean, 3),
            "mean_oos_sharpe": round(oos_mean, 3),
            "pct_windows_profitable": round(100 * float(np.mean([w["oos_return"] > 0 for w in windows])), 1),
            "verdict": verdict(is_mean, oos_mean)[0],
        },
        "start": equity.index[0].strftime("%Y-%m-%d"),
    }
