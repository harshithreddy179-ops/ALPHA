"""Performance and risk metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    r = returns.dropna() - rf / TRADING_DAYS
    sd = r.std(ddof=1)
    if len(r) < 2 or not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    return float(r.mean() / sd * math.sqrt(TRADING_DAYS))


def sortino(returns: pd.Series) -> float:
    r = returns.dropna()
    downside = r[r < 0]
    dd = math.sqrt((downside ** 2).sum() / max(len(r), 1))
    if dd < 1e-12:
        return 0.0
    return float(r.mean() / dd * math.sqrt(TRADING_DAYS))


def max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """Returns (max drawdown as a negative fraction, longest drawdown in bars)."""
    peak = equity.cummax()
    dd = equity / peak - 1
    underwater = (dd < 0).astype(int).to_numpy()
    longest = run = 0
    for u in underwater:
        run = run + 1 if u else 0
        longest = max(longest, run)
    return float(dd.min()) if len(dd) else 0.0, int(longest)


def cagr(equity: pd.Series, capital: float) -> float:
    if len(equity) < 2 or equity.iloc[-1] <= 0:
        return -1.0 if len(equity) and equity.iloc[-1] <= 0 else 0.0
    years = len(equity) / TRADING_DAYS
    return float((equity.iloc[-1] / capital) ** (1 / years) - 1)


def compute_metrics(equity: pd.Series, trades: pd.DataFrame, position: pd.Series,
                    capital: float) -> dict:
    rets = equity.pct_change().fillna(equity.iloc[0] / capital - 1 if len(equity) else 0.0)
    mdd, mdd_len = max_drawdown(pd.concat([pd.Series([capital]), equity.reset_index(drop=True)]))
    total = float(equity.iloc[-1] / capital - 1) if len(equity) else 0.0
    ann_ret = cagr(equity, capital)
    vol = float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(rets) > 1 else 0.0

    n_trades = int(len(trades))
    if n_trades:
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        win_rate = len(wins) / n_trades
        gross_win, gross_loss = wins["pnl"].sum(), -losses["pnl"].sum()
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")
        avg_trade = float(trades["return_pct"].mean())
        avg_win = float(wins["return_pct"].mean()) if len(wins) else 0.0
        avg_loss = float(losses["return_pct"].mean()) if len(losses) else 0.0
        avg_hold = float(trades["bars_held"].mean())
    else:
        win_rate = profit_factor = avg_trade = avg_win = avg_loss = avg_hold = 0.0

    switches = float(position.diff().abs().sum()) if len(position) else 0.0
    years = max(len(equity) / TRADING_DAYS, 1e-9)

    return {
        "total_return": round(total * 100, 3),
        "cagr": round(ann_ret * 100, 3),
        "volatility": round(vol * 100, 3),
        "sharpe": round(sharpe(rets), 3),
        "sortino": round(sortino(rets), 3),
        "max_drawdown": round(mdd * 100, 3),
        "max_dd_duration": mdd_len,
        "calmar": round(ann_ret / abs(mdd), 3) if mdd < 0 else 0.0,
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 3) if np.isfinite(profit_factor) else None,
        "num_trades": n_trades,
        "avg_trade_pct": round(avg_trade, 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "avg_bars_held": round(avg_hold, 1),
        "exposure": round(float(position.mean()) * 100, 2) if len(position) else 0.0,
        "trades_per_year": round(n_trades / years, 2),
        "turnover": round(switches / years, 2),
        "final_equity": round(float(equity.iloc[-1]), 2) if len(equity) else capital,
    }


METRIC_LABELS = {
    "total_return": "Total Return %", "cagr": "CAGR %", "volatility": "Volatility %",
    "sharpe": "Sharpe", "sortino": "Sortino", "max_drawdown": "Max Drawdown %",
    "calmar": "Calmar", "win_rate": "Win Rate %", "profit_factor": "Profit Factor",
    "num_trades": "Trades", "exposure": "Exposure %",
}
