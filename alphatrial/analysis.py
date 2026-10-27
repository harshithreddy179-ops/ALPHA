"""Multi-strategy comparison, transaction-cost sensitivity and the written report."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtester import BacktestResult, CostModel, buy_and_hold, run_backtest
from .regimes import classify_rule_based, regime_performance, yearly_returns
from .strategies import Strategy, get

COST_LEVELS = [0, 2, 5, 10, 15, 20, 30, 50, 75, 100]


def compare(df: pd.DataFrame, specs: list[dict], start=None, end=None,
            capital: float = 100_000.0, costs: CostModel | None = None) -> dict:
    """Backtest several strategies plus buy-and-hold on the same period and costs."""
    results: dict[str, BacktestResult] = {}
    for spec in specs:
        strat = get(spec["key"], spec.get("rules"))
        label = spec.get("label") or strat.name
        results[label] = run_backtest(df, strat, spec.get("params"), start, end, capital, costs)
    bh = buy_and_hold(df, start, end, capital, costs)
    results["Buy & Hold"] = bh

    leaderboard = []
    for name, r in results.items():
        m = r.metrics
        leaderboard.append({"name": name, **m,
                            "excess_return": round(m["total_return"] - bh.metrics["total_return"], 2),
                            "excess_sharpe": round(m["sharpe"] - bh.metrics["sharpe"], 3)})
    leaderboard.sort(key=lambda x: -x["sharpe"])
    for i, row in enumerate(leaderboard, 1):
        row["rank"] = i

    rets = {k: v.returns for k, v in results.items()}
    labels = classify_rule_based(df)["regime"]
    corr = pd.DataFrame(rets).corr().round(3)
    return {
        "leaderboard": leaderboard,
        "series": {k: v.to_dict() for k, v in results.items()},
        "correlation": {"names": list(corr.columns), "matrix": corr.fillna(0).values.tolist()},
        "regimes": regime_performance(rets, labels),
        "yearly": yearly_returns(rets),
        "_results": results,
    }


def cost_sensitivity(df: pd.DataFrame, specs: list[dict], start=None, end=None,
                     capital: float = 100_000.0, levels: list[float] | None = None) -> dict:
    """Re-run each strategy across round-trip cost levels (split evenly between
    commission and slippage) and find the break-even cost."""
    levels = levels or COST_LEVELS
    out = {"levels": levels, "strategies": []}
    named = [(get(s["key"], s.get("rules")), s) for s in specs]
    for strat, spec in named:
        label = spec.get("label") or strat.name
        target = strat.signals(df.loc[:pd.Timestamp(end)] if end else df, spec.get("params"))
        rows = []
        for bps in levels:
            cm = CostModel(commission_bps=bps / 2, slippage_bps=bps / 2)
            r = run_backtest(df, strat, spec.get("params"), start, end, capital, cm, target=target)
            rows.append({"bps": bps, "total_return": r.metrics["total_return"],
                         "sharpe": r.metrics["sharpe"], "cagr": r.metrics["cagr"],
                         "costs_paid": r.metrics["costs_paid"], "trades": r.metrics["num_trades"]})
        out["strategies"].append({"name": label, "rows": rows,
                                  "break_even_bps": _break_even(rows, "total_return"),
                                  "turnover": r.metrics["turnover"]})
    bh_rows = []
    for bps in levels:
        cm = CostModel(commission_bps=bps / 2, slippage_bps=bps / 2)
        r = buy_and_hold(df, start, end, capital, cm)
        bh_rows.append({"bps": bps, "total_return": r.metrics["total_return"],
                        "sharpe": r.metrics["sharpe"], "cagr": r.metrics["cagr"],
                        "costs_paid": r.metrics["costs_paid"], "trades": r.metrics["num_trades"]})
    out["buy_and_hold"] = bh_rows
    # Cost level at which each strategy stops beating buy-and-hold.
    for s in out["strategies"]:
        diff = [{"bps": a["bps"], "total_return": a["total_return"] - b["total_return"]}
                for a, b in zip(s["rows"], bh_rows)]
        s["beats_bh_until_bps"] = _break_even(diff, "total_return")
        gross, net = s["rows"][0]["total_return"], s["rows"][min(3, len(levels) - 1)]["total_return"]
        s["return_lost_at_10bps"] = round(gross - net, 2)
    return out


def _break_even(rows: list[dict], key: str) -> float | None:
    """Linear interpolation of the cost level where `key` crosses zero."""
    if rows[0][key] <= 0:
        return 0.0
    for a, b in zip(rows, rows[1:]):
        if a[key] > 0 >= b[key]:
            return round(a["bps"] + (b["bps"] - a["bps"]) * a[key] / (a[key] - b[key]), 1)
    return None  # still positive at the highest level tested


def strengths_weaknesses(name: str, m: dict, bh: dict, regimes: list[dict] | None = None,
                         cost_row: dict | None = None, validation: dict | None = None) -> dict:
    s, w = [], []
    if m["sharpe"] > bh["sharpe"] + 0.1:
        s.append(f"Better risk-adjusted return than buy-and-hold (Sharpe {m['sharpe']:.2f} vs {bh['sharpe']:.2f}).")
    elif m["sharpe"] < bh["sharpe"] - 0.1:
        w.append(f"Lower Sharpe than simply holding ({m['sharpe']:.2f} vs {bh['sharpe']:.2f}).")
    if m["max_drawdown"] > bh["max_drawdown"] + 5:
        s.append(f"Shallower worst drawdown ({m['max_drawdown']:.1f}% vs {bh['max_drawdown']:.1f}%).")
    elif m["max_drawdown"] < bh["max_drawdown"] - 5:
        w.append(f"Deeper drawdown than buy-and-hold ({m['max_drawdown']:.1f}%).")
    if m["total_return"] < bh["total_return"] and m["sharpe"] >= bh["sharpe"]:
        s.append("Earns less in absolute terms but with less risk per unit of return.")
    if m["total_return"] > bh["total_return"]:
        s.append(f"Higher total return than buy-and-hold ({m['total_return']:.1f}% vs {bh['total_return']:.1f}%).")
    if m["exposure"] < 60:
        s.append(f"Only invested {m['exposure']:.0f}% of the time, so capital is free and market risk is lower.")
    if m["num_trades"] < 10:
        w.append(f"Only {m['num_trades']} trades, too few for statistically reliable conclusions.")
    if m["trades_per_year"] > 20:
        w.append(f"High trading frequency ({m['trades_per_year']:.0f} trades/yr) makes it sensitive to costs.")
    if m["win_rate"] >= 55:
        s.append(f"High win rate ({m['win_rate']:.0f}%).")
    elif m["num_trades"] >= 10 and m["win_rate"] < 40:
        w.append(f"Low win rate ({m['win_rate']:.0f}%); relies on a few large winners.")
    if m.get("profit_factor") and m["profit_factor"] > 1.5:
        s.append(f"Strong profit factor ({m['profit_factor']:.2f}).")
    if regimes:
        perf = [(r["regime"], r[name]["ann_return"]) for r in regimes
                if name in r and r[name]["ann_return"] is not None and r["days"] > 40]
        if perf:
            best = max(perf, key=lambda x: x[1])
            worst = min(perf, key=lambda x: x[1])
            s.append(f"Performs best in {best[0]} markets ({best[1]:+.1f}% annualised).")
            if worst[1] < 0:
                w.append(f"Loses money in {worst[0]} markets ({worst[1]:+.1f}% annualised).")
    if cost_row:
        be = cost_row.get("break_even_bps")
        if be is not None and be < 20:
            w.append(f"Turns unprofitable at only ~{be:.0f} bps round-trip cost.")
        elif be is None:
            s.append("Stays profitable even at 100 bps round-trip cost.")
    if validation:
        v = validation.get("verdict")
        if v == "Robust":
            s.append(f"Held up out of sample (Sharpe decay {validation.get('sharpe_decay_pct')}%).")
        elif v in ("Overfit", "Degraded", "No Edge"):
            w.append(f"Out-of-sample verdict: {v} (Sharpe decay {validation.get('sharpe_decay_pct')}%).")
        if validation.get("pbo") is not None and validation["pbo"] > 50:
            w.append(f"High probability of backtest overfitting (PBO {validation['pbo']}%): the best "
                     "in-sample parameters usually rank below median on unseen data.")
    return {"strengths": s, "weaknesses": w}


def build_report(df: pd.DataFrame, specs: list[dict], dataset: str, start=None, end=None,
                 capital: float = 100_000.0, costs: CostModel | None = None,
                 include_validation: bool = True) -> dict:
    from .validation import train_test

    cmp = compare(df, specs, start, end, capital, costs)
    cs = cost_sensitivity(df, specs, start, end, capital)
    cost_by_name = {s["name"]: s for s in cs["strategies"]}
    bh = next(r for r in cmp["leaderboard"] if r["name"] == "Buy & Hold")

    sections = []
    for spec in specs:
        strat: Strategy = get(spec["key"], spec.get("rules"))
        name = spec.get("label") or strat.name
        m = next(r for r in cmp["leaderboard"] if r["name"] == name)
        val = None
        if include_validation and strat.params and strat.key != "ml":
            try:
                tt = train_test(df, strat, costs=costs, capital=capital)
                val = {k: tt[k] for k in ("verdict", "sharpe_decay_pct", "best_params",
                                          "rank_correlation")}
                val["is_sharpe"] = tt["in_sample"]["metrics"]["sharpe"]
                val["oos_sharpe"] = tt["out_of_sample"]["metrics"]["sharpe"]
                val["pbo"] = tt["pbo"]["pbo"] if tt["pbo"] else None
            except Exception as e:  # pragma: no cover - report should still render
                val = {"verdict": "n/a", "error": str(e)}
        sw = strengths_weaknesses(name, m, bh, cmp["regimes"], cost_by_name.get(name), val)
        sections.append({"name": name, "metrics": m, "validation": val,
                         "cost": cost_by_name.get(name), **sw})

    ranked = [r for r in cmp["leaderboard"] if r["name"] != "Buy & Hold"]
    winner = ranked[0] if ranked else None
    beats = [r["name"] for r in ranked if r["sharpe"] > bh["sharpe"]]
    summary = []
    if winner:
        summary.append(f"Best risk-adjusted strategy: **{winner['name']}** with Sharpe {winner['sharpe']:.2f}, "
                       f"total return {winner['total_return']:.1f}% and max drawdown {winner['max_drawdown']:.1f}%.")
    summary.append(f"Buy & Hold benchmark: Sharpe {bh['sharpe']:.2f}, return {bh['total_return']:.1f}%, "
                   f"max drawdown {bh['max_drawdown']:.1f}%.")
    summary.append(f"{len(beats)} of {len(ranked)} strategies beat buy-and-hold on a risk-adjusted basis"
                   + (f": {', '.join(beats)}." if beats else "."))
    robust = [s["name"] for s in sections if s["validation"] and s["validation"].get("verdict") == "Robust"]
    overfit = [s["name"] for s in sections if s["validation"] and s["validation"].get("verdict") in ("Overfit", "No Edge")]
    if robust:
        summary.append(f"Survived out-of-sample testing: {', '.join(robust)}.")
    if overfit:
        summary.append(f"Failed out-of-sample (likely overfit / no edge): {', '.join(overfit)}.")

    return {
        "dataset": dataset,
        "period": [cmp["series"]["Buy & Hold"]["dates"][0], cmp["series"]["Buy & Hold"]["dates"][-1]],
        "costs": (costs or CostModel()).to_dict(), "capital": capital,
        "summary": summary, "leaderboard": cmp["leaderboard"], "sections": sections,
        "regimes": cmp["regimes"], "yearly": cmp["yearly"], "cost_sensitivity": cs,
        "methodology": METHODOLOGY,
    }


METHODOLOGY = [
    "Signals are computed from data up to the close of day t and executed at the open of day t+1 (no look-ahead).",
    "Orders are for whole shares, never exceed available cash, and pay commission + slippage on every fill.",
    "Buy-and-hold pays the same costs and is measured over the same period.",
    "Strategies are ranked by Sharpe ratio (risk-adjusted), not by raw profit.",
    "Parameters are optimised on the training period only and then frozen for the test period.",
    "Walk-forward analysis re-optimises on a rolling window and stitches only out-of-sample segments.",
    "PBO (Probability of Backtest Overfitting) uses combinatorially symmetric cross-validation over the parameter grid.",
    "Regimes are labelled with trailing information only; returns are attributed to the regime known at the prior close.",
]


def report_markdown(rep: dict) -> str:
    L = [f"# AlphaTrial Strategy Report: {rep['dataset']}", "",
         f"Period: {rep['period'][0]} → {rep['period'][1]}  ",
         f"Capital: {rep['capital']:,.0f}  ",
         f"Costs: commission {rep['costs']['commission_bps']} bps, slippage {rep['costs']['slippage_bps']} bps per side", "",
         "## Executive summary", ""]
    L += [f"- {s}" for s in rep["summary"]]
    L += ["", "## Leaderboard (ranked by Sharpe)", "",
          "| # | Strategy | Return % | CAGR % | Sharpe | Sortino | Max DD % | Win % | Trades | Exposure % |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["leaderboard"]:
        L.append(f"| {r['rank']} | {r['name']} | {r['total_return']:.1f} | {r['cagr']:.1f} | {r['sharpe']:.2f} | "
                 f"{r['sortino']:.2f} | {r['max_drawdown']:.1f} | {r['win_rate']:.0f} | {r['num_trades']} | {r['exposure']:.0f} |")
    for s in rep["sections"]:
        L += ["", f"## {s['name']}", ""]
        if s["validation"] and "is_sharpe" in s["validation"]:
            v = s["validation"]
            L.append(f"Out-of-sample check: **{v['verdict']}**. In-sample Sharpe {v['is_sharpe']:.2f} → "
                     f"out-of-sample {v['oos_sharpe']:.2f}" + (f", PBO {v['pbo']}%" if v.get("pbo") is not None else "") + ".")
            L.append("")
        if s["cost"]:
            be = s["cost"]["break_even_bps"]
            L.append(f"Break-even round-trip cost: {'> 100' if be is None else be} bps.")
            L.append("")
        L.append("**Strengths**")
        L += [f"- {x}" for x in s["strengths"]] or ["- None identified"]
        L += ["", "**Weaknesses**"]
        L += [f"- {x}" for x in s["weaknesses"]] or ["- None identified"]
    L += ["", "## Methodology", ""] + [f"- {m}" for m in rep["methodology"]]
    L += ["", "## Limitations", "",
          "- Past performance on historical data does not guarantee future results.",
          "- Fills assume the open price plus fixed slippage; real liquidity and market impact may differ.",
          "- Long-only, single-asset strategies; no dividends, borrowing costs or taxes are modelled."]
    return "\n".join(L)
