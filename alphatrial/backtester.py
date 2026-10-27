"""Cash-constrained, cost-aware backtest engine.

Timing model (no look-ahead):
  * the strategy decides a target position using data up to the close of day t;
  * the order is filled at the OPEN of day t+1, adjusted for slippage;
  * equity is marked to market at every close.
Shares are whole numbers, there's no leverage, and costs are paid from cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .metrics import compute_metrics
from .strategies import Strategy


@dataclass
class CostModel:
    commission_bps: float = 5.0   # % of traded notional, in basis points
    slippage_bps: float = 5.0     # adverse price move on each fill, in basis points
    fixed_fee: float = 0.0        # flat fee per order

    @property
    def total_bps(self) -> float:
        return self.commission_bps + self.slippage_bps

    def to_dict(self) -> dict:
        return {"commission_bps": self.commission_bps, "slippage_bps": self.slippage_bps,
                "fixed_fee": self.fixed_fee}


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    position: pd.Series
    target: pd.Series
    trades: pd.DataFrame
    metrics: dict
    costs_paid: float
    params: dict = field(default_factory=dict)

    def to_dict(self, include_series: bool = True) -> dict:
        out = {"metrics": self.metrics, "params": self.params,
               "costs_paid": round(self.costs_paid, 2),
               "trades": _trades_json(self.trades)}
        if include_series:
            out["dates"] = [d.strftime("%Y-%m-%d") for d in self.equity.index]
            out["equity"] = np.round(self.equity.to_numpy(), 2).tolist()
            out["drawdown"] = np.round((self.equity / self.equity.cummax() - 1).to_numpy() * 100, 3).tolist()
            out["position"] = self.position.astype(int).tolist()
        return out


def _trades_json(trades: pd.DataFrame) -> list[dict]:
    if trades.empty:
        return []
    t = trades.copy()
    for c in ("entry_date", "exit_date"):
        t[c] = t[c].dt.strftime("%Y-%m-%d")
    return t.round(4).to_dict(orient="records")


def simulate(df: pd.DataFrame, target: pd.Series, capital: float = 100_000.0,
             costs: CostModel | None = None, allocation: float = 1.0) -> BacktestResult:
    """Execute a target-position series (values in [0, 1]) against OHLC data."""
    costs = costs or CostModel()
    comm, slip, fee = costs.commission_bps / 1e4, costs.slippage_bps / 1e4, costs.fixed_fee
    opens, closes = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    tgt = target.reindex(df.index).fillna(0).to_numpy(float)
    n = len(df)
    dates = df.index

    cash, shares = float(capital), 0
    equity = np.empty(n)
    pos = np.zeros(n)
    costs_paid = 0.0
    trades: list[dict] = []
    open_trade: dict | None = None

    for i in range(n):
        desired = tgt[i - 1] if i > 0 else 0.0  # decision from the previous close
        if desired > 0 and shares == 0:
            price = opens[i] * (1 + slip)
            budget = cash * min(allocation * desired, 1.0) - fee
            qty = int(budget // (price * (1 + comm))) if budget > 0 else 0
            if qty > 0:
                cost = qty * price * comm + fee + qty * opens[i] * slip
                cash -= qty * price * (1 + comm) + fee
                shares = qty
                costs_paid += cost
                open_trade = {"entry_date": dates[i], "entry_price": price, "shares": qty,
                              "entry_cost": qty * price * (1 + comm) + fee}
        elif desired <= 0 and shares > 0:
            price = opens[i] * (1 - slip)
            proceeds = shares * price * (1 - comm) - fee
            costs_paid += shares * price * comm + fee + shares * opens[i] * slip
            cash += proceeds
            _close_trade(trades, open_trade, dates[i], price, proceeds)
            shares, open_trade = 0, None
        equity[i] = cash + shares * closes[i]
        pos[i] = 1.0 if shares > 0 else 0.0

    if open_trade is not None:  # mark the still-open position at the final close
        proceeds = shares * closes[-1] * (1 - comm) - fee
        _close_trade(trades, open_trade, dates[-1], closes[-1], proceeds, still_open=True)

    eq = pd.Series(equity, index=dates, name="equity")
    rets = eq.pct_change().fillna(0.0)
    trades_df = pd.DataFrame(trades)
    position = pd.Series(pos, index=dates)
    metrics = compute_metrics(eq, trades_df, position, capital)
    metrics["costs_paid"] = round(costs_paid, 2)
    metrics["costs_pct_of_capital"] = round(costs_paid / capital * 100, 3)
    return BacktestResult(eq, rets, position, target.reindex(df.index).fillna(0), trades_df,
                          metrics, costs_paid)


def _close_trade(trades, open_trade, date, price, proceeds, still_open=False):
    pnl = proceeds - open_trade["entry_cost"]
    trades.append({
        "entry_date": open_trade["entry_date"], "exit_date": date,
        "entry_price": open_trade["entry_price"], "exit_price": price,
        "shares": open_trade["shares"], "pnl": pnl,
        "return_pct": pnl / open_trade["entry_cost"] * 100,
        "bars_held": None, "open": still_open,
    })
    t = trades[-1]
    t["bars_held"] = int(np.busday_count(t["entry_date"].date(), t["exit_date"].date()))


def slice_period(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    return df.loc[pd.Timestamp(start) if start else None: pd.Timestamp(end) if end else None]


def run_backtest(df: pd.DataFrame, strategy: Strategy, params: dict | None = None,
                 start=None, end=None, capital: float = 100_000.0,
                 costs: CostModel | None = None, target: pd.Series | None = None) -> BacktestResult:
    """Signals are computed on all history up to `end` (indicators warm up on earlier
    data, and nothing after `end` is visible), then traded only inside [start, end]."""
    hist = slice_period(df, None, end)
    if target is None:
        target = strategy.signals(hist, params)
    window = slice_period(hist, start, end)
    res = simulate(window, target.reindex(window.index), capital, costs)
    res.params = strategy.resolve(params) if strategy.params else (params or {})
    return res


def buy_and_hold(df: pd.DataFrame, start=None, end=None, capital: float = 100_000.0,
                 costs: CostModel | None = None) -> BacktestResult:
    window = slice_period(df, start, end)
    # Target is 1 from the first bar, so the engine buys at the second bar's open.
    # Shift so the purchase happens at the very first open, as a passive investor would.
    target = pd.Series(1.0, index=window.index)
    padded = pd.concat([window.iloc[:1], window])
    padded.index = [window.index[0] - pd.Timedelta(days=1)] + list(window.index)
    res = simulate(padded, pd.Series(1.0, index=padded.index), capital, costs)
    eq = res.equity.iloc[1:]
    trades = res.trades
    pos = res.position.iloc[1:]
    metrics = compute_metrics(eq, trades, pos, capital)
    metrics["costs_paid"] = round(res.costs_paid, 2)
    metrics["costs_pct_of_capital"] = round(res.costs_paid / capital * 100, 3)
    return BacktestResult(eq, eq.pct_change().fillna(0.0), pos, target, trades, metrics,
                          res.costs_paid, {})
