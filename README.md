# AlphaTrial

**QuantActive Code Conflux · PS-01: Build, Backtest & Validate a Trading Strategy**

Live demo: https://alphatrial.vercel.app

AlphaTrial is a web app for testing rule-based trading strategies on Indian stocks.
You pick a stock (NIFTY 50, NSE or BSE), pick a strategy, and it shows how the strategy
would have performed after costs, compared with simply buying and holding. It then checks
whether the result still holds on data the strategy was not tuned on.

## Features

**Data**
- 10 years of daily prices for NIFTY 50 stocks and indices (NIFTY 50, SENSEX, BANK NIFTY, ...)
  from Yahoo Finance, or any NSE/BSE symbol you type in
- CSV upload (`Date, Open, High, Low, Close, Volume`)
- Market tab with the latest NIFTY 50 snapshot

**Strategies**
- SMA crossover, RSI mean reversion, momentum
- A simple rule builder to make your own (e.g. "RSI(14) < 30 and Close > SMA(200)")
- An ML strategy (logistic regression or random forest) that predicts next-day direction

**Backtesting**
- Signals are calculated at the close and executed at the next day's open, so the strategy
  never uses future prices
- Whole shares only, no borrowing, commission and slippage on every trade
- Total return, CAGR, Sharpe, Sortino, max drawdown, win rate, number of trades
- Every result is compared with buy-and-hold over the same period and costs

**Validation**
- Train/test split: parameters are tuned on the first part of the data and tested on the rest.
  The app labels the result Robust, Degraded or Overfit
- Walk-forward test: re-tune on a rolling window, test on the next window, repeat
- Performance in bull, bear and sideways markets
- Transaction cost sweep (0–100 bps) showing where each strategy stops being profitable
- A comparison report with strengths and weaknesses, downloadable as Markdown or PDF

## Run locally

```
pip install -r requirements.txt
python -m uvicorn alphatrial.api:app --port 8000
```

Open http://localhost:8000. If Yahoo Finance is unreachable (for example behind a college
proxy), the app falls back to the sample CSVs in `data/`, which are synthetic.

## Project structure

```
alphatrial/
  data.py         CSV loading and cleaning, sample data
  market.py       NSE/BSE data from Yahoo Finance (cached)
  indicators.py   SMA, EMA, RSI, momentum, volatility
  strategies.py   strategy rules and the custom rule builder
  backtester.py   trade simulation with costs and cash limits
  metrics.py      returns, Sharpe, drawdown, win rate, ...
  validation.py   parameter search, train/test, walk-forward
  regimes.py      bull/bear/sideways labelling
  ml.py           ML direction model
  analysis.py     strategy comparison, cost sweep, report
  api.py          FastAPI backend
frontend/         dashboard (HTML, CSS, JavaScript, Plotly)
tests/            unit tests
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests cover the metrics, the cost and cash rules, and a look-ahead check: prices after
a date are changed, and the test confirms no earlier signal changes.

## Deployment

The app is deployed on Vercel. `index.py` is the entry point and `vercel.json` sets the
function timeout.

## Limitations

- Long-only, one stock at a time
- Fills use the next open plus a fixed slippage; real market impact can be larger
- Dividends are included through adjusted prices, but taxes are not modelled
- Past results do not guarantee future returns
