# FontesFund QQQ Vegas 升级说明 — Vegas ∧ RV20≤扩窗 Q80

**策略 ID：** `qqq_vegas_rv20_q80`  
**回测标签：** `v9_rv20_q80` / filter `v5_rv20_q80`  
**as_of：** 2026-10-16  
**样本：** 1999-01-04 → 2026-10-16（覆盖互联网泡沫；UI 若以前从 ~2010 起，现改为全样本）

## 相对定案的变化

原先 Fontes「QQQ Vegas」页 = **纯 Vegas 1.3x**（70% QQQ + 30% QLD / 空仓现金）。  
现升级为：**Vegas 隧道 AND 低波动门（RV20 ≤ 扩窗 80% 分位）**，仓位结构不变。

| | 纯 Vegas 1.3x（同引擎全样本） | **本策略 Vegas∧RV门** |
|---|--:|--:|
| CAGR | 12.98% | **14.9%** |
| MaxDD | -63.56% | **-27.81%** |
| Sharpe | 0.6793 | **0.8389** |
| Calmar | 0.2042 | **0.5359** |

## 信号规则（严格无前视）

1. **Vegas 隧道**（QQQ 收盘）：Mom189>0 **且** Close>SMA150 **且** Close≥min(EMA144,EMA169)
2. **RV 门**：`rv20 = std(日收益,20)×√252`；`q80 = expanding_quantile(rv20.shift(1), 0.80, min_periods=252)`；`rv_ok = (rv20 ≤ q80)`
3. **risk_on** = Vegas ∧ rv_ok（0/1）
4. **执行**：收盘确认 → `exposure.shift(1)` 吃次日收益；QQQ+2× 腿 L1 换手扣 **4 bps**
5. **仓位**：开仓 70% QQQ + 30% 2×（QLD；2006-06-21 前为合成 2×）；平仓 100% 现金（IRX→BIL 拼接）

## UI 建议

- Tab 名可仍叫「QQQ Vegas」，副标题/规则区写清 **+ RV20≤扩窗Q80**
- 刷新：净值曲线、回撤、**月度收益热力图**、年度柱状（可选）
- `signal_current.json` 新增字段：`vegas`, `rv20`, `rv20_q80`, `rv_ok`（旧字段 `state`/`weights`/`reason` 保留）

## 免责

历史回测，非投资建议；合成 2× / 修订宏观等口径见 `summary.json` notes。
