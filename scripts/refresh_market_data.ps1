# =============================================================================
# refresh_market_data.ps1 — Daily market-data + backtest refresh -> GCS.
# Task "ETF-Data-Refresh" (daily 08:40, before the 09:00 IBKR snapshot).
#
# Runs run_backtest.py with FORCE_REFRESH=1 (fresh yfinance + FRED downloads —
# reliable from this PC's residential IP, unlike Cloud Run's datacenter IPs,
# which produced corrupted regimes on 2026-07-12) and pushes the caches/results
# to GCS. The 11:00 UTC cloud refresh stays as a gated backup.
# On ANY failure: nothing is pushed; GCS keeps the last good data.
# =============================================================================
$ErrorActionPreference = 'Continue'
$repo   = 'D:\Software\Antigraivty File\Investment'
$py     = 'C:\Users\lisha\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$gcloud = 'C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
$bucket = 'montesfund-etf-dashboard-data'
$log    = Join-Path $repo 'data\cache\data_refresh_task.log'

Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
$env:FORCE_REFRESH = '1'
"$(Get-Date -Format s)  --- market data refresh start ---" | Out-File -Append $log

& $py 'run_backtest.py' *>> $log
if ($LASTEXITCODE -ne 0) {
    "$(Get-Date -Format s)  refresh FAILED (rc=$LASTEXITCODE); GCS NOT updated." | Out-File -Append $log
    exit 1
}

foreach ($f in @('data\cache\price_data.csv', 'data\cache\macro_data.pkl',
                 'data\backtest_results\20yr_comparison.csv', 'data\backtest_results\all_equity_curves.csv')) {
    $rel = $f -replace '\\', '/'
    & $gcloud storage cp $f "gs://$bucket/$rel" *>> $log
}
"$(Get-Date -Format s)  refresh + GCS push OK." | Out-File -Append $log
