# 象限 / VIX 跨档提醒

Weekday notifier. It opens a GitHub Issue (label `rebalance`) only when the Merrill regime changes or the latest VIX print crosses a band. GitHub notification settings deliver the email. An unchanged regime and the same VIX band end the run with no Issue. There is no SMTP send.

If a run should have opened that Issue and it did not, the job fails and an audit Issue (title prefix `[审计]`, label `notify-audit`) is opened so the miss is not silent. See [Audit](#audit).

This path is separate from Cloud Run and from `run_backtest.py`. It does not change `REGIME_WEIGHTS`, `CDN_REGIME_WEIGHTS`, or the CPI+1 / GDP+4 lag.

## When an Issue is opened

| Event | Issue |
|---|---|
| Regime changes (`goldilocks` / `reflation` / `stagflation` / `deflation`) | Yes. Title `[调仓]`. Headline is old → new, **需要调仓：是/否** (any sleeve moves by ≥ 1%), US and CDN weight deltas, equity-vs-defensive one-liners, and a 减持/增持 list. |
| Latest VIX crosses 20, 28, 30, or 40, regime unchanged | Yes. Title `[风险档位]`. Says whether the overlay should tighten or ease, and **月中再平衡：不建议**. No weight table. |
| First successful run | No. Writes `data/notify_state.json` only. |
| `workflow_dispatch` with **force** | Yes, even when nothing changed. Title `[测试]`. |

Bands: `0-20` 正常, `20-28` 偏高, `28-30` 开始降敞口, `30-40` 大幅降敞口, `40+` 接近清仓股票.

The regime is `classify_regimes(..., mode="targeted")` from `src/backtester/regime_clock.py`, the same call the dashboard and `scripts/ibkr_rebalance.py` use. That clock lags CPI by 1 month and GDP by 4 months, then lags the VIX monthly mean and 12-month momentum by one month. A latest VIX print above 30 forces the live label to `deflation`. The email's VIX band is the latest `VIXCLS` print, separate from that monthly mean.

US weights come from `REGIME_WEIGHTS`. CDN weights come from `CDN_REGIME_WEIGHTS` for the same regime. A sleeve change smaller than 1% does not flip **需要调仓** to 是 and is left off the trade list.

US equity in the one-liner is `QQQ+SOXX+SPY+AIPO`; defensive is `IEF+GLD+DBMF`. CDN equity is `ZQQ.TO+VFV.TO+ZEB.TO+XGD.TO`; defensive is `XBB.TO+CGL-C.TO`.

## Example Issue

Illustration only. The regime sample is `goldilocks` → `deflation` with VIX also stepping `0-20` → `20-28` the same day. The second sample is VIX-only (`0-20` → `28-30`, regime stays `goldilocks`). Numbers follow the weights in the repo today. An unchanged regime and the same VIX band produce no Issue. When the band falls instead of rising, the VIX-only posture line is **防御姿态：可放松**.

```text
标题: [调仓] goldilocks → deflation（2026-09-25）

### 组合变化
象限：**goldilocks → deflation**
**需要调仓：是**（任一标的权重变化达到 1% 为「是」）
同日 VIX 升档：日频 overlay 另应收紧。目标权重仍按新象限调整。
**US 风险姿态：** 股票仓 78% → 30%（-48%）；防御仓 22% → 70%（+48%）。股票仓 = QQQ+SOXX+SPY+AIPO；防御仓 = IEF+GLD+DBMF。
**CDN 风险姿态：** 股票仓 85% → 30%（-55%）；防御仓 15% → 70%（+55%）。股票仓 = ZQQ.TO+VFV.TO+ZEB.TO+XGD.TO；防御仓 = XBB.TO+CGL-C.TO。

**US 目标权重（REGIME_WEIGHTS）**

| 标的 | 原 | 新 | 变化 |
|---|---:|---:|---:|
| IEF | 8% | 35% | +27% |
| GLD | 10% | 20% | +10% |
| SPY | 25% | 20% | -5% |
| DBMF | 4% | 15% | +11% |
| QQQ | 30% | 5% | -25% |
| SOXX | 20% | 3% | -17% |
| AIPO | 3% | 2% | -1% |

**CDN 目标权重（CDN_REGIME_WEIGHTS）**

| 标的 | 原 | 新 | 变化 |
|---|---:|---:|---:|
| XBB.TO | 8% | 50% | +42% |
| CGL-C.TO | 7% | 20% | +13% |
| XGD.TO | 5% | 15% | +10% |
| VFV.TO | 25% | 5% | -20% |
| ZEB.TO | 20% | 5% | -15% |
| ZQQ.TO | 35% | 5% | -30% |

### 建议操作（目标差额，尚未下单）
**US**
- 减持 QQQ 30% → 5%（-25%）
- 减持 SOXX 20% → 3%（-17%）
- 减持 SPY 25% → 20%（-5%）
- 减持 AIPO 3% → 2%（-1%）
- 增持 IEF 8% → 35%（+27%）
- 增持 DBMF 4% → 15%（+11%）
- 增持 GLD 10% → 20%（+10%）
**CDN**
- 减持 ZQQ.TO 35% → 5%（-30%）
- 减持 VFV.TO 25% → 5%（-20%）
- 减持 ZEB.TO 20% → 5%（-15%）
- 增持 XBB.TO 8% → 50%（+42%）
- 增持 CGL-C.TO 7% → 20%（+13%）
- 增持 XGD.TO 5% → 15%（+10%）

### 怎么执行
- 上面是目标权重差额，不是已成交。这封邮件不会下单。
- 本机 TWS 或 Gateway 开着时，先跑 `python scripts/ibkr_rebalance.py`（默认 dry-run，只打印计划）。
- 核对纸账户计划后，再加 `--execute` 才会发单。脚本拒绝向非纸账户 `--execute`。
- 对照仪表盘 **Regime Monitor**（当前象限）和 **Portfolio**（目标权重）。

### 判定依据
- VIX 22.4（档位 20-28 · 偏高）
- CPI YoY 2.40% · GDP 2.10% · SPY 12 月动量 12.0%
- 价格数据截至 2026-09-25；检查时间 2026-09-25 23:05 UTC

象限与仪表盘相同，用 targeted 时钟：CPI 滞后 1 个月，GDP 滞后 4 个月，VIX 月均和 12 个月动量再滞后 1 个月。最新 VIX 高于 30 时，当日标签改为 deflation。VIX 档位用最新收盘；同一档内的波动不单独发信。

本邮件是信号提醒，不是成交回执，也不构成投资建议。
```

VIX-only (regime stays `goldilocks`, band `0-20` → `28-30`):

```text
标题: [风险档位] VIX 28.6 → 开始降敞口（2026-09-25）

### 组合变化
象限未变：**goldilocks**。目标权重不变。
**需要调仓：否**
**防御姿态：应收紧**（VIX 档位升高，日频 overlay 降低股票敞口）
**月中再平衡：不建议（观察为主，不改目标权重）**

### 怎么执行
- **月中再平衡：不建议。** 观察为主，不改四象限目标权重。
- 日频股票敞口由引擎按 VIX 与回撤缩放。这一档只说明 overlay 应收紧还是可放松。
- 若要核对账户是否偏离当前象限目标，本机跑 `python scripts/ibkr_rebalance.py`（默认 dry-run）。不要为了这一档加上 `--execute`。
- 对照仪表盘 **Regime Monitor** 和 **Portfolio**。
- 打印出来的是目标，不是已成交。

### 判定依据
- VIX 28.6（档位 28-30 · 开始降敞口）
- CPI YoY 2.40% · GDP 2.10% · SPY 12 月动量 12.0%
- 价格数据截至 2026-09-25；检查时间 2026-09-25 23:05 UTC

象限与仪表盘相同，用 targeted 时钟：CPI 滞后 1 个月，GDP 滞后 4 个月，VIX 月均和 12 个月动量再滞后 1 个月。最新 VIX 高于 30 时，当日标签改为 deflation。VIX 档位用最新收盘；同一档内的波动不单独发信。

本邮件是信号提醒，不是成交回执，也不构成投资建议。
```

## Enable

1. **Secret `FRED_API_KEY`**  
   Repo → Settings → Secrets and variables → Actions → New repository secret.  
   The key is the same FRED key the backtest uses. The workflow fails closed when the secret is missing (no Issue, no guessed regime).

2. **Actions**  
   Settings → Actions → allow this repository's workflows. The file is `.github/workflows/notify.yml`.  
   Cron: `0 23 * * 1-5` (23:00 UTC weekdays, after the US cash close).  
   You can also run it by hand: Actions → 象限切换提醒 → Run workflow.

3. **Email**  
   The script assigns the Issue to the repository owner and adds the label `rebalance`. It creates that label when it is missing (`issues: write`).  
   Confirm the label exists after the first alert, or create it once:

   ```bash
   gh label create rebalance --color D93F0B --description "Merrill regime or VIX band change / 象限或 VIX 跨档"
   ```

   Email arrives through GitHub notifications: watch the repo (Issues) and/or leave yourself as the assignee. Being the repo owner plus assignee covers the usual account.

4. **First baseline**  
   The first scheduled run (or a manual run with force left off) writes `data/notify_state.json` and pushes it. It does not open an Issue. Later runs compare regime and `vix_band` to that file.

5. **Force test**  
   Actions → 象限切换提醒 → Run workflow → set **force** → Run.  
   That opens one test Issue even when the regime and band are unchanged. Use it to confirm mail delivery, then close the Issue. Closing is fine. Deleting it makes the next audit treat the send as missing.

## Audit

The mail channel is the `rebalance` Issue itself (assignee + label → GitHub notification). The audit answers: when this run should have opened that Issue, does a matching Issue exist?

A run should notify when the regime changes, the latest VIX print crosses a band, or the workflow is started with **force**. Same run:

1. Opens the Issue and requires `number` and `html_url` in the API response.
2. Stores them on `data/notify_state.json` as `last_delivery`, and writes a gitignored run log at `data/notify_audit.json`.
3. Exits non-zero **without** advancing the regime baseline if create fails, the response has no number or URL, or Actions is missing `--github-issue`.

Advancing the baseline after a missed create would make the next day silent. Leaving the previous baseline in place means the next run tries the same alert again.

The following step runs `python scripts/notify_regime.py --audit` when the notify step succeeded or failed (not when it was skipped, for example because install failed):

| Situation | Audit |
|---|---|
| This run should have notified, and a matching `rebalance` Issue exists | Pass. |
| This run should have notified, and no matching Issue exists | Fail. Open one `[审计]` Issue if that fingerprint does not already have an open `notify-audit` Issue. |
| This run stayed silent, and `last_delivery` records an earlier send | Re-check that Issue. Deleted (HTTP 404) → miss. Closed, retitled, or unlabeled still counts as sent. |
| Baseline only, or silent with no `last_delivery` | Quiet. No API call, no audit Issue. |
| Notify step died before a should-fire decision (missing `FRED_API_KEY`, stale prices, short history) | Not a missed alert. The notify step is already red. Audit stays quiet and does not open `[审计]`. |

A stored issue number matches at any age when that Issue still exists and is not a pull request. Closing it, editing the title, or removing the label does not count as a miss. Searching by title (no number, or the number returns 404) only accepts an Issue with the `rebalance` label and the same title, created within **7 days** of `checked_at`, so an older test Issue cannot cover a new miss. Deleting the Issue is a miss.

If this run recorded `delivery=created` and the Issue still cannot be found, `confirmed_miss` stays true even when an audit Issue for that fingerprint is already open, so the new baseline is not pushed. A create that failed earlier does not push a baseline anyway; once its `[审计]` Issue is open, later audits do not open a second one.

The audit Issue is Chinese-titled, for example `[审计] 未发出象限切换提醒（2026-09-25）`. The body names the expected `rebalance` title and states that mail is a GitHub notification, not SMTP. The workflow sets `confirmed_miss=true` and does **not** push a new baseline, so a failed create is not frozen as “already sent”.

An open `notify-audit` Issue with the same fingerprint suppresses a second audit Issue. The log says so and that audit step exits 0 (the notify step is still red when create itself failed). Close the audit Issue and the next run opens another one if the `rebalance` Issue is still missing.

### Run the audit

Locally, against this checkout’s state and the latest `data/notify_audit.json` if you just ran the notifier:

```bash
export GITHUB_REPOSITORY=fintechshan/FontesFund
export GITHUB_TOKEN=...   # Issues read/write. Not required when there is nothing to verify.

python scripts/notify_regime.py --audit
```

In Actions the step is **审计提醒 Issue 是否已创建** in `.github/workflows/notify.yml`. Unit tests cover the decision with a fake Issue lookup and do not call GitHub:

```bash
python -m unittest tests.test_notify_regime
```

A local change without `--github-issue` only prints. It does not advance `notify_state.json`, so a later run can still open the Issue. `--dry-run` is not a should-fire event and does not rewrite `data/notify_audit.json`.

## Data refresh

`data/cache/price_data.csv` and `data/cache/macro_data.pkl` are gitignored, so a runner cannot assume they exist.

Each run calls `python scripts/notify_regime.py --refresh`. That downloads:

- FRED: `VIXCLS`, `CPIAUCSL`, `A191RL1Q225SBEA` (real GDP % change), `DGS10`, `DGS2`
- Yahoo: `SPY` only (12-month momentum)

Runtime is typically one to two minutes including `pip`, not the full `run_backtest.py` universe download and 20-year engine. The production engine remains `python run_backtest.py` when you want the published CSV.

SPY or VIX older than 7 days, or too-short history, aborts the job before any Issue. A failed refresh uses Actions' own failure notification. It does not use the `rebalance` channel.

## State commit and branch protection

The workflow has `contents: write` and pushes with `GITHUB_TOKEN` only when `data/notify_state.json` changes. The commit message ends with `[skip ci]`. This workflow is `schedule` + `workflow_dispatch` only, so that commit does not start another notify run.

`git add` then `git diff --cached` is what detects a new baseline file. A plain `git diff` would miss an untracked state file and skip the first commit.

If branch protection rejects `github-actions[bot]`:

- Allow GitHub Actions to push to the default branch, or
- Add secret **`NOTIFY_PUSH_TOKEN`**: a fine-grained PAT on this repo with Contents read and write. The workflow retries the push with that token. The log records the rejection and does not print the token.

Until the state file lands on the branch, the next run still sees the old baseline and can open a second Issue for the same change.

The save step does not run when the audit step sets `confirmed_miss=true`. A should-fire that did not leave a matching Issue is not recorded as the new baseline.

## Local preview

```bash
pip install 'pandas>=2.1,<3' numpy 'yfinance>=0.2.18' fredapi
export FRED_API_KEY=...          # or put it in .env

python scripts/notify_regime.py --refresh --dry-run
python scripts/notify_regime.py --refresh          # first local baseline, no Issue
python scripts/notify_regime.py --audit            # quiet when nothing should have been sent
```

`--dry-run` prints the Issue and does not write state. Omit `--github-issue` locally unless `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are set. A real change without `--github-issue` prints the Issue and does **not** advance the baseline. Unit tests do not call FRED:

```bash
python -m unittest tests.test_notify_regime
```

`.github/workflows/test-notify.yml` runs that file on pull requests that touch the notifier. It does not use `FRED_API_KEY`. The scheduled workflow is the one that needs the secret.

## Files

| Path | Role |
|---|---|
| `.github/workflows/notify.yml` | Weekday cron, manual force, then `--audit` |
| `scripts/notify_regime.py` | Classify, dedupe, open Issue, audit a miss |
| `data/notify_state.json` | Baseline plus `last_delivery` after a successful Issue. Keep it tracked |
| `data/notify_audit.json` | Gitignored run log for the audit step in the same job |
