"""
scripts/generate_gsblbr.py
==========================
Goldman Sachs Bull/Bear Market Indicator (GSBLBR) & 5-Factor Generator.

Methodology & Institutional Audit Integrity:
--------------------------------------------
Strictly causal expanding-window percentile ranking (NO look-ahead bias).
For each monthly date t >= t_0 (min_periods = 60 months / 5 years):
    Percentile(X_t) = Rank(X_t in {X_1, ..., X_t}) / t * 100

Factors (5 macroeconomic components):
  1. Shiller_Valuation:      S&P 500 (^GSPC) / 10-year moving average (Shiller P/E proxy)
  2. Yield_Curve_Inversion:  -1 * 10Y-2Y Treasury spread (T10Y2Y from FRED)
  3. Core_Inflation:         Core CPI YoY % change (CPILFESL from FRED)
  4. Labor_Tightness:        -1 * Civilian Unemployment Rate (UNRATE from FRED)
  5. Economic_Activity:      ISM / Industrial Production YoY % change (INDPRO from FRED)

Composite Indicator:
  GSBLBR_t = Average(Factor_1_t, Factor_2_t, Factor_3_t, Factor_4_t, Factor_5_t)

Outputs:
  data/cache/gsblbr_history.csv

The composite is a bear-RISK percentile (high = late-cycle stress), not a
second allocation engine. ab_gs_throttle.py reads this file, lags it by
GS_THROTTLE_PARAMS["release_lag_months"], and uses it only as a throttle
on the Investment Clock. This generator's dates stay at observation
month-end so the dashboard gauge and the backtest lag stay separate.
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pandas as pd
import numpy as np
import yfinance as yf
from fredapi import Fred
from config.settings import FRED_API_KEY


def fetch_raw_components():
    """Fetch all 5 macroeconomic component series from FRED and Yahoo Finance."""
    print("Fetching raw macroeconomic components...")
    fred = Fred(api_key=FRED_API_KEY)

    # 1. S&P 500 for Shiller Valuation Proxy (Price / 10Y MA)
    print("  - Fetching S&P 500 (^GSPC) from Yahoo Finance...")
    sp = yf.download('^GSPC', start='1960-01-01', progress=False)['Close'].squeeze()
    val = (sp / sp.rolling(252 * 10).mean()).dropna()

    # 2. 10Y-2Y Yield Curve Spread (Inverted so higher = more inverted/bearish)
    print("  - Fetching T10Y2Y spread from FRED...")
    yc = fred.get_series('T10Y2Y').dropna()

    # 3. Core CPI (YoY % change)
    print("  - Fetching Core CPI (CPILFESL) from FRED...")
    core_cpi = fred.get_series('CPILFESL').dropna()
    cpi_yoy = ((core_cpi / core_cpi.shift(12) - 1) * 100).dropna()

    # 4. Unemployment Rate (Inverted so higher = tighter labor market)
    print("  - Fetching Unemployment Rate (UNRATE) from FRED...")
    unemp = fred.get_series('UNRATE').dropna()

    # 5. Industrial Production (YoY % change)
    print("  - Fetching Industrial Production (INDPRO) from FRED...")
    indpro = fred.get_series('INDPRO').dropna()
    act_yoy = ((indpro / indpro.shift(12) - 1) * 100).dropna()

    # Align to month-end frequency
    df_monthly = pd.DataFrame({
        'Shiller_Valuation': val.resample('ME').last(),
        'Yield_Curve_Inversion': -yc.resample('ME').last(),
        'Core_Inflation': cpi_yoy.resample('ME').last(),
        'Labor_Tightness': -unemp.resample('ME').last(),
        'Economic_Activity': act_yoy.resample('ME').last(),
    }).dropna()

    print(f"Monthly raw observations aligned: {len(df_monthly)} rows ({df_monthly.index[0].date()} to {df_monthly.index[-1].date()})")
    return df_monthly


def calculate_causal_percentiles(df_monthly: pd.DataFrame, min_periods: int = 60) -> pd.DataFrame:
    """
    Compute strictly causal expanding-window percentiles.
    Guarantees no look-ahead bias: an observation at month t is ranked
    ONLY against data available up to month t.
    """
    print(f"Calculating causal expanding-window percentiles (min_periods={min_periods})...")
    pct_df = pd.DataFrame(index=df_monthly.index)

    for col in df_monthly.columns:
        # Expanding percentile: rank of current point within historical window up to current point
        pct_df[col] = df_monthly[col].expanding(min_periods=min_periods).apply(
            lambda w: float(pd.Series(w).rank(pct=True).iloc[-1] * 100), raw=False
        )

    # GSBLBR composite: simple average of all 5 factor percentiles
    pct_df['GSBLBR'] = pct_df.mean(axis=1)
    return pct_df


def main():
    df_monthly = fetch_raw_components()
    pct_df = calculate_causal_percentiles(df_monthly, min_periods=60)

    out_path = ROOT / 'data' / 'cache' / 'gsblbr_history.csv'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pct_df.to_csv(out_path)
    print(f"\nSuccessfully generated causal GSBLBR history: {out_path}")
    print(f"Total rows: {len(pct_df)}, Valid expanding rows: {pct_df['GSBLBR'].dropna().shape[0]}")

    latest_row = pct_df.dropna().iloc[-1]
    latest_date = pct_df.dropna().index[-1].strftime('%Y-%m-%d')
    print(f"\nLatest Causal GSBLBR Reading ({latest_date}):")
    print(f"  Composite GSBLBR:               {latest_row['GSBLBR']:.2f}%")
    print(f"  - Shiller Valuation:            {latest_row['Shiller_Valuation']:.2f}%")
    print(f"  - Yield Curve Inversion:        {latest_row['Yield_Curve_Inversion']:.2f}%")
    print(f"  - Core Inflation (YoY):         {latest_row['Core_Inflation']:.2f}%")
    print(f"  - Labor Tightness (-UNRATE):    {latest_row['Labor_Tightness']:.2f}%")
    print(f"  - Economic Activity (INDPRO YoY): {latest_row['Economic_Activity']:.2f}%")


if __name__ == '__main__':
    main()
