# QQQ Vegas 影子 / 实验 — 2 日确认

这不是官方 v9 卡，不替代 `data/qqq_vegas/` 里的 `daily_signal.csv`、`equity_curve.csv`、`rebalances.csv` 或 `signal_current.json`，也不发实盘 ENTER/EXIT 提醒。

## 确认规则

锁定 v9 的布尔信号不变：Vegas 隧道（Mom189>0 且 Close>SMA150 且 Close≥min(EMA144, EMA169)）并且 `rv20 ≤` 1999 以来扩窗 Q80。本目录不重算这条布尔，只读官方 `signal` 列。

- 从空仓开始。
- **进场和出场**都要连续两个收盘的布尔值等于新状态，确认状态才翻转。中间夹一个反向收盘，连续计数清零，状态不动。
- 持仓是确认状态的前一交易日（`confirmed.shift(1)`）：收盘确认，次日生效。首日持仓为现金。
- 仓位仍是 70% QQQ + 30% QLD，空仓 100% BIL。换仓仍扣 4 bps。
- 没有 ±1.5% 价格带，也没有 `rv20 > 1.15×Q80` 的当日离场例外。

官方 v9 仍是一收盘即确认。这里的历史对照是纸面记录，用来往后攒 6–12 个月样本外，不是改卡理由。

刷新：`python scripts/refresh_qqq_vegas_shadow.py`。官方信号刷新成功后也会顺带重写本目录，失败不影响官方文件。
