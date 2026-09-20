# =============================================================================
# refresh_ibkr_snapshot.ps1  —  Daily IBKR paper-account snapshot -> GCS -> live dashboard.
# Run by Windows Task Scheduler (task "ETF-IBKR-Snapshot").
#
# REQUIRES: TWS or IB Gateway running on this PC with the API enabled
#           (port 7497 = TWS paper; use --port 4002 for IB Gateway paper).
# If TWS/Gateway is not running, the snapshot fails cleanly and GCS is NOT
# overwritten (the dashboard keeps the last good snapshot).
# =============================================================================
$ErrorActionPreference = 'Continue'
$repo   = 'D:\Software\Antigraivty File\Investment'
$py     = 'C:\Users\lisha\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$gcloud = 'C:\Users\lisha\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
$bucket = 'montesfund-etf-dashboard-data'
$ports  = @(7497, 4002)   # try TWS paper first, then IB Gateway paper
$log    = Join-Path $repo 'data\cache\ibkr_snapshot_task.log'

Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'   # keep Unicode in script output/logs (avoids cp1252 crash)
"$(Get-Date -Format s)  --- snapshot run start ---" | Out-File -Append $log

# 1) Write the local snapshot (connects to TWS or IB Gateway; read-only, never trades).
$ok = $false
foreach ($port in $ports) {
    & $py 'scripts\ibkr_snapshot.py' --port $port *>> $log
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    "$(Get-Date -Format s)  port $port failed; trying next..." | Out-File -Append $log
}
if (-not $ok) {
    "$(Get-Date -Format s)  snapshot FAILED on all ports (TWS/Gateway not running / API off?); GCS NOT updated." | Out-File -Append $log
    exit 1
}

# 2) Push to GCS using the gcloud CLI (uses your gcloud login; no ADC needed).
& $gcloud storage cp 'data\cache\ibkr_account.json'       "gs://$bucket/data/cache/ibkr_account.json"       *>> $log
& $gcloud storage cp 'data\cache\ibkr_equity_history.csv' "gs://$bucket/data/cache/ibkr_equity_history.csv" *>> $log
"$(Get-Date -Format s)  snapshot + GCS push OK (dashboard updates on its next load)." | Out-File -Append $log
