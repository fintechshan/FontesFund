import pandas as pd
import yfinance as yf

# Check what happened in 2015
data = yf.download(['SPY','SHY','AGG','GLD','TLT','IEF','TIP','DBC'], start='2015-01-01', end='2015-12-31', auto_adjust=True)['Close']
returns_2015 = data.pct_change().dropna()
monthly = returns_2015.resample('ME').apply(lambda x: (1+x).prod()-1)

print("Monthly returns 2015:")
print(monthly.to_string(float_format='{:.2%}'.format))
print()

# Check the actual portfolio equity curve around 2015
eq = pd.read_csv('data/backtest_results/aggressive_equity_curve.csv', index_col=0, parse_dates=True)
eq.columns = ['equity']
eq_2015 = eq.loc['2015']
monthly_eq = eq_2015.resample('ME').last()
monthly_eq_ret = monthly_eq.pct_change().dropna()
print("\nPortfolio monthly returns 2015:")
for d, v in monthly_eq_ret.iterrows():
    print(f"  {d.strftime('%Y-%m')}: {v.iloc[0]:.2%}")

# Check SPY drawdown from 120-day high in 2015
spy = yf.download('SPY', start='2014-08-01', end='2016-01-01', auto_adjust=True)['Close']
for month_end in ['2015-03-31','2015-06-30','2015-08-31','2015-11-09']:
    d = pd.Timestamp(month_end)
    nearest = spy.index[spy.index <= d][-1]
    high_120 = spy.loc[:nearest].tail(120).max()
    val = spy.loc[nearest]
    dd_pct = (val - high_120) / high_120
    print(f"  SPY at {nearest.date()}: {val:.2f}, 120d high: {high_120:.2f}, DD: {dd_pct:.2%}")
