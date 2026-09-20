# =============================================================================
# monthly_rebalance.ps1 — Automatic monthly PAPER rebalance to current regime weights.
# Run by Windows Task Scheduler (task "ETF-IBKR-Rebalance", 1st of month).
#
# REQUIRES: TWS or IB Gateway running with API enabled (7497 TWS / 4002 Gateway).
# SAFETY:  scripts/ibkr_rebalance.py hard-refuses --execute on any non-paper
#          account (id must start with "DU"), so this can never trade real money.
# NOTE:    runs at 09:15 China time = US market closed; market orders are queued
#          as PreSubmitted and fill at the next US open (same as the manual run).
# =============================================================================
$ErrorActionPreference = 'Continue'
$repo  = 'D:\Software\Antigraivty File\Investment'
$py    = 'C:\Users\lisha\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$ports = @(7497, 4002)
$log   = Join-Path $repo 'data\cache\ibkr_rebalance_task.log'

Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
"$(Get-Date -Format s)  --- monthly rebalance run start ---" | Out-File -Append $log

$ok = $false
foreach ($port in $ports) {
    & $py 'scripts\ibkr_rebalance.py' --port $port --execute *>> $log
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    "$(Get-Date -Format s)  port $port failed; trying next..." | Out-File -Append $log
}
if (-not $ok) {
    "$(Get-Date -Format s)  rebalance FAILED on all ports (TWS/Gateway not running?). No orders placed." | Out-File -Append $log
    exit 1
}
"$(Get-Date -Format s)  rebalance orders submitted (fills at next US open; tomorrow's 9AM snapshot will reflect them)." | Out-File -Append $log
