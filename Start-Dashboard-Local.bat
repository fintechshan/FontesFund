@echo off
REM ============================================================================
REM  Start ETF Dashboard LOCALLY (trading buttons enabled).
REM  1) Pulls the latest caches + IBKR snapshot from GCS (best-effort)
REM  2) Starts the Dash app on http://localhost:8050
REM  With TWS/IB Gateway open (API on), the Execution tab's Connect / Preview /
REM  Execute buttons work here (they are hidden on the hosted Cloud Run site).
REM ============================================================================
cd /d "D:\Software\Antigraivty File\Investment"
set PYTHONIOENCODING=utf-8

echo Syncing latest data from GCS (best-effort)...
set GCB=gs://montesfund-etf-dashboard-data
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/cache/price_data.csv" data\cache\price_data.csv 2>nul
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/cache/macro_data.pkl" data\cache\macro_data.pkl 2>nul
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/backtest_results/20yr_comparison.csv" data\backtest_results\20yr_comparison.csv 2>nul
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/backtest_results/all_equity_curves.csv" data\backtest_results\all_equity_curves.csv 2>nul
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/cache/ibkr_account.json" data\cache\ibkr_account.json 2>nul
call "C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" storage cp "%GCB%/data/cache/ibkr_equity_history.csv" data\cache\ibkr_equity_history.csv 2>nul

echo Starting dashboard at http://localhost:8050  (Ctrl+C to stop)
start "" http://localhost:8050
"C:\Users\lisha\AppData\Local\Python\pythoncore-3.14-64\python.exe" run_dashboard.py
pause
