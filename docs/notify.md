# 策略调仓提醒（Merrill + QQQ Vegas）

Weekday notifier. It opens **one** GitHub Issue (label `rebalance`) when **either** sleeve changes. GitHub notification settings deliver the email. An optional [Server酱](#微信server酱) push sends the same body to WeChat. There is no SMTP send.

Either sleeve alone is enough. The job does not wait for the other sleeve.

| Sleeve | What counts as a change |
|---|---|
| Merrill | Regime changes (`goldilocks` / `reflation` / `stagflation` / `deflation`), or the latest VIX print crosses a band. |
| QQQ Vegas | `RISK_ON` / `RISK_OFF` / `CASH`, `ENTER` / `EXIT`, `next_action`, a target weight move of at least 1% (70/30 QQQ+QLD versus cash), or the cash ticker switching between BIL and SGOV. |

An unchanged Merrill regime, the same VIX band, and the same QQQ Vegas fingerprint end the run with no Issue. The two fingerprints live side by side in `data/notify_state.json`. Updating one does not clear the other.

If a run should have opened that Issue and it did not, the job fails and an audit Issue (title prefix `[审计]`, label `notify-audit`) is opened so the miss is not silent. See [Audit](#audit). The audit checks the GitHub Issue. A WeChat miss does not roll the baseline back, because the Issue is already the mail.

This path is separate from Cloud Run and from `run_backtest.py`. It does not change `REGIME_WEIGHTS`, `CDN_REGIME_WEIGHTS`, or the CPI+1 / GDP+4 lag. It does not send broker orders.

## When an Issue is opened

One run opens at most one Issue. If Merrill and QQQ Vegas both change on the same run, that one Issue describes both. The body always names the other sleeve, including when it did not fire.

| Event | Issue |
|---|---|
| Merrill regime changes | Yes. Title `[调仓]`. Headline is old → new, **需要调仓：是/否** (any sleeve moves by ≥ 1%), US and CDN weight deltas, equity-vs-defensive one-liners, and a 减持/增持 list. A **QQQ Vegas（本次未触发）** block gives the current ON/OFF state, 70/30 or cash weights, and the last rebalance date. If Vegas also changed, the title gains `· QQQ Vegas …` and the Vegas block is the trade. |
| Latest VIX crosses 20, 28, 30, or 40, regime unchanged, Vegas unchanged | Yes. Title `[风险档位]`. Says whether the overlay should tighten or ease, and **月中再平衡：不建议**. No Merrill weight table. The QQQ Vegas block is still there, marked 本次未触发. |
| QQQ Vegas changes, Merrill regime and VIX band unchanged | Yes. Title `[QQQ Vegas]`. Merrill is summarized as unchanged (**需要调仓：否**). No Merrill weight table. |
| Both sleeves change | Yes. One Issue, title starts with `[调仓]` or `[风险档位]` and includes `QQQ Vegas`. |
| First successful run | No. Writes `data/notify_state.json` only, Merrill fields and `qqq_vegas` together. |
| State file exists but has no `qqq_vegas` yet | No Issue for that adoption. Merrill is compared as usual. The new `qqq_vegas` fingerprint is written. `last_delivery` from the previous Merrill mail is kept. |
| `workflow_dispatch` with **force** | Yes, even when nothing changed. Title `[测试]`. Body includes both sleeves. WeChat is pushed too when the secret is set. |

QQQ Vegas is not recomputed in this workflow. `--refresh` still downloads FRED (`VIXCLS`, CPI, GDP, `DGS10`, `DGS2`) and Yahoo `SPY` only. The Vegas snapshot is the committed pack under `data/qqq_vegas/`, the same files the read-only dashboard tab displays. See [How the QQQ signal gets here](#how-the-qqq-signal-gets-here).

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

### QQQ Vegas（本次未触发）
状态：RISK_ON（下一步 HOLD）
目标权重：QQQ 70% · QLD 30% · 现金 0%
最近调仓：2026-04-09 ENTER（CASH → RISK_ON）
信号截至 2026-10-16。本次 QQQ Vegas 不需要单独动手。
- QQQ Vegas 是只读袖套（风险开启时 70% QQQ + 30% QLD，关闭时现金 BIL 或 SGOV）。它不改 Merrill 的 `REGIME_WEIGHTS`。
- 这封提醒不会下单。对照仪表盘 **QQQ Vegas** 与仓库里的 `data/qqq_vegas/signal_current.json`。

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

### QQQ Vegas（本次未触发）
状态：RISK_ON（下一步 HOLD）
目标权重：QQQ 70% · QLD 30% · 现金 0%
最近调仓：2026-04-09 ENTER（CASH → RISK_ON）
信号截至 2026-10-16。本次 QQQ Vegas 不需要单独动手。

### 判定依据
- VIX 28.6（档位 28-30 · 开始降敞口）
- CPI YoY 2.40% · GDP 2.10% · SPY 12 月动量 12.0%
- 价格数据截至 2026-09-25；检查时间 2026-09-25 23:05 UTC

象限与仪表盘相同，用 targeted 时钟：CPI 滞后 1 个月，GDP 滞后 4 个月，VIX 月均和 12 个月动量再滞后 1 个月。最新 VIX 高于 30 时，当日标签改为 deflation。VIX 档位用最新收盘；同一档内的波动不单独发信。

本邮件是信号提醒，不是成交回执，也不构成投资建议。
```

QQQ Vegas only (Merrill stays `reflation`, VIX stays in `0-20`). One Issue, even though the four-quadrant book did not move:

```text
标题: [QQQ Vegas] RISK_ON → CASH（2026-10-17）

### Merrill 象限
Merrill 象限未变：**reflation**。目标权重不变。
**需要调仓：否**
本次触发的是 QQQ Vegas，不是四象限袖套。

### QQQ Vegas 调仓
**QQQ Vegas 需要调仓：是**（状态、ENTER/EXIT、下一步动作、目标权重达到 1%，或现金标的 BIL/SGOV 切换）
状态：**RISK_ON → CASH**
下一步：HOLD → EXIT
目标：QQQ 70% · QLD 30% · 现金 0% → QQQ 0% · QLD 0% · 现金 100%（BIL）
最近调仓：2026-04-09 ENTER（CASH → RISK_ON） → 2026-10-17 EXIT（RISK_ON → CASH）
信号截至 2026-10-17
- QQQ Vegas 是只读袖套（风险开启时 70% QQQ + 30% QLD，关闭时现金 BIL 或 SGOV）。它不改 Merrill 的 `REGIME_WEIGHTS`。
- 这封提醒不会下单。对照仪表盘 **QQQ Vegas** 与仓库里的 `data/qqq_vegas/signal_current.json`。

### 判定依据
- VIX 15.3（档位 0-20 · 正常）
- 价格数据截至 2026-10-14；检查时间 2026-10-17 23:05 UTC

本邮件是信号提醒，不是成交回执，也不构成投资建议。
```

Same-day Merrill and Vegas changes are still one Issue. The title looks like `[调仓] goldilocks → deflation · QQQ Vegas RISK_ON → CASH（2026-09-25）`. A weight-only Vegas change (state stays `RISK_ON`) is titled `[QQQ Vegas] 权重变化 RISK_ON（…）`. A `next_action` change with the same state is titled `[QQQ Vegas] 信号 HOLD → EXIT（…）`.

## How the QQQ signal gets here

The dashboard tab and this notifier both read `data/qqq_vegas/signal_current.json`. There is no FRED-style download for Vegas in `notify.yml`. A runner only sees what is committed on the branch it checks out.

To publish a new Vegas signal:

1. Regenerate the pack with the same offline builder that produced `data/qqq_vegas/` (`signal_current.json`, and `rebalances.csv` when a new ENTER/EXIT row exists). `last_rebalance` inside the JSON is what the notifier prefers. If that object is missing, the last row of `rebalances.csv` is the fallback.
2. Commit those files to the default branch and push.
3. The next weekday run (or a manual **Run workflow**) checks the new snapshot against `qqq_vegas` in `data/notify_state.json`.

Fields that fire: `state`, `next_action`, `qqq_w` / `qld_w` / `cash_w` (1% band), `cash_ticker` (empty versus `BIL` versus `SGOV`), `last_rebalance.date`, `last_rebalance.action`. `as_of`, `signal_date`, and the prose `reason` do not fire by themselves. A missing or unreadable signal file is not an exit to cash: the job warns and keeps the stored fingerprint. `RISK_OFF` and `CASH` are different states; either one leaving `RISK_ON` fires.

`schema` 2 means the file has a `qqq_vegas` object. A schema 1 file still compares Merrill. The first run that sees a readable pack writes `qqq_vegas` and does not treat that adoption as a trade.

## Enable

1. **Secret `FRED_API_KEY`**  
   Repo → Settings → Secrets and variables → Actions → New repository secret.  
   The key is the same FRED key the backtest uses. The workflow fails closed when the secret is missing (no Issue, no guessed regime).

2. **Actions**  
   Settings → Actions → allow this repository's workflows. The file is `.github/workflows/notify.yml`.  
   Cron: `0 23 * * 1-5` (23:00 UTC weekdays, after the US cash close).  
   You can also run it by hand: Actions → 策略调仓提醒 → Run workflow.

3. **Email**  
   The script assigns the Issue to the repository owner and adds the label `rebalance`. It creates that label when it is missing (`issues: write`).  
   Confirm the label exists after the first alert, or create it once:

   ```bash
   gh label create rebalance --color D93F0B --description "Merrill, VIX band, or QQQ Vegas change / 象限、VIX 或 QQQ Vegas"
   ```

   Email arrives through GitHub notifications: watch the repo (Issues) and/or leave yourself as the assignee. Being the repo owner plus assignee covers the usual account.

4. **First baseline**  
   The first scheduled run (or a manual run with force left off) writes `data/notify_state.json` and pushes it. It does not open an Issue. Later runs compare Merrill `regime` and `vix_band`, and the `qqq_vegas` fingerprint, to that file. Each sleeve has its own fields. A QQQ change does not rewrite the Merrill comparison into a false "already switched", and a Merrill change does not clear the Vegas fingerprint.

5. **WeChat (Server酱)**  
   Repo secret **`SERVERCHAN_SENDKEY`**. Leave it unset and the job still opens the Issue; the log warns and skips WeChat. See [微信（Server酱）](#微信server酱).

6. **Force test**  
   Actions → 策略调仓提醒 → Run workflow → set **force** → Run.  
   That opens one test Issue even when the regime, the VIX band, and QQQ Vegas are unchanged, and it pushes WeChat when the secret is set. Use it to confirm mail (and WeChat) delivery, then close the Issue. Closing is fine. Deleting it makes the next audit treat the send as missing.

## 微信（Server酱）

The mail channel is the GitHub Issue. WeChat is the same notice, sent after the Issue exists, as text only.

The SendKey is a password. It lives only in the GitHub Actions secret `SERVERCHAN_SENDKEY`. Do not commit it, do not paste it into docs or pull requests, and do not put it in the dashboard or any other frontend. The workflow injects it into the notify step and the script never prints it.

1. Open [sct.ftqq.com](https://sct.ftqq.com/), copy the SendKey (it looks like `SCT` plus letters and digits), and bind the WeChat channel in that console. This repo does not choose the channel.
2. On GitHub: the repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Name: `SERVERCHAN_SENDKEY`. Value: the SendKey alone.
3. On a Merrill or QQQ Vegas trigger the script `POST`s form fields to `https://sctapi.ftqq.com/<SendKey>.send`:
   - `title` — required, one line, cut at 40 characters. The full title is repeated at the top of `desp`.
   - `desp` — Markdown text (the Issue body). No images, no screenshot host, no extra upload.
   - Success is JSON `code == 0`.
4. One run sends one message, even when both sleeves fire. A quiet run sends nothing, so it does not spend the free quota (about 5 messages a day). A **force** run spends one.
5. Missing secret: warning, no HTTP call, Issue still opens, baseline still advances, job stays green when the Issue succeeded.
6. Server酱 returns `code != 0`, or the HTTP call fails: warning only. The baseline still advances. Rolling it back would open a second Issue on the next run. Fix the secret or the channel binding, then use **force** if you want another copy.

PushPlus is not connected. Do not add a `PUSHPLUS_TOKEN` value to the repo. A later change can read that secret if a second channel is needed.

The audit step does not call Server酱. It only checks that the `rebalance` Issue exists.

## Audit

The mail channel is the `rebalance` Issue itself (assignee + label → GitHub notification). The audit answers: when this run should have opened that Issue, does a matching Issue exist?

A run should notify when the Merrill regime changes, the latest VIX print crosses a band, QQQ Vegas changes, or the workflow is started with **force**. Same run:

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

`.github/workflows/test-notify.yml` runs that file on pull requests that touch the notifier. It does not use `FRED_API_KEY` or `SERVERCHAN_SENDKEY`. The scheduled workflow needs `FRED_API_KEY`. `SERVERCHAN_SENDKEY` stays optional there.

## Files

| Path | Role |
|---|---|
| `.github/workflows/notify.yml` | Weekday cron, manual force, optional Server酱, then `--audit` |
| `scripts/notify_regime.py` | Classify both sleeves, dedupe, open one Issue, push WeChat, audit a miss |
| `data/notify_state.json` | Merrill baseline, `qqq_vegas` fingerprint, and `last_delivery` after a successful Issue. Keep it tracked |
| `data/qqq_vegas/signal_current.json` | Committed Vegas signal the notifier reads. Not refreshed by `--refresh` |
| `data/notify_audit.json` | Gitignored run log for the audit step in the same job |
