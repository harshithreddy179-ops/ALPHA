import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from alphatrial import data, strategies as S
from alphatrial.api import app
from alphatrial.backtester import CostModel, buy_and_hold, run_backtest, simulate
from alphatrial.metrics import max_drawdown, sharpe
from alphatrial.ml import walk_forward_predict
from alphatrial.validation import train_test, walk_forward


@pytest.fixture(scope="module")
def df():
    return data.load_dataset("ALPHA_TECH")


def _frame(closes, opens=None):
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    c = np.asarray(closes, float)
    o = c if opens is None else np.asarray(opens, float)
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c), "Low": np.minimum(o, c),
                         "Close": c, "Volume": 1e6}, index=idx)


# --- look-ahead bias ---------------------------------------------------------------

@pytest.mark.parametrize("key", list(S.STRATEGIES))
def test_signals_do_not_use_future_data(df, key):
    """Changing prices after day t must not change any signal up to day t."""
    strat = S.get(key)
    cut = 1500
    base = strat.signals(df)
    shocked = df.copy()
    shocked.iloc[cut:, :4] *= 3.0
    after = strat.signals(shocked)
    pd.testing.assert_series_equal(base.iloc[:cut], after.iloc[:cut])


def test_ml_predictions_do_not_use_future_data(df):
    p1, _, _ = walk_forward_predict(df.iloc[:1400])
    p2, _, _ = walk_forward_predict(df.iloc[:1800])
    common = p1.dropna().index
    np.testing.assert_allclose(p1[common], p2[common])


def test_execution_happens_next_open():
    df = _frame([10, 10, 10, 20, 20], opens=[10, 10, 15, 20, 20])
    target = pd.Series([0, 1, 1, 1, 1], index=df.index, dtype=float)
    res = simulate(df, target, capital=1500, costs=CostModel(0, 0, 0))
    t = res.trades.iloc[0]
    assert t["entry_date"] == df.index[2]          # decided at close of bar 1, filled at open of bar 2
    assert t["entry_price"] == 15
    assert t["shares"] == 100


# --- cash constraints & costs ---------------------------------------------------------

def test_cash_never_negative_and_whole_shares(df):
    res = run_backtest(df, S.get("momentum"), costs=CostModel(10, 10, 5))
    assert (res.equity > 0).all()
    assert all(float(s).is_integer() for s in res.trades["shares"])


def test_costs_reduce_returns(df):
    strat = S.get("sma_cross")
    free = run_backtest(df, strat, costs=CostModel(0, 0, 0)).metrics["total_return"]
    costly = run_backtest(df, strat, costs=CostModel(25, 25, 0)).metrics["total_return"]
    assert costly < free


def test_commission_math():
    df = _frame([100, 100, 100, 100], opens=[100, 100, 100, 100])
    target = pd.Series([1, 1, 0, 0], index=df.index, dtype=float)
    res = simulate(df, target, capital=10_000, costs=CostModel(commission_bps=100, slippage_bps=0))
    # buy 99 shares at 100 with 1% commission, sell at 100 with 1% commission
    assert res.trades.iloc[0]["shares"] == 99
    assert res.equity.iloc[-1] == pytest.approx(10_000 - 99 * 100 * 0.02)


# --- metrics ----------------------------------------------------------------------

def test_max_drawdown():
    mdd, _ = max_drawdown(pd.Series([100, 120, 60, 90, 130]))
    assert mdd == pytest.approx(-0.5)


def test_sharpe_constant_is_zero():
    assert sharpe(pd.Series([0.001] * 100)) == 0.0


def test_buy_and_hold_matches_price(df):
    bh = buy_and_hold(df, costs=CostModel(0, 0, 0))
    price_ret = df["Close"].iloc[-1] / df["Open"].iloc[0] - 1
    assert bh.metrics["total_return"] / 100 == pytest.approx(price_ret, rel=0.01)


# --- validation ------------------------------------------------------------------

def test_train_test_and_walk_forward(df):
    tt = train_test(df, S.get("sma_cross"))
    assert tt["verdict"] in {"Robust", "Degraded", "Overfit", "No Edge"}
    assert tt["test_period"][0] > tt["train_period"][1]
    wf = walk_forward(df, S.get("sma_cross"), 504, 252)
    assert wf["summary"]["n_windows"] >= 5
    for w in wf["windows"]:
        assert w["test"][0] > w["train"][1]


def test_custom_rules(df):
    rules = {"entry": [{"left": {"type": "sma", "n": 20}, "op": ">", "right": {"type": "sma", "n": 50}}]}
    a = run_backtest(df, S.get("custom", rules)).metrics
    b = run_backtest(df, S.get("sma_cross"), {"fast": 20, "slow": 50}).metrics
    assert a["total_return"] == pytest.approx(b["total_return"])


