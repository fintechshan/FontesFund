# 风险旗 · notify only

`A_vol`, `B_crowd`, and `C_put` are a research scorecard. They are shown on the QQQ Vegas tab and, when one turns **on**, the weekday notifier opens one GitHub Issue (and Server酱, if `SERVERCHAN_SENDKEY` is set).

**通知 / 不改仓.** These flags do not change Merrill `REGIME_WEIGHTS`, the CPI+1 / GDP+4 clock, QQQ Vegas v9 (Vegas and expanding Q80, 70/30, close to next open), or any live rebalance size. A backtest of using them to cut live exposure hurt returns. Do not wire them into `src/backtester/engine.py`, `src/backtester/daily_overlay.py`, or `scripts/ibkr_rebalance.py`.

## Rules

Each published flag is the condition from the **previous** trading session (`shift(1)`). Expanding windows use only data through that session.

| Flag | Rule |
|---|---|
| **A_vol** | SOXX 20-day realized vol (annualized, sample std × √252) **>** its expanding 80th percentile (`min_periods=252`), **or** VXN **>** its expanding 80th percentile (`min_periods=252`). |
| **B_crowd** | Price proxy, **not** Goldman Sachs hedge-fund flow. (SOXX 5-day ≤ −8% **or** 10-day ≤ −12%) **and** 10-day range/close **>** its expanding median (`min_periods=10`), **or** (down-streak ≥ 4 **and** 5-day ≤ −5%). Range is Yahoo high−low over the close when both print; otherwise the close range, labeled on the card. |
| **C_put** | VIX ≥ 25 **and** VIX higher than 5 sessions ago **and** SOXX < SMA50 **and** SOXX 10-day ≤ −8%. **Sell-put checklist hint only.** Not an order. |

If SOXX and VXN are both missing, **A_vol** degrades to **VIX ≥ 30** and the card says so. If only one of those two is missing, the other leg still runs and the card does **not** switch to the VIX≥30 rule. If SOXX is missing, **B_crowd** and **C_put** are skipped. If VIX is missing, **C_put** is skipped.

## Where it runs

| Path | Role |
|---|---|
| `src/risk_flags.py` | Flag math and the JSON scorecard. |
| `scripts/refresh_risk_flags.py` | Yahoo download. Failure keeps the previous `flags.json`. |
| `data/risk_flags/flags.json` | What the dashboard reads. ASCII path. |
| `data/risk_flags/prices.csv` | Price cache. Gitignored. |
| QQQ Vegas tab | Card: name, on/off/skip, rule, as-of. |
| `scripts/notify_regime.py` | Rising edge only. Sticky ON does not send every day. First sight of the block is a baseline. |
| `/tasks/refresh` | Refreshes the scorecard after the backtest step and uploads `flags.json`. A backtest failure still attempts this refresh. |

The notifier’s regime and VIX-band rules are unchanged. A flag edge on a quiet regime day is its own Issue, titled `[风险旗]`, labeled `rebalance` and `risk-flag`. The body says not to rebalance because of the flag.
