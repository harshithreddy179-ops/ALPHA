import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from alphatrial import data, strategies as S
from alphatrial.api import app
from alphatrial.backtester import CostModel, buy_and_hold, run_backtest, simulate
from alphatrial.metrics import max_drawdown, sharpe
from alphatrial.ml import walk_forward_predict
from alphatrial.validation import pbo, train_test, walk_forward


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
    strat = S.get("ema_cross")
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


def test_pbo_detects_pure_noise():
    rng = np.random.default_rng(0)
    noise = pd.DataFrame(rng.normal(0, 0.01, (1000, 30)))
    assert 25 <= pbo(noise)["pbo"] <= 75   # no real skill → about a coin flip


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
