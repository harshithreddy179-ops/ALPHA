"""Download real daily OHLCV data from Yahoo Finance into data/ (needs internet).

    pip install yfinance
    python scripts/fetch_data.py AAPL MSFT RELIANCE.NS ^NSEI --start 2014-01-01
"""

import argparse
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    import yfinance as yf

    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--start", default="2014-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    for t in args.tickers:
        df = yf.download(t, start=args.start, end=args.end, auto_adjust=True, progress=False)
        if df.empty:
            print(f"{t}: no data")
            continue
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        name = t.replace("^", "").replace(".", "_")
        df[["Open", "High", "Low", "Close", "Volume"]].to_csv(DATA / f"{name}.csv", index_label="Date")
        print(f"{t}: {len(df)} rows -> data/{name}.csv")


if __name__ == "__main__":
    main()