def test_csv_cleaning():
    raw = "date,close\n2020-01-03,11\n2020-01-02,10\n2020-01-02,10\n" + "".join(
        f"2020-{m:02d}-{d:02d},{10 + d}\n" for m in range(2, 6) for d in range(1, 28))
    df = data.load_csv(raw.encode())
    assert df.index.is_monotonic_increasing and not df.index.duplicated().any()
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


# --- API smoke ---------------------------------------------------------------------

def test_api_endpoints():
    c = TestClient(app)
    assert c.get("/api/datasets").status_code == 200
    body = {"dataset": "DELTA_INDEX", "strategies": [{"key": "sma_cross"}, {"key": "rsi"}]}
    assert c.post("/api/backtest", json={"dataset": "DELTA_INDEX", "key": "rsi"}).status_code == 200
    assert c.post("/api/compare", json=body).status_code == 200
    assert c.post("/api/costs", json=body).status_code == 200
    assert c.post("/api/backtest", json={"dataset": "nope", "key": "rsi"}).status_code == 404
    assert c.post("/api/backtest", json={"dataset": "DELTA_INDEX", "key": "nope"}).status_code == 400


# --- live market data ----------------------------------------------------------------

def _chart_payload(n=120):
    ts = [1_600_000_000 + i * 86400 for i in range(n)]
    close = [100 + i for i in range(n)]
    return {"chart": {"result": [{
        "meta": {"gmtoffset": 19800},
        "timestamp": ts,
        "indicators": {
            "quote": [{"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
                       "close": close, "volume": [1000] * n}],
            "adjclose": [{"adjclose": [c / 2 for c in close]}],
        }}], "error": None}}


def test_parse_chart_adjusts_prices():
    from alphatrial.market import parse_chart
    df = parse_chart(_chart_payload())
    assert len(df) == 120
    assert df["Close"].iloc[0] == pytest.approx(50)      # adjusted by adjclose / close
    assert df["Open"].iloc[0] == pytest.approx(50)


def test_parse_chart_error():
    from alphatrial.market import parse_chart
    with pytest.raises(data.DataError):
        parse_chart({"chart": {"result": None, "error": {"description": "No data found"}}})


def test_symbol_helpers():
    from alphatrial.market import normalise, to_symbol
    assert normalise("reliance") == "RELIANCE.NS"
    assert normalise("TCS", "BSE") == "TCS.BO"
    assert normalise("^NSEI") == "^NSEI"
    assert to_symbol("YF:M&M.NS") == "M&M.NS"
    with pytest.raises(data.DataError):
        to_symbol("YF:../../etc")


def test_live_dataset_through_api(monkeypatch):
    from alphatrial import market
    monkeypatch.setattr(market, "_get", lambda url, timeout=15: _chart_payload(400))
    market._MEM.clear()
    c = TestClient(app)
    r = c.post("/api/backtest", json={"dataset": "YF:TESTSYM.NS", "key": "sma_cross"})
    assert r.status_code == 200
    assert c.get("/api/universe").json()["nifty50"]
    snap = c.get("/api/market?group=indices").json()["rows"]
    assert all("close" in s for s in snap)


def test_download_falls_back_when_range_ignored(monkeypatch):
    """BSE feeds can ignore range=10y and return one bar; the period1/period2 retry fixes it."""
    from alphatrial import market
    calls = []

    def fake_get(url, timeout=15):
        calls.append(url)
        return _chart_payload(1 if "range=10y" in url else 400)

    monkeypatch.setattr(market, "_get", fake_get)
    df = market._download("RELIANCE.BO", "10y")
    assert len(df) == 400
    assert any("period1=" in u for u in calls)


def test_short_bse_history_is_filled_from_nse(monkeypatch):
    from alphatrial import market

    def fake_get(url, timeout=15):
        if ".BO" in url:
            p = _chart_payload(400)
            r = p["chart"]["result"][0]
            r["timestamp"] = r["timestamp"][-80:]
            for k in ("open", "high", "low", "close", "volume"):
                r["indicators"]["quote"][0][k] = r["indicators"]["quote"][0][k][-80:]
            r["indicators"]["adjclose"][0]["adjclose"] = r["indicators"]["adjclose"][0]["adjclose"][-80:]
            return p
        return _chart_payload(400)

    monkeypatch.setattr(market, "_get", fake_get)
    monkeypatch.setattr(market, "_CACHE_DIR", __import__("pathlib").Path("/nonexistent/x"))
    market._MEM.clear()
    df = market.fetch("YF:FOO.BO")
    assert len(df) == 400 and "NSE" in df.attrs["note"]
    assert df.index.is_unique and df.index.is_monotonic_increasing
