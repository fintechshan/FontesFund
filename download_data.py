"""Download ETF data one ticker at a time to avoid yfinance batch failures."""
import yfinance as yf
import pandas as pd
import time

tickers = [
    'SPY', 'QQQ', 'IWM', 'VEA', 'VWO',
    'TLT', 'IEF', 'SHY', 'AGG', 'TIP',
    'GLD', 'DBC', 'VNQ', 'SOXX',
    'SPYI', 'QQQI', 'TQQQ', 'SOXL', 'DBMF', 'BTAL'
]

all_data = {}
for t in tickers:
    for attempt in range(5):
        try:
            print(f"  Downloading {t} (attempt {attempt+1})...", end=" ")
            d = yf.download(t, start='2005-01-01', auto_adjust=True, progress=False)
            if not d.empty:
                if isinstance(d.columns, pd.MultiIndex):
                    d = d['Close']
                if isinstance(d, pd.DataFrame):
                    all_data[t] = d.iloc[:, 0]
                else:
                    all_data[t] = d
                print(f"OK ({len(all_data[t])} rows)")
                break
            else:
                print("EMPTY")
                time.sleep(3)
        except Exception as e:
            print(f"ERROR: {e}")
            time.sleep(3)
    else:
        print(f"  FAILED {t} after 5 attempts")
    time.sleep(0.5)  # Rate limit

result = pd.DataFrame(all_data)
result.index.name = 'Date'
print(f"\nTotal: {len(result.columns)} ETFs: {sorted(result.columns.tolist())}")
result.to_csv('data/cache/price_data.csv')
print("Saved to data/cache/price_data.csv")
