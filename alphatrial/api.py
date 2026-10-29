"""FastAPI service exposing the AlphaTrial engine and serving the dashboard."""

from __future__ import annotations

import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import data as data_mod
from . import indicators as ind
from . import market
from .analysis import build_report, compare, cost_sensitivity, report_markdown
from .backtester import CostModel, buy_and_hold, run_backtest, slice_period
from .ml import ml_report
from .regimes import classify_rule_based, regime_performance
from .strategies import all_strategies, get
from .validation import optimize, train_test, walk_forward

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
# Serverless platforms (Vercel) only allow writes under /tmp.
UPLOAD_DIR = (Path(tempfile.gettempdir()) / "alphatrial_uploads" if os.environ.get("VERCEL")
              else data_mod.DATA_DIR / "uploads")

app = FastAPI(title="AlphaTrial", version="1.0.0",
              description="Build, backtest & validate rule-based trading strategies.")


# ---------------------------------------------------------------- helpers

def clean(obj: Any) -> Any:
    """Make numpy/pandas values JSON safe (NaN/inf become null)."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    return obj


def ok(payload: Any) -> JSONResponse:
    return JSONResponse(clean(payload))


@lru_cache(maxsize=32)
def _load(name: str) -> pd.DataFrame:
    up = UPLOAD_DIR / f"{name}.csv"
    if up.exists():
        return data_mod.load_csv(up)
    return data_mod.load_dataset(name)


def load(name: str) -> pd.DataFrame:
    try:
        if market.is_live(name):
            return market.fetch(name)  # has its own time-based cache
        return _load(name)
    except data_mod.DataError as e:
        raise HTTPException(404, str(e))


class Costs(BaseModel):
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    fixed_fee: float = 0.0

    def model(self) -> CostModel:
        return CostModel(self.commission_bps, self.slippage_bps, self.fixed_fee)


class StrategySpec(BaseModel):
    key: str
    params: dict[str, Any] | None = None
    rules: dict[str, Any] | None = None
    label: str | None = None


class Base(BaseModel):
    dataset: str
    start: str | None = None
    end: str | None = None
    capital: float = Field(100_000.0, gt=0)
    costs: Costs = Costs()


class BacktestReq(Base, StrategySpec):
    pass


class CompareReq(Base):
    strategies: list[StrategySpec]


class ValidateReq(Base):
    key: str
    split: str | None = None
    train_ratio: float = Field(0.6, gt=0.2, lt=0.9)
    objective: str = "sharpe"


class WalkForwardReq(Base):
    key: str
    train_days: int = Field(504, ge=120)
    test_days: int = Field(126, ge=20)
    anchored: bool = False
    objective: str = "sharpe"


class RegimeReq(Base):
    strategies: list[StrategySpec] = []
    detail: bool = False  # False: Bull/Bear/Sideways only; True: also split by volatility


class MLReq(Base):
    model: str = "logistic"
    threshold: float = 0.52
    train_window: int = 756
    retrain_every: int = 63


class ReportReq(CompareReq):
    validation: bool = True


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except HTTPException:
        raise
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


def _spec(s: StrategySpec) -> dict:
    return s.model_dump()


# ---------------------------------------------------------------- endpoints

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/datasets")
def datasets():
    names = data_mod.list_datasets()
    uploads = sorted(p.stem for p in UPLOAD_DIR.glob("*.csv")) if UPLOAD_DIR.exists() else []
    out = []
    for n in names + uploads:
        df = load(n)
        out.append({"name": n, "rows": len(df), "start": df.index[0].strftime("%Y-%m-%d"),
                    "end": df.index[-1].strftime("%Y-%m-%d"), "uploaded": n in uploads})
    return ok(out)


@app.get("/api/universe")
def universe():
    return ok(market.universe())


@app.get("/api/info/{name}")
def info(name: str):
    df = load(name)
    return ok({"name": name, "rows": len(df), "start": df.index[0], "end": df.index[-1],
               "last_close": round(float(df["Close"].iloc[-1]), 2),
               "note": df.attrs.get("note")})


@app.get("/api/market")
def market_snapshot(group: str = "nifty50", exchange: str = "NSE"):
    u = market.universe()
    if group == "indices":
        items = u["indices"]
        syms = [i["symbol"] for i in items]
    else:
        items = u["nifty50"]
        syms = [market.normalise(i["symbol"], exchange) for i in items]
    rows = market.snapshot(syms)
    for row, item in zip(rows, items):
        row["name"] = item["name"]
        row["sector"] = item.get("sector", "Index")
    return ok({"group": group, "exchange": exchange, "rows": rows})


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "File too large (25 MB max)")
    try:
        df = data_mod.load_csv(raw)
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")
    name = re.sub(r"[^A-Za-z0-9_-]", "_", Path(file.filename or "upload").stem)[:40] or "upload"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(UPLOAD_DIR / f"{name}.csv")
    _load.cache_clear()
    return ok({"name": name, "rows": len(df), "start": df.index[0], "end": df.index[-1]})


@app.get("/api/strategies")
def strategies():
    return ok(all_strategies())


@app.get("/api/prices/{name}")
def prices(name: str, start: str | None = None, end: str | None = None):
    df = slice_period(load(name), start, end)
    return ok({"dates": [d.strftime("%Y-%m-%d") for d in df.index],
               **{c.lower(): np.round(df[c].to_numpy(), 4).tolist() for c in df.columns}})


def _overlays(key: str, params: dict, df: pd.DataFrame) -> dict:
    c = df["Close"]
    lines, panel = {}, None
    if key == "sma_cross":
        lines = {f"SMA {params['fast']}": ind.sma(c, params["fast"]), f"SMA {params['slow']}": ind.sma(c, params["slow"])}
    elif key == "rsi":
        panel = {"name": f"RSI {params['period']}", "values": ind.rsi(c, params["period"]),
                 "levels": [params["oversold"], params["overbought"]]}
    elif key == "momentum":
        panel = {"name": f"{params['lookback']}d momentum %", "values": ind.momentum(c, params["lookback"]) * 100,
                 "levels": [params["threshold"] * 100]}
    ser = lambda s: [None if not np.isfinite(v) else round(float(v), 4) for v in s.to_numpy()]
    out = {"lines": {k: ser(v) for k, v in lines.items()}}
    if panel:
        out["panel"] = {**panel, "values": ser(panel["values"])}
    return out


@app.post("/api/backtest")
def backtest(req: BacktestReq):
    df = load(req.dataset)
    strat = _guard(get, req.key, req.rules)
    res = _guard(run_backtest, df, strat, req.params, req.start, req.end, req.capital, req.costs.model())
    bh = buy_and_hold(df, req.start, req.end, req.capital, req.costs.model())
    gross = run_backtest(df, strat, req.params, req.start, req.end, req.capital,
                         CostModel(0, 0, 0), target=res.target)
    window = slice_period(df.loc[:pd.Timestamp(req.end)] if req.end else df, req.start, req.end)
    hist = df.loc[:window.index[-1]]
    ov = _overlays(strat.key, res.params, hist) if strat.params else {"lines": {}}
    n = len(window)
    ov["lines"] = {k: v[-n:] for k, v in ov["lines"].items()}
    if "panel" in ov:
        ov["panel"]["values"] = ov["panel"]["values"][-n:]
    return ok({
        "strategy": {"key": strat.key, "name": strat.name, "params": res.params},
        "result": res.to_dict(), "benchmark": bh.to_dict(),
        "gross": {"equity": gross.to_dict()["equity"], "metrics": gross.metrics},
        "price": {"open": window["Open"].round(4).tolist(), "high": window["High"].round(4).tolist(),
                  "low": window["Low"].round(4).tolist(), "close": window["Close"].round(4).tolist(),
                  "volume": window["Volume"].tolist()},
        "overlays": ov,
    })


@app.post("/api/compare")
def compare_ep(req: CompareReq):
    df = load(req.dataset)
    out = _guard(compare, df, [_spec(s) for s in req.strategies], req.start, req.end,
                 req.capital, req.costs.model())
    return ok(out)


@app.post("/api/validate")
def validate_ep(req: ValidateReq):
    df = slice_period(load(req.dataset), req.start, req.end)
    strat = _guard(get, req.key)
    if not strat.params:
        raise HTTPException(400, "Strategy has no parameters to optimise")
    return ok(_guard(train_test, df, strat, req.split, req.train_ratio, req.objective,
                     req.costs.model(), req.capital))


@app.post("/api/optimize")
def optimize_ep(req: ValidateReq):
    df = slice_period(load(req.dataset), req.start, req.end)
    strat = _guard(get, req.key)
    res = _guard(optimize, df, strat, None, None, req.objective, req.costs.model(), req.capital)
    return ok({"best": res["best"], "results": res["results"][:50]})


@app.post("/api/walkforward")
def walkforward_ep(req: WalkForwardReq):
    df = slice_period(load(req.dataset), req.start, req.end)
    strat = _guard(get, req.key)
    if not strat.params:
        raise HTTPException(400, "Strategy has no parameters to optimise")
    out = _guard(walk_forward, df, strat, req.train_days, req.test_days, req.anchored,
                 req.objective, req.costs.model(), req.capital)
    bh = buy_and_hold(df, out["start"], None, req.capital, req.costs.model())
    out["benchmark"] = {"dates": bh.to_dict()["dates"], "equity": bh.to_dict()["equity"],
                        "metrics": bh.metrics}
    return ok(out)


@app.post("/api/regimes")
def regimes_ep(req: RegimeReq):
    df = load(req.dataset)
    window = slice_period(df, req.start, req.end)
    labels = classify_rule_based(df)["regime" if req.detail else "trend"].reindex(window.index)
    rets = {}
    for s in req.strategies:
        strat = _guard(get, s.key, s.rules)
        r = run_backtest(df, strat, s.params, req.start, req.end, req.capital, req.costs.model())
        rets[s.label or strat.name] = r.returns
    rets["Buy & Hold"] = buy_and_hold(df, req.start, req.end, req.capital, req.costs.model()).returns
    counts = labels[labels != "Unknown"].value_counts()
    return ok({
        "dates": [d.strftime("%Y-%m-%d") for d in window.index],
        "close": window["Close"].round(4).tolist(),
        "labels": labels.tolist(),
        "distribution": {k: int(v) for k, v in counts.items()},
        "performance": regime_performance(rets, labels),
        "strategies": list(rets),
    })


@app.post("/api/ml")
def ml_ep(req: MLReq):
    df = slice_period(load(req.dataset), req.start, req.end)
    rep = _guard(ml_report, df, req.model, req.threshold, req.train_window, req.retrain_every)
    strat = get("ml")
    params = {"model": req.model, "threshold": req.threshold, "train_window": req.train_window,
              "retrain_every": req.retrain_every}
    res = run_backtest(df, strat, params, None, None, req.capital, req.costs.model())
    bh = buy_and_hold(df, None, None, req.capital, req.costs.model())
    rep["backtest"] = res.to_dict()
    rep["benchmark"] = {"equity": bh.to_dict()["equity"], "metrics": bh.metrics}
    return ok(rep)


@app.post("/api/costs")
def costs_ep(req: CompareReq):
    df = load(req.dataset)
    return ok(_guard(cost_sensitivity, df, [_spec(s) for s in req.strategies], req.start,
                     req.end, req.capital))


@app.post("/api/report")
def report_ep(req: ReportReq):
    df = load(req.dataset)
    rep = _guard(build_report, df, [_spec(s) for s in req.strategies], req.dataset, req.start,
                 req.end, req.capital, req.costs.model(), req.validation)
    rep["markdown"] = report_markdown(clean(rep))
    return ok(rep)


@app.post("/api/report.md", response_class=PlainTextResponse)
def report_md(req: ReportReq):
    df = load(req.dataset)
    rep = _guard(build_report, df, [_spec(s) for s in req.strategies], req.dataset, req.start,
                 req.end, req.capital, req.costs.model(), req.validation)
    return PlainTextResponse(report_markdown(clean(rep)), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{req.dataset}_report.md"'})


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
