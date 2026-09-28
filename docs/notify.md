# 象限 / VIX 跨档提醒

Weekday notifier. It opens a GitHub Issue (label `rebalance`) only when the Merrill regime changes or the latest VIX print crosses a band. GitHub notification settings deliver the email. An unchanged regime and the same VIX band end the run with no Issue.

This path is separate from Cloud Run and from `run_backtest.py`. It does not change `REGIME_WEIGHTS`, `CDN_REGIME_WEIGHTS`, or the CPI+1 / GDP+4 lag.

## When an Issue is opened

| Event | Issue |
|---|---|
| Regime changes (`goldilocks` / `reflation` / `stagflation` / `deflation`) | Yes. Title `[调仓]`. Body has old → new and US + CDN weight deltas. |
| Latest VIX crosses 20, 28, 30, or 40 | Yes. Title `[风险档位]`. Same-band moves (21 → 27) stay silent. |
| First successful run | No. Writes `data/notify_state.json` only. |
| `workflow_dispatch` with **force** | Yes, even when nothing changed. Title `[测试]`. |

Bands: `0-20` 正常, `20-28` 偏高, `28-30` 开始降敞口, `30-40` 大幅降敞口, `40+` 接近清仓股票.

The regime is `classify_regimes(..., apply_lag=True)` from `run_dashboard.py` (CPI lagged 1 month, GDP lagged 4 months). The script loads that function with `ast` so importing `run_dashboard` does not run dashboard startup. The VIX band uses the latest `VIXCLS` print. Monthly average VIX above 30 still forces `deflation` inside the classifier.

US weights come from `REGIME_WEIGHTS`. CDN weights come from `CDN_REGIME_WEIGHTS` for the same regime.

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
   That opens one test Issue even when the regime and band are unchanged. Use it to confirm mail delivery, then close the Issue.

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

## Local preview

```bash
pip install 'pandas>=2.1,<3' numpy 'yfinance>=0.2.18' fredapi
export FRED_API_KEY=...          # or put it in .env

python scripts/notify_regime.py --refresh --dry-run
python scripts/notify_regime.py --refresh          # first local baseline, no Issue
```

`--dry-run` prints the Issue and does not write state. Omit `--github-issue` locally unless `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are set. Unit tests do not call FRED:

```bash
python -m unittest tests.test_notify_regime
```

`.github/workflows/test-notify.yml` runs that file on pull requests that touch the notifier. It does not use `FRED_API_KEY`. The scheduled workflow is the one that needs the secret.

## Files

| Path | Role |
|---|---|
| `.github/workflows/notify.yml` | Weekday cron and manual force |
| `scripts/notify_regime.py` | Classify, dedupe, open Issue |
| `data/notify_state.json` | Created on the first run; keep it tracked |
