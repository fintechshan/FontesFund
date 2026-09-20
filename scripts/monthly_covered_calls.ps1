# =============================================================================
# monthly_covered_calls.ps1 — Roll the covered-call overlay (PAPER account).
# Task "ETF-IBKR-CoveredCalls": 2nd of month 09:15 — the day AFTER the rebalance,
# so contract counts are sized against post-rebalance share counts.
#
# Buys back last month's short calls and writes new ~30-45 DTE calls on the
# income/defensive sleeves only (SPY/GLD/TLT — never QQQ/SOXX/URA/SPYI/DBMF).
# scripts/ibkr_covered_calls.py hard-refuses non-paper ("DU") accounts.
# =============================================================================
$ErrorActionPreference = 'Continue'
$repo  = 'D:\Software\Antigraivty File\Investment'
$py    = 'C:\Users\lisha\AppData\Local\Python\pythoncore-3.14-64\python.exe'
$ports = @(7497, 4002)
$log   = Join-Path $repo 'data\cache\ibkr_covered_calls_task.log'

Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
"$(Get-Date -Format s)  --- covered-call roll start ---" | Out-File -Append $log

$ok = $false
foreach ($port in $ports) {
    & $py 'scripts\ibkr_covered_calls.py' --port $port --execute *>> $log
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    "$(Get-Date -Format s)  port $port failed; trying next..." | Out-File -Append $log
}
if (-not $ok) {
    "$(Get-Date -Format s)  covered-call roll FAILED on all ports (TWS/Gateway down?). No orders placed." | Out-File -Append $log
    exit 1
}
"$(Get-Date -Format s)  covered-call roll submitted (fills at next US open)." | Out-File -Append $log
