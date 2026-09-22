# FontesFund v7 双配置正式数字（公开 FRED）

**更新：** 2026-09-21
**宏观：** FRED public CSV: CPIAUCSL +1mo, A191RL1Q225SBEA +4mo, VIXCLS, DFF
**引擎：** simplified honest (not bit-identical to src/backtester/engine.py)
**平均无风险利率（DFF）：** 1.87%

## 宇宙 / Universe

| 模式 Mode | 袖套 Sleeve | 完整列表 Book |
|---|---|---|
| **backtest（研究默认）** | XLY 代理 AIPO 槽 | QQQ SOXX SPY IEF GLD DBMF **XLY** |
| **live（实盘）** | AIPO | QQQ SOXX SPY IEF GLD DBMF **AIPO** |

上市 / inception：AIPO 2025-07-25 · XLY 2005-01-03 · DBMF 2019-05-08

## 结果（cash 口径，缺史不重归一）

| 组合 | CAGR | MaxDD | Sharpe | Vol | 区间 |
|---|--:|--:|--:|--:|---|
| **backtest / XLY** | **10.18%** | **-15.44%** | **0.86** | 9.68% | 2005-01-04→2026-09-18 |
| **live / AIPO** | **10.88%** | **-14.78%** | **0.98** | 9.22% | 2005-01-04→2026-09-18 |
| SPY | 10.90% | -55.19% | 0.48 | 18.89% | |
| 60/40 SPY/IEF | 8.30% | -31.39% | 0.59 | 10.88% | |

### 读法 / How to read

- **对外研究/长样本**：报 XLY 行（backtest）。
- **实盘预期叙事**：AIPO 长样本里该袖套大部分时间为现金，所以 live 行更像「6 只核心 + 近年才有的 AIPO」；**不要**把 live 长样本 CAGR 说成「二十年满仓 AIPO」。
  **Live long-sample ≠ full historical AIPO allocation.**
- 目标 16% / &lt;14.8% / 1.2：**两套都未全中**；live MaxDD -14.78% 贴线，backtest MaxDD -15.44% 略破。

v5.1 8-ETF 14.52% / 14.78% / 0.97 仅为历史对照。

## 复现 / Reproduce

```bash
# 公开 FRED CSV（无需 API key）。缺缓存时脚本会从 fred.stlouisfed.org 拉取。
python out/v7_fred_dual_recompute.py

FONTES_RUN_MODE=backtest python run_backtest.py   # 完整引擎路径（需依赖 + 可选 FRED key）
FONTES_RUN_MODE=live python run_backtest.py
```

冻结数字：[`../out/v7_fred_dual_metrics.json`](../out/v7_fred_dual_metrics.json)。
