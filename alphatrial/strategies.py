"""Rule-based strategies.

A strategy turns price data into a *target position* series (1 = long, 0 = flat)
where the value at row t is decided with information available at the close of t.
The backtester is responsible for executing it on the *next* bar, which is what
keeps the whole pipeline free of look-ahead bias.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Param:
    name: str
    default: Any
    grid: list[Any]
    label: str = ""
    kind: str = "int"  # int | float | choice


@dataclass
class Strategy:
    key: str
    name: str
    description: str
    params: list[Param]
    fn: Callable[..., pd.Series]
    constraint: Callable[[dict], bool] = field(default=lambda p: True)

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.params}

    def resolve(self, params: dict | None) -> dict:
        out = self.defaults()
        for p in self.params:
            if params and p.name in params and params[p.name] is not None:
                v = params[p.name]
                out[p.name] = int(v) if p.kind == "int" else (float(v) if p.kind == "float" else v)
        return out

    def grid(self, overrides: dict[str, list] | None = None) -> list[dict]:
        names = [p.name for p in self.params]
        values = [(overrides or {}).get(p.name) or p.grid for p in self.params]
        combos = [dict(zip(names, v)) for v in itertools.product(*values)]
        return [c for c in combos if self.constraint(c)]

    def signals(self, df: pd.DataFrame, params: dict | None = None) -> pd.Series:
        p = self.resolve(params)
        pos = self.fn(df, **p)
        return pos.reindex(df.index).fillna(0).clip(0, 1).astype(float)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "description": self.description,
            "params": [{"name": p.name, "label": p.label or p.name, "default": p.default,
                        "grid": p.grid, "kind": p.kind} for p in self.params],
        }


def _stateful(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """Enter on `entry`, hold until `exit_`. Both are boolean series known at close t."""
    e, x = entry.fillna(False).to_numpy(), exit_.fillna(False).to_numpy()
    pos = np.zeros(len(e))
    held = 0.0
    for i in range(len(e)):
        if held == 0 and e[i]:
            held = 1.0
        elif held == 1 and x[i]:
            held = 0.0
        pos[i] = held
    return pd.Series(pos, index=entry.index)


# --- strategy implementations --------------------------------------------------------

def sma_crossover(df, fast=20, slow=50):
    f, s = ind.sma(df["Close"], fast), ind.sma(df["Close"], slow)
    return (f > s).astype(float).where(s.notna(), 0.0)


def rsi_reversion(df, period=14, oversold=30, overbought=70):
    r = ind.rsi(df["Close"], period)
    return _stateful(r < oversold, r > overbought)


def momentum_strategy(df, lookback=60, threshold=0.0):
    m = ind.momentum(df["Close"], lookback)
    return (m > threshold).astype(float).where(m.notna(), 0.0)


STRATEGIES: dict[str, Strategy] = {}


def register(s: Strategy) -> Strategy:
    STRATEGIES[s.key] = s
    return s


register(Strategy(
    "sma_cross", "Moving Average Crossover",
    "Buy when the short-term average price rises above the long-term average, sell when it falls below.",
    [Param("fast", 20, [5, 10, 20, 30, 50], "Short average (days)"),
     Param("slow", 50, [50, 100, 150, 200], "Long average (days)")],
    sma_crossover, constraint=lambda p: p["fast"] < p["slow"]))

register(Strategy(
    "rsi", "RSI (Buy Low, Sell High)",
    "Buy when RSI shows the stock has fallen too much, sell when it shows it has risen too much.",
    [Param("period", 14, [7, 14, 21], "RSI days"),
     Param("oversold", 30, [20, 25, 30, 35], "Buy below"),
     Param("overbought", 70, [60, 65, 70, 75, 80], "Sell above")],
    rsi_reversion, constraint=lambda p: p["oversold"] < p["overbought"]))

register(Strategy(
    "momentum", "Momentum",
    "Hold the stock while its price is higher than it was N days ago, otherwise stay in cash.",
    [Param("lookback", 60, [20, 40, 60, 90, 120, 180, 250], "Look back (days)"),
     Param("threshold", 0.0, [0.0, 0.02, 0.05], "Min. rise (0.05 = 5%)", "float")],
    momentum_strategy))

# --- user-designed rule strategies ---------------------------------------------------

_OPS = {
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    "crosses_above": lambda a, b: (a > b) & (a.shift(1) <= b.shift(1)),
    "crosses_below": lambda a, b: (a < b) & (a.shift(1) >= b.shift(1)),
}


def _operand(df: pd.DataFrame, spec: dict | float | int) -> pd.Series:
    if isinstance(spec, (int, float)):
        return pd.Series(float(spec), index=df.index)
    kind = str(spec.get("type", "price")).lower()
    n = int(spec.get("n", 14))
    c = df["Close"]
    if kind == "value":
        return pd.Series(float(spec.get("value", 0)), index=df.index)
    if kind == "price":
        return df[spec.get("field", "Close")]
    if kind == "sma":
        return ind.sma(c, n)
    if kind == "ema":
        return ind.ema(c, n)
    if kind == "rsi":
        return ind.rsi(c, n)
    if kind == "momentum":
        return ind.momentum(c, n) * 100
    if kind == "volatility":
        return ind.volatility(c, n) * 100
    if kind == "bb_lower":
        return ind.bollinger(c, n, float(spec.get("k", 2)))[0]
    if kind == "bb_upper":
        return ind.bollinger(c, n, float(spec.get("k", 2)))[2]
    if kind == "volume_sma":
        return df["Volume"].rolling(n, min_periods=n).mean()
    if kind == "volume":
        return df["Volume"]
    raise ValueError(f"Unknown operand type '{kind}'")


def _conditions(df: pd.DataFrame, conds: list[dict], mode: str) -> pd.Series:
    if not conds:
        return pd.Series(False, index=df.index)
    parts = []
    for c in conds:
        op = c.get("op", ">")
        if op not in _OPS:
            raise ValueError(f"Unknown operator '{op}'")
        a, b = _operand(df, c["left"]), _operand(df, c["right"])
        parts.append(_OPS[op](a, b) & a.notna() & b.notna())
    combined = parts[0]
    for p in parts[1:]:
        combined = (combined | p) if mode == "any" else (combined & p)
    return combined


def custom_rules(df: pd.DataFrame, rules: dict) -> pd.Series:
    """rules = {"entry": [cond...], "exit": [cond...], "entry_mode": "all"|"any", "exit_mode": ...}

    A condition is {"left": operand, "op": ">", "right": operand}, where an operand is a
    number or {"type": "sma", "n": 50}. With no exit rules the position closes as soon as
    the entry conditions stop holding.
    """
    entry = _conditions(df, rules.get("entry", []), rules.get("entry_mode", "all"))
    if rules.get("exit"):
        exit_ = _conditions(df, rules["exit"], rules.get("exit_mode", "any"))
    else:
        exit_ = ~entry
    return _stateful(entry, exit_)


def custom_strategy(rules: dict, name: str = "Custom Rules") -> Strategy:
    return Strategy("custom", name, "User-designed rule set.", [],
                    lambda df: custom_rules(df, rules))


def get(key: str, rules: dict | None = None) -> Strategy:
    if key == "custom":
        if not rules:
            raise ValueError("Custom strategy requires a rules object")
        return custom_strategy(rules)
    if key == "ml":
        from .ml import ML_STRATEGY
        return ML_STRATEGY
    if key not in STRATEGIES:
        raise KeyError(f"Unknown strategy '{key}'")
    return STRATEGIES[key]


def all_strategies() -> list[dict]:
    from .ml import ML_STRATEGY
    return [s.to_dict() for s in STRATEGIES.values()] + [ML_STRATEGY.to_dict()]
