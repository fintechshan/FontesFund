# FontesFund v7 双配置：长回测 XLY / 实盘 AIPO

## 怎么用 / How to run

| 模式 Mode | 环境变量 Env | 袖套标的 Sleeve | 用途 Use |
|---|---|---|---|
| **backtest**（默认） | `FONTES_RUN_MODE=backtest` | **XLY** 替代 AIPO | 2005 起长样本研究 / long-history research |
| **live** | `FONTES_RUN_MODE=live` | **AIPO** | 老虎/IB 实盘与下单清单 / live book |

```bash
# 长回测（默认 / default research path）
python run_backtest.py

# 实盘权重检查（AIPO）
FONTES_RUN_MODE=live python run_backtest.py

# 公开 FRED 简化引擎（无需 API key）
python out/v7_fred_dual_recompute.py
```

缺史权重默认进现金：`FONTES_WEIGHT_MODE=cash`。旧静默重归一仅作 A/B：
`FONTES_WEIGHT_MODE=renorm`。

## 代码入口 / Code entry

- `config/regime_rules.py`
  - `LIVE_UNIVERSE` / `BACKTEST_UNIVERSE`
  - `BACKTEST_TICKER_PROXY = {"AIPO": "XLY"}`
  - `get_universe(mode)` / `get_regime_weights_for_mode(mode)`
  - `get_run_mode()` / `get_weight_mode()`
- `run_backtest.py` 读 `FONTES_RUN_MODE`，默认 `backtest`；
  `filter_weights(..., renormalize=False)` 默认 cash 口径

## 口径提醒 / Disclosure

- 两套数字**不要混着对外报**。长回测是「消费可选代理」；实盘是「AI/电力基建」。
  Do not mix the two series in external copy. Backtest = consumer-discretionary
  proxy; live = AI/power infrastructure.
- cash 口径仍适用：DBMF 2019 前、AIPO 2025-07 前（live 模式）缺史进现金。
- **Live long-sample ≠ full AIPO allocation historically.** AIPO listed
  2025-07-25; most of the 20-year live window that sleeve is cash.

## 正式数字（公开 FRED，2026-09-21）

| 模式 Mode | CAGR | MaxDD | Sharpe |
|---|--:|--:|--:|
| backtest / XLY | 10.18% | -15.44% | 0.86 |
| live / AIPO | 10.88% | -14.78% | 0.98 |

窗口 / window: 2005-01-04 → 2026-09-18。宏观滞后 CPI +1mo、GDP +4mo。
引擎为简化诚实复算，**不是** `src/backtester/engine.py` 逐行复刻。

详见 [`V7_FRED_DUAL_RESULTS.md`](V7_FRED_DUAL_RESULTS.md)。
