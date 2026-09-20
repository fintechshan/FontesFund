# FontesFund USD v7 回测口径（已锁定）

**生产宇宙（live，唯一）：** `QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO`

**研究宇宙（backtest 默认）：** `QQQ, SOXX, SPY, IEF, GLD, DBMF, XLY`
（XLY 代理 AIPO 袖套，便于 2005 起长样本）

v5.1（8 只：含 SPYI / TLT / URA，headline 14.52% / 14.78% / 0.97）已废弃，
不得再当生产数字引用。

## 口径规则（必须同时满足）

1. **宏观滞后**：CPI 序列 +1 个月；GDP 序列 +4 个月（与 `run_backtest.py` 一致）。禁止用 FRED 期初标签当日交易。
2. **价格无前视**：权重只用 t-1 及更早信息。
3. **上市日起算（inception-aware）**：某 ETF 尚无收盘价时，其目标权重记为 **现金**，**禁止**静默重归一化到其余股票。旧 `filter_weights` renorm 仅作 A/B（`FONTES_WEIGHT_MODE=renorm`）。
4. **分层披露**：
   - 长样本（~2005→今，live）：实质是「6 只 + DBMF(2019+) + AIPO 现金占位」
   - 长样本（backtest）：AIPO 槽位换成 XLY，全程可交易（DBMF 2019 前仍为现金）
   - AIPO 全样本（自 2025-07-25）：7 只齐，但窗口极短，不得外推
5. **成本**：单边约 5 bps；波动目标 ~13%；熊市权益系数 0.70；回撤熔断 7%。

## 正式披露数字（公开 FRED，简化引擎）

窗口 2005-01-04 → 2026-09-18。宏观：公开 FRED CSV，CPI +1mo / GDP +4mo。
**不是** `src/backtester/engine.py` 逐行复刻。

| 口径 | CAGR | MaxDD | Sharpe | 区间 |
|---|--:|--:|--:|---|
| **backtest / XLY cash（对外长样本）** | **10.18%** | **-15.44%** | **0.86** | 2005-01-04 → 2026-09-18 |
| **live / AIPO cash** | **10.88%** | **-14.78%** | **0.98** | 同上（AIPO 2025-07-25 前为现金） |
| SPY | 10.90% | -55.19% | 0.48 | |
| 60/40 (SPY/IEF) | 8.30% | -31.39% | 0.59 | |

详见 [`V7_FRED_DUAL_RESULTS.md`](V7_FRED_DUAL_RESULTS.md) 与
[`../out/v7_fred_dual_metrics.json`](../out/v7_fred_dual_metrics.json)。

### 更早的代理宏观快照（已被上表取代，勿对外引用）

无 FRED、用 SPY/GLD-IEF 代理宏观时的简化复算（保留作审计痕迹）：

| 口径 | CAGR | MaxDD | Sharpe |
|---|--:|--:|--:|
| v7 cash（AIPO，代理宏观） | 10.31% | -14.82% | 0.95 |
| v7 renorm（旧口径对照） | 10.45% | -15.17% | 0.89 |
| v7 cash · AIPO 上市后（291 日） | 25.51% | -7.36% | 1.76 |

**为何低于旧文案 14.52%：** 宇宙已换（IEF 替 TLT、去掉 SPYI、URA→AIPO/XLY）；
缺史进现金；本次为简化引擎 + 滞后公开 FRED，不是 v5.1 全引擎复现。

## 代码对齐清单

- [x] `config/regime_rules.py` 已是 v7 权重
- [x] 双模式 API：`LIVE_UNIVERSE` / `BACKTEST_UNIVERSE` / `get_universe()` / `get_regime_weights_for_mode()`
- [x] `run_backtest.py` 读 `FONTES_RUN_MODE`（默认 backtest）+ V7 + 防御 auxiliary
- [x] `filter_weights` 默认 cash 模式（`FONTES_WEIGHT_MODE=cash`）
- [x] `CLAUDE.md` 生产段落改为 v7 dual sleeve
- [ ] 用完整 `BacktestEngine` + FRED key 重跑，若要替换本简化数字须单独文档化 delta
- [ ] Dashboard / Cloud Run 调用点若需发布 live 曲线，设置 `FONTES_RUN_MODE=live`
