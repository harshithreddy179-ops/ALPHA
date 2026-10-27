# AlphaTrial: Build, Backtest & Validate Trading Strategies

**QuantActive Code Conflux · PS-01 AlphaTrial**

AlphaTrial is a quantitative research platform for designing rule-based trading
strategies, backtesting them realistically on historical data, and proving whether
their edge survives on data they've never seen.

```
pip install -r requirements.txt
python -m uvicorn alphatrial.api:app --port 8000
# open http://localhost:8000
```

No internet needed: four sample datasets ship in `data/`, and Plotly is vendored.
Run `python scripts/fetch_data.py AAPL RELIANCE.NS ^NSEI` on a connected machine to pull real data,
or upload any CSV from the dashboard.

## How it works

```
CSV ──► data.py (clean/validate) ──► strategies.py (target position at close t)
                                           │
                                           ▼
            backtester.py: fill at OPEN t+1 · whole shares · cash-limited · commission + slippage
                                           │
                    ┌──────────────┬───────┴───────┬───────────────┬──────────────┐
                    ▼              ▼               ▼               ▼              ▼
               metrics.py     validation.py    regimes.py       ml.py        analysis.py
           Sharpe, MDD, win  train/test, WFA,  trend×vol, GMM  walk-forward  compare, cost sweep,
            rate, Sortino…    PBO, heatmap     per-regime P&L   classifier    strengths/weaknesses
                                           │
                               api.py (FastAPI) ──► frontend/ (Plotly dashboard)
```

## Feature checklist vs the problem statement

| Requirement | Where |
|---|---|
| Import historical prices & volumes from CSV | Sidebar upload, `data.py` (column aliasing, dedupe, sort, gap-fill, validation) |
| MA crossover, RSI, momentum strategies | SMA/EMA crossover, RSI reversion, time-series momentum, Bollinger, trend-filtered RSI |
| Entry/exit signals from predefined rules | Every strategy, plus a **visual rule builder** (combine SMA/EMA/RSI/momentum/vol/BB/volume with `>`, `<`, `crosses_above`…) |
| Simulate trades with transaction costs & cash constraints | `backtester.py`: commission bps, slippage bps, fixed fee, integer shares, no leverage |
| Cumulative return, Sharpe, max drawdown, win rate | Plus CAGR, Sortino, Calmar, profit factor, exposure, turnover, DD duration |
| Compare vs buy-and-hold with charts | Every view overlays B&H (paying the same costs); Compare tab leaderboard |
| **Adv:** walk-forward / rolling-window evaluation | Walk-Forward tab: rolling or anchored, stitched OOS equity, WF efficiency |
| **Adv:** optimise a limited parameter set on training data | Grid search on the training window only, with a choice of objective |
| **Adv:** in-sample vs out-of-sample | Validation Lab: IS→OOS Sharpe decay, verdict, IS-vs-OOS scatter of every combo, rank correlation |
| **Adv:** performance across market conditions | Regimes tab: Bull/Bear/Sideways × High/Low vol, or an unsupervised GMM; per-regime return & Sharpe; yearly heatmap |
| **Adv:** simple ML model for direction / regimes | ML Lab: logistic / random forest / gradient boosting, retrained walk-forward; accuracy vs naive baseline, AUC, calibration, feature importance. GMM regime classifier |
| ★ How costs change profitability | Cost Impact tab: 0–100 bps sweep, break-even cost, "beats B&H until" cost, gross vs net equity |
| ★ Strategies good in training, bad on unseen data | Overfit / Degraded verdicts, **Probability of Backtest Overfitting (CSCV)**, parameter-stability heatmap |
| ★ Risk-adjusted over total profit | Leaderboards ranked by Sharpe; risk/return bubble chart |
| ★ Prevent look-ahead bias | Close-t signal → open-t+1 fill; trailing-only indicators; walk-forward ML; regime labels lagged. **Unit-tested** by perturbing future prices |
| ★ Comparison report with strengths & weaknesses | Report tab: auto-generated narrative, downloadable as Markdown or printable to PDF |

## Look-ahead bias controls
1. Strategies output a target position using data **up to the close of day t**.
2. The engine executes it at the **open of day t+1** (with slippage).
3. When backtesting a sub-period, signals are computed only on history up to that period's end.
4. The ML model at day t is trained only on rows whose label (next-day direction) was already known.
5. Regime volatility thresholds use an *expanding* median, and returns are attributed to the regime known at the prior close.
6. `tests/test_engine.py::test_signals_do_not_use_future_data` triples all prices after a cut-off and asserts that earlier signals don't change.

## API
`GET /api/datasets` · `POST /api/upload` · `GET /api/strategies` · `POST /api/backtest` ·
`POST /api/compare` · `POST /api/validate` · `POST /api/optimize` · `POST /api/walkforward` ·
`POST /api/regimes` · `POST /api/ml` · `POST /api/costs` · `POST /api/report` · `POST /api/report.md`.
Interactive docs are at `/docs`.

## Tests
```
python -m pytest -q
```

## Sample data
`ALPHA_TECH`, `BETA_BANK`, `GAMMA_ENERGY` and `DELTA_INDEX` are synthetic, generated by
`python -m alphatrial.data` with regime switching (bull/bear/sideways/crash), GARCH-style volatility
clustering and fat tails, so every feature can be demoed offline. Swap in real data with the
fetch script or the CSV upload.

## Limitations
Long-only, single asset. Fills at next open plus fixed slippage, with no market impact,
dividends, borrowing costs or taxes. Historical results do not guarantee future performance.
