# Moomoo / Futu US paper rebalance

Local SIMULATE orders for the FontesFund US sleeve. This is the Moomoo counterpart of `scripts/ibkr_rebalance.py`. It reads the same last-day overlay (`src/execution/overlay_targets.py`: targeted clock, then the daily 200-day blend, HAR vol scale, and portfolio drawdown shrink). It does not use notify's static `book_weights`.

简要：在已登录的 OpenD 上，对美股**模拟盘**按当前 overlay 打印或下单。默认只打印。`--execute` 只接受 `trd_env=SIMULATE`，遇到 REAL 直接退出。不要在 Cloud Run 或 GitHub Actions 里跑。

## What you need

1. OpenD from Moomoo or Futu, running and logged in on this machine. The API default is `127.0.0.1:11111`.
2. A US **paper** account. The script calls `get_acc_list` and keeps a row with `trd_env=SIMULATE`. It prefers `sim_acc_type=STOCK_AND_OPTION`, then `STOCK`. Futures paper accounts are left alone.
3. One SDK, installed only on that machine:

   ```bash
   pip install moomoo-api
   ```

   If that import name is absent, the script tries `futu` (`pip install futu-api`).

Unlock the paper session in the OpenD window if it asks. This script has no password flag. Do not commit OpenD credentials.

## Commands

From the repo root, with the price and macro caches present (`data/cache/price_data.csv` and `data/cache/macro_data.pkl`):

```bash
python scripts/moomoo_rebalance.py
python scripts/moomoo_rebalance.py --host 127.0.0.1 --port 11111 --execute
```

| Command | What it does |
|---|---|
| (no flag) | Computes overlay weights from the local cache, reads paper NAV and positions, prints the order table. Places nothing. |
| `--execute` | Same plan, then `place_order(..., trd_env=TrdEnv.SIMULATE)` for that account. |
| `--security-firm FUTUINC` | Optional. Empty uses the SDK default. Paper `get_acc_list` still has to show SIMULATE. |

`--help` does not connect to OpenD.

If OpenD is down, the script still prints the overlay weights from cache, then exits. A closed port is detected before the SDK client starts; that client would otherwise retry the connection indefinitely. Nothing is placed.

## US sleeve

| Ticker | Moomoo code |
|---|---|
| QQQ | `US.QQQ` |
| SOXX | `US.SOXX` |
| SPY | `US.SPY` |
| IEF | `US.IEF` |
| GLD | `US.GLD` |
| DBMF | `US.DBMF` |
| AIPO | `US.AIPO` |

**AIPO:** confirm `US.AIPO` is tradeable on your Moomoo paper account before `--execute`. If a snapshot or an order says the code is missing, the script skips that name and prints a warning. It does not swap in another ETF. The skipped weight stays uninvested. Positions outside `US.*` are left unchanged.

Orders are market when the SDK has `OrderType.MARKET` (US regular hours). If OpenD rejects the market type, the script sends one limit 0.5% through the last cache price. A rejected symbol is not retried as a different ticker.

## Safety

- Default is dry-run.
- `--execute` aborts unless the chosen account's `trd_env` is `SIMULATE`.
- `place_order` is only called with `TrdEnv.SIMULATE`. A SDK whose `TrdEnv.SIMULATE` is not that value raises before the call.
- There is no live-trading flag.
- GitHub Actions notify stays signal-only. It mentions this command in the Issue body and does not open OpenD.
- Cloud Run does not run this script. `moomoo-api` / `futu-api` are not production dependencies.

## Windows Task Scheduler

`scripts/monthly_rebalance.ps1` is the IBKR paper task. Do not point that file at OpenD.

For Moomoo, a separate optional task on the same PC is enough. Start with a dry-run so a closed OpenD only writes a log:

```text
python D:\path\to\FontesFund\scripts\moomoo_rebalance.py
```

After one manual `--execute` on the SIMULATE account looks right, the action can add `--execute`. The script still refuses a REAL login. Log next to the IBKR task log, for example `data\cache\moomoo_rebalance_task.log`. Market orders fill in the US regular session; a task while the US cash market is closed queues on OpenD the same way a manual run does.

Create the task in Task Scheduler (monthly, 1st, a time you are usually logged in so OpenD is up). A copy of `monthly_rebalance.ps1` with the python path, the repo path, and `scripts\moomoo_rebalance.py` is the local pattern. Keep that copy on the PC. It does not belong in this repo, because the IBKR script's copy hard-codes one machine.
