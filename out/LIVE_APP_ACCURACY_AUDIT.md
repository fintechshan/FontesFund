# Live app accuracy audit

**Date:** 2026-09-27  
**Repo:** `fintechshan/FontesFund` at `main` `3c39173` (same commit as `origin/main`)  
**Live app:** https://etf-regime-strategist-322569756829.asia-east2.run.app/  
**What was read from the live process:** Dash layout JSON (`/_dash-layout`), HTTP 200, 3.2 MB, served 2026-09-27 06:28 UTC. Layout stamp inside the page: generated 2026-09-27 06:16. Python 3.10.21, Dash 4.4.1.  
**What was not done:** no Cloud Run change, no merge, no strategy-parameter edit.

The live numbers below are the strings in that layout, not a remembered screenshot.
They describe the page **before** the label and limit fixes in this branch. A short
checklist of those fixes is at the end of this file. The findings tables are the
before-state and are left as the audit record.

**Later display change (not a new backtest):** the Backtest tab and the Portfolio CAGR
card now open on Auditor Lagged (extra month, **12.21% / 14.10% / 0.83**). Production
**14.85% / 13.90% / 1.03** stays the engine CSV and the labeled Backtest alternate.
CDN still has no extra-month series; its US column follows that Backtest default.

---

## Verdict

The US headline **14.85% CAGR / 13.90% MaxDD / Sharpe 1.03 / vol 12.60%** is the production engine with CPI lagged +1 month and GDP lagged +4 months, missing ETFs renormalized into the names that already trade, 5 bp costs, and the v7 sleeve. A fresh run of that path on Yahoo prices and public FRED data for **2005-01-04 → 2026-09-21** prints the same displayed figures.

The Auditor column labeled **Lagged, 12.21% / 14.10% / Sharpe 0.83**, is that same publication-lagged regime shifted **one more month**. It is a harsher delay than the release calendar. It is not the number the Portfolio and Backtest tabs show.

Turning the publication lag off prints **15.74% CAGR** (Sharpe 1.11, MaxDD 14.58% in the fresh run). The live Auditor states this premium in prose: “unlagged 15.74% → production 14.85%” (+0.89 percentage points). The Portfolio card subtitle “no look-ahead” matches that production path. The Auditor chart title that calls the **same 14.85% curve** “Standard Strategy (Look-Ahead Bias)” does not.

`CLAUDE.md` and `README.md` still quote the older **8-ETF v5.1** result **14.52% / 14.78% / 0.97**. The engine weight table and the live app are **7-ETF v7**. Overlay knobs (vol target 13%, bear fraction 0.70, drawdown trigger 7%, HAR on, 5 bp) are unchanged. The Goldman-style throttle from draft PR #4 is absent from `main` and from the live layout.

---

## Live figures captured 2026-09-27

| Surface | Live text |
|---|---|
| Portfolio card | Backtest CAGR **14.85%**. Subtitle: “Sharpe 1.03 \| DD 13.90% (7-ETF v7, no look-ahead)” |
| Backtest cards | Annual Return **14.85%** (“20yr CAGR”), Sharpe **1.03**, Max Drawdown **13.90%**, Sortino 1.39, Calmar 1.07, Total Return **1909.27%** (“2005-2026”) |
| Backtest table, Optimized Regime Strategy | 14.85% / vol 12.60% / Sharpe 1.03 / Max DD 13.90% / Win Rate 54.5% / Total 1909.27% |
| Auditor Standard column | 14.85% / Sharpe 1.03 / Max DD 13.90% / Total 1909.27% |
| Auditor Lagged column | **12.21%** / Sharpe **0.83** / Max DD **14.10%** / Total **1113.59%** |
| Auditor warning | “CAGR drop: 2.64% (Standard: 14.85%, Lagged: 12.21%). Sharpe drop: 0.20 (Standard: 1.03, Lagged: 0.83).” Status WARNING |
| Auditor unlagged (prose only, not in the comparison table) | “Publication lag removes a +0.89% look-ahead premium (unlagged **15.74%** → production **14.85%**).” |
| CDN cards | CAGR **14.62%** (“20-yr backtest (CAD)”), Max DD **15.53%**, Sharpe **1.16**, Vol **10.90%**, Win Rate 56.4% (“Monthly positive %”), Total **552.90%** |
| CDN header line | “CAGR 14.62% \| MaxDD 15.53% \| Sharpe 1.16 \| Vol 10.90%” |
| Tax-study panel (Portfolio tab) | RRSP/taxable **20.12%** CAGR, Sharpe 1.31, MaxDD −15.14%, vol 13.90%. TFSA **19.79%**. All-Canadian **8.58%** / 0.67 / −29.18%. Window label: “2012-02 → 2026-06” |

Cache stamps on the live page: macro fetched **2026-09-22 12:30:22**, backtest CSV **2026-09-22 16:06:54**. The US equity chart’s last date in the layout is **2026-09-21**. Those match the CSVs committed in the repo (`data/backtest_results/20yr_comparison.csv`, `all_equity_curves.csv` ending 2026-09-21, `cdn_strategy_config.json` `as_of` 2026-09-20, CDN curve ending 2026-09-18).

---

## How each number is computed

Costs and overlays, unless a row says otherwise, come from `config/regime_rules.py` `STRATEGY_PARAMS`: risk parity on, 60-day inverse-vol, target vol 13%, vol cap 0.50–1.50, HAR-RV on, bear equity fraction 0.70, drawdown trigger 7%, transaction cost 5 bp, borrow spread 1% on gross leverage above 1. The VIX gate only redirects TQQQ/SOXL; v7 has neither, so the gate is idle. Sample for the US cards is the equity curve **2005-01-04 → 2026-09-21** (5,462 points, 21.67 years at 252 days).

US sleeve in `REGIME_WEIGHTS`: **QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO**. Defense basket inside the engine, used only when SPY is below its lagged 200-day average: SHY 35% / AGG 20% / GLD 25% / IEF 20%.

Missing names are **renormalized**, not parked in cash. `run_optimized_regime_backtest` keeps a ticker only when yesterday’s price exists, then rescales the remaining weights to 1 (`src/backtester/engine.py`, `weight_matrix`). `run_backtest.py` also renormalizes once up front to columns present in the file; with the current seven names all downloaded, that step does not change the table.

| UI label | Displayed claim (live) | Code path | Lag | Missing ETFs | Costs / rf | Window and sleeve | Reproduced | Verdict |
|---|---|---|---|---|---|---|---|---|
| Portfolio “Backtest CAGR” | 14.85%; subtitle Sharpe 1.03, DD 13.90%, “7-ETF v7, no look-ahead” | `build_portfolio_tab` reads `data/backtest_results/20yr_comparison.csv`, row `Optimized Regime Strategy`. CSV is written by `run_backtest.py` → `BacktestEngine.run_optimized_regime_backtest` + `STRATEGY_PARAMS` | CPI +1 month, GDP +4 months in `run_backtest.py` (`CPI_RELEASE_LAG_M=1`, `GDP_RELEASE_LAG_M=4`) | Renormalize | 5 bp, 1% borrow spread, rf = mean DFF = **1.8676%** over 2005-01-01..2026-09-21 | 2005-01-04 → 2026-09-21. Weights: QQQ SOXX SPY IEF GLD DBMF AIPO. AIPO prints start **2025-07-25** (291 sessions). DBMF prints start **2019-05-08** (1,853 sessions) | Fresh engine: **14.85% / 13.90% / 1.03 / vol 12.60%**. Repo curve recomputed: 14.8495% / 13.8988% / vol 12.603% | **Accurate** on the lag and the level. **Misleading** on “7-ETF” for the whole 20 years: most of the sample is a renormalized subset (no DBMF before May 2019, no AIPO before 25 Jul 2025) |
| Backtest tab cards and comparison row | 14.85% / 1.03 / 13.90% / vol 12.60% / Sortino 1.39 / Calmar 1.07 / Win Rate 54.5% / Total 1909.27%. Subtitles “20yr CAGR” and “2005-2026” | `build_backtest_tab`, same CSV. Equity and monthly heatmap are the optimized curve (`all_equity_curves.csv`, `aggressive_monthly_returns.csv` — that filename is the optimized result, see `run_backtest.py` save block) | Same publication lag | Renormalize | Same | Same window. Win rate is the **daily** fraction of up days in `_compute_result` (`(returns > 0).sum() / len(returns)`). Repo curve: 54.50% of days, **62.5% of months** (261 months) | Curve math matches the CSV at display precision (total return 1909.27%, daily win 54.5%) | **Accurate** for CAGR, Sharpe, MaxDD, vol, total return. Win Rate is a real daily statistic and is not labeled “monthly” on this tab |
| Auditor “Standard” | 14.85% / 1.03 / 13.90% / 1909.27% | `run_dashboard.py` startup: `classify_regimes(..., apply_lag=True)` then `run_optimized_regime_backtest`. Stored as `lagged_metrics['standard']`. Shown by `build_auditor_tab` | CPI +1, GDP +4. On this sample the dashboard classifier and `run_backtest.py` classifier agree on **100%** of months, so this column equals the CSV | Renormalize (full `REGIME_WEIGHTS` passed in; the engine drops names with no price) | Same `STRATEGY_PARAMS`, rf = mean fed funds | Same price cache the container loaded (GCS or baked CSV). Chart x starts 2005-01-04 | Fresh dashboard-equivalent run: **14.85% / 1.03 / 13.90%** | **Accurate** as a level. The column header “Standard” and the paragraph under it describe a backtest that treats CPI/GDP as known on the period date. That description is **wrong** for this column. This column is already the lagged production run |
| Auditor “Lagged” | 12.21% / 0.83 / 14.10% / 1113.59% | Same startup block: `regime_history['regime'].shift(1).bfill()` **after** the publication lag, then the engine again. `lagged_metrics['lagged']` | Publication lag **plus one extra month** on the whole regime label (VIX override and momentum timing move too) | Renormalize | Same | Same sample | Fresh run: **12.21% / Sharpe 0.83 / MaxDD 14.10% / vol 12.40% / total 1113.48%** (live total 1113.59%; 0.11 point of cumulative return, same displayed CAGR) | **Accurate** as the output of that extra shift. **Misleading** as “1-month reporting lag on GDP and CPI.” CPI is already +1 month and GDP +4. This column is a second delay. The hardcoded line “minor decrease in Sharpe but the model remains highly robust” fights the WARNING on the same page (Sharpe 1.03 → 0.83, CAGR −2.64 points) |
| Auditor unlagged check (prose) | unlagged 15.74% → production 14.85% | `classify_regimes(..., apply_lag=False)` → `lagged_metrics['unlagged']`. Not shown in the Standard/Lagged table | **No** CPI/GDP publication lag | Renormalize | Same | Same | Fresh run: **15.74% / Sharpe 1.11 / MaxDD 14.58% / vol 12.52%** | **Accurate.** This is the look-ahead case. It is higher than the headline, which is what the publication lag is supposed to do |
| Auditor chart | Legend “Standard Strategy (Look-Ahead Bias)” on the green line; “Lagged Strategy (1-Month Reporting Lag)” on the dashed line | `make_auditor_curves` in `src/dashboard/app.py` | Green line is `standard_curve` = production **with** publication lag | — | — | Same | Green line is the 14.85% path | **Wrong caption.** The green line is the lagged production curve. The dashed line is the extra-month path |
| CDN “CAGR (CDN)” and the side-by-side CDN column | 14.62% / 15.53% / Sharpe 1.16 / vol 10.90% / Win Rate 56.4% / Total 552.90%. Subtitle “20-yr backtest (CAD)”. Win Rate subtitle “Monthly positive %” | `build_cdn_portfolio_tab` reads `data/backtest_results/cdn_strategy_config.json` (and the CDN equity CSV). Written by `scripts/run_cdn_backtest.py` | CPI +1, GDP +4. Growth momentum is **VFV.TO** 12-month, not SPY | Renormalize. At the published start every sleeve name already exists (see below) | Same overlays, but rf is **hardcoded 2%**, not mean fed funds. **200-day SPY hedge does not run** (no SPY column → `trend_ok = 1`). Defense basket is empty (no SHY/AGG/GLD/IEF in the CDN frame), so `r_def = 0` | Committed curve **2012-11-27 → 2026-09-18**, 3,465 points, **13.75 years**. Sleeve: ZQQ.TO, VFV.TO, ZEB.TO, XBB.TO, CGL-C.TO, XGD.TO | Recompute of the committed curve: **14.62% / 15.53% / Sharpe 1.158 at rf=2% / vol 10.91% / total 552.90%**. Daily win **56.4%**. Monthly win **65.9%** | **Accurate** versus its own curve for CAGR, MaxDD, Sharpe, vol, total return. **Misleading** “20-yr” (it is 13.8 years). **Wrong** “Monthly positive %” (the engine’s win rate is daily; monthly is 65.9%). **Misleading** footer “Same BacktestEngine + regime classification as US”: the function is the same, the trend hedge and defense sleeve do not fire, momentum is VFV, and rf is 2% |
| CDN vs US table, US column | 14.85% / 13.90% / 1.03 | Same CSV as the Backtest tab (`us_row` in `build_cdn_portfolio_tab`) | Publication lag | Renormalize | US rf | 2005–2026 vs CDN 2012–2026, stated in the caption | Matches the US CSV | **Accurate** as a pointer at Tab 3. The two Sharpes use different risk-free rates (1.87% vs 2%) and different windows |
| Tax study “Net CAGR” | 20.12% RRSP/taxable, 19.79% TFSA, 8.58% all-Canadian. Caveat on the live page: “local-USD CAGR ~18%” and “SPYI/DBMF … uranium” | `build_tax_study_panel` reads `data/cache/tax_study.json`, produced by `ab_canadian_tax.py` (gitignored cache; file is on the server, not in this checkout) | Whatever `optimize_strategy.py` regime history that script used. It is **not** `run_optimized_regime_backtest` with HAR | Separate static Canadian book: 35% XIC + 20% ZWB + 15% XEI + 15% ZFL + 15% CGL | Withholding study. US book converted with USDCAD | Live label: **2012-02 → 2026-06**, CAD | Not re-run. `data/cache/ab_canada_prices.csv` is gitignored and was not on disk | **Misleading** next to the 14.85% card. 20.12% is a CAD, FX-inclusive planning figure on a different window and a different engine. The panel does say “planning study” and “local-USD CAGR ~18%”. The drag sentence names IEF/AIPO while the caveat still names SPYI and uranium |

Regime Monitor does not show a strategy CAGR. It shows live macro and sector returns. Covered-call figures on the Portfolio tab are premium estimates (trailing realized vol), not backtest CAGR.

---

## Contradictions on one site

1. **Portfolio card vs Auditor chart.** Both use the 14.85% series. The card says “no look-ahead.” `make_auditor_curves` names that series “Standard Strategy (Look-Ahead Bias).” The card matches the code. The chart caption does not.

2. **Auditor paragraph vs Auditor arithmetic.** The paragraph says a standard backtest “assume[s] this data is known instantly on the first of the month” and that the test “lag[s] macro indices” by about a month. The Standard column is already CPI+1 / GDP+4. The Lagged column is an extra `shift(1)` of the regime label. The unlagged case (true instant macro) is 15.74% and is only in a different paragraph.

3. **“Minor” vs the warning.** The italic under the Auditor table is a fixed sentence: a one-month shift causes “a minor decrease in Sharpe” and “the model remains highly robust.” The same page’s diagnostic is a WARNING for a 2.64 point CAGR drop and a Sharpe drop of 0.20 (threshold in `auditor.py` is 2 points of CAGR or 0.25 Sharpe). The banner “Gemini Independent Auditor … No exceptions found” is shown only when every check is PASS. On this snapshot the look-ahead row is WARNING, so that banner is not up. The sentence still exists in `build_audit_findings_panel` for a future all-PASS run.

4. **Docs vs the app.** `README.md` and `CLAUDE.md` (dated 2026-06-22 in the brief) still say 8-ETF v5.1, **14.52% / 14.78% / Sharpe 0.97**, sleeve QQQ, SOXX, SPY, SPYI, TLT, GLD, DBMF, URA. Live and `REGIME_WEIGHTS` are 7-ETF v7: QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO, headline 14.85% / 13.90% / 1.03. The class comment in `run_optimized_regime_backtest` still says “~16.2% CAGR / −14.7% MaxDD / Sharpe ~1.13.” `PERFORMANCE_TARGETS` is still the 16% / 14.8% / 1.2 goal, which this sample does not meet (MaxDD 13.90% is inside 14.8%; CAGR and Sharpe are short).

5. **CDN “unhedged Nasdaq” vs the ticker.** `config/cdn_regime_rules.py` opens with “Unhedged US Core + Nasdaq AI Tech” and describes ZQQ.TO as “BMO NASDAQ 100 Equity Index ETF.” Yahoo’s long name for **ZQQ.TO** is “BMO Nasdaq 100 Equity Hedged to CAD Index ETF.” The unhedged BMO Nasdaq ETF is **ZNQ.TO** (“BMO NASDAQ 100 Equity Index ETF”), first print **2019-02-19**. The dashboard name map says “BMO NASDAQ 100 Index ETF” and does not say hedged. XQQ.TO, which is explicitly CAD-hedged, tracks ZQQ year by year (2022: ZQQ −33.8%, XQQ −33.7%, QQQ −32.6%, while USDCAD rose 6.3% and ZNQ was −28.1%). ZQQ’s CAD price follows QQQ in USD (two-factor beta on QQQ ≈ 1.00, beta on USDCAD ≈ 0.00 over 2019-02-19 → 2026-09-21). ZNQ’s calendar-year gap versus ZQQ lines up with USDCAD (2022 +5.7 points vs FX +6.3; 2024 +11.8 vs FX +8.5; 2025 −3.4 vs FX −4.6). The backtest holds ZQQ, so the Nasdaq sleeve is **hedged**. VFV is the unhedged S&P sleeve. Nothing in `scripts/run_cdn_backtest.py` substitutes ZNQ or backfills ZQQ with QQQ.

6. **AIPO’s display name.** Yahoo: “Defiance AI & Power Infrastructure ETF.” `REGIME_WEIGHTS` comments say that. The Portfolio ticker map (`src/dashboard/app.py`) says “AI IPO & Innov,” and `config/etf_universe.py` says “AI-Powered IPO & Innovation ETF.” The listing date in the price history is **2025-07-25**, which matches the first-trade timestamp Yahoo returns.

---

## Reproduction

### US headline and Auditor

Commands used (network; nothing written under `data/cache`):

- Prices: `yfinance` download of QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO, SHY, AGG, TLT, SPYI, URA, `start=2005-01-01`, `end=2026-09-22`, `auto_adjust=True`, then reindexed to SPY’s sessions and cut at 2026-09-21. That is the alignment `run_backtest.py` does.
- Macro: FRED CSV, no API key: `VIXCLS`, `A191RL1Q225SBEA` (real GDP percent change), `CPIAUCSL`, `DFF`.
- Engine: `BacktestEngine.run_optimized_regime_backtest(..., **STRATEGY_PARAMS)` on this tree.

| Run | Classifier | Lag | CAGR | Vol | Sharpe | MaxDD | Total |
|---|---|---|---|---:|---:|---:|---:|
| Live Portfolio / Backtest / Auditor Standard | — | — | 14.85% | 12.60% | 1.03 | 13.90% | 1909.27% |
| Fresh, `run_backtest.py` rules | monthly SPY momentum, `resample('MS').last()` | CPI+1, GDP+4 | **14.85%** | **12.60%** | **1.03** | **13.90%** | 1909.12% |
| Fresh, `run_dashboard.classify_regimes` | daily 252-day momentum, GDP `resample('MS').ffill()` | CPI+1, GDP+4 | **14.85%** | **12.60%** | **1.03** | **13.90%** | 1909.12% |
| Fresh, extra month (`regime.shift(1)`) | either classifier (they matched) | publication lag + 1 month | **12.21%** | 12.40% | **0.83** | **14.10%** | 1113.48% |
| Fresh, lag off | either classifier | none | **15.74%** | 12.52% | 1.11 | 14.58% | 2275.52% |
| Committed `all_equity_curves.csv` recomputed with the engine formulas | — | — | 14.8495% | 12.603% | 1.03 at rf 1.87% | 13.899% | **1909.27%** |

Regime mix under the publication lag: goldilocks 69.5%, reflation 15.2%, deflation 13.3%, stagflation 2.0% (256 months). The two classifiers agreed on every month in this sample, lagged and unlagged, so the dashboard startup path and the CSV writer are the same number here.

The cumulative-return gap versus the committed curve (1909.12% vs 1909.27%) is a few basis points of total wealth, inside the rounding of 14.85% and 13.90%. Adjusted closes move. Displayed CAGR, Sharpe, MaxDD, and vol match.

A flat pre-listing AIPO price is **not** a valid “hold AIPO as cash” test under inverse-vol: zero volatility makes that sleeve take the whole risk-parity book. That experiment was discarded. The live 14.85% is the renormalize path, which is what `weight_matrix` does. Draft PR #4 (not merged, not on this tree) reported that parking AIPO’s strategic weight in cash instead costs about 0.24 points of CAGR (14.85% → 14.61%) on this sample. That hook is not in `main`.

### CDN

`cdn_price_data.csv` is not in git (only `gsblbr_history.csv` is force-included). The committed equity curve is.

Recompute of `data/backtest_results/cdn_equity_curve.csv` with rf = 2% and the engine’s 252-day year: **CAGR 14.62%, vol 10.91%, Sharpe 1.16, MaxDD 15.53%, total 552.90%, daily win 56.38%, monthly win 65.87%.** That is the live card, including the win-rate label error.

Fresh TSX-only Yahoo download (`CDN_UNIVERSE`, `start=2012-01-01`, `end=2026-09-22`), same classifier as `scripts/run_cdn_backtest.py`, rf = 2%, `STRATEGY_PARAMS`:

| Slice | What it is | CAGR | Vol | Sharpe | MaxDD | Points |
|---|---|---:|---:|---:|---:|---:|
| 2012-11-27 → 2026-09-18 | published curve’s dates | **14.58%** | **10.90%** | 1.15 | **15.53%** | 3,464 vs 3,465 in the file |
| 2012-11-08 → 2026-09-21 | first day all six names exist, through the latest print | 14.73% | 10.90% | 1.17 | 15.53% | 3,478 |
| 2012-01-04 → 2026-09-21 | what the script does today if the price frame still contains pre-VFV rows | 13.84% | 10.52% | 1.12 | 15.53% | 3,693 |

Vol and MaxDD on the published window match the card. CAGR is 4 basis points lower (14.58% vs 14.62%) and Sharpe rounds to 1.15 instead of 1.16. That is a price-revision residual, not a second methodology. The script as written does **not** cut the price frame at the common start; it only starts the regime calendar there. A naive re-run therefore includes January–November 2012 with VFV missing and the other weights scaled up, and the CAGR falls to 13.84%. The published curve starts **2012-11-27**, nineteen days after VFV’s first print (2012-11-08), so the live 14.62% does not include that pre-VFV stretch.

### Listing dates (Yahoo adjusted close, this download)

| Ticker | First print | Role in the live number |
|---|---|---|
| AIPO | 2025-07-25 | In the v7 weights the whole time; held only after this date; earlier weight renormalized |
| DBMF | 2019-05-08 | Same |
| VFV.TO | 2012-11-08 | Binds the CDN common start |
| CGL-C.TO | 2012-01-24 | Exists before the CDN curve starts. Unhedged gold (Yahoo: “Non-Hedged”) |
| ZQQ.TO | 2010-01-25 | Hedged Nasdaq. Real history, not a ZNQ backfill |
| ZNQ.TO | 2019-02-19 | Not in `CDN_UNIVERSE`. Not used to extend ZQQ |
| ZEB.TO | 2010-04-20 | In the CDN book |
| XBB.TO, XGD.TO | before 2005 | In the CDN book |

There is no `bfill` of CDN prices in `scripts/run_cdn_backtest.py`. `ffill` does not create prices before the first print. Pre-listing handling is the engine’s renormalize. Inside the published CDN window, every one of the six tickers has already listed, so that curve is not a backfilled portfolio. Extending the frame back to January 2012 **lowers** CAGR. The comment in `verify_portfolio.py` that “Portfolio B’s 14.62% … came substantially from pre-inception history” does not describe this curve.

---

## v7 sleeve, docs, throttle

Live config is v7. `REGIME_WEIGHTS` in `config/regime_rules.py` is the 7-name book above. `run_backtest.py` `ALL_TICKERS` still downloads extras (SPYI, TLT, URA, XLY, XEI.TO, ZWB.TO) for benchmarks and old studies; they are not in the production weight table. `STRATEGY_PARAMS` is what both `run_backtest.py` and `run_dashboard.py` unpack into the engine. The live Rebalancing Rules panel is rendered from that dict (7% drawdown breaker, 30% to defense when SPY is under the 200-day average, “No leveraged ETFs in the current 7-ETF universe — gate inactive”, HAR on, vol target 13%).

`CLAUDE.md` §1 and the README banner still describe v5.1 and 14.52% / 14.78% / 0.97 through 2026-06-26. Those were the honest lagged numbers for the **old** sleeve. They are not what asia-east2 is showing.

Draft PR #4 (`cursor/gs-ml-throttle-contrast-0982`, open, not merged) adds an optional GSBLBR throttle and concludes it should stay off. `main` has no `gs_throttle` argument. The live layout has no throttle control and no GS band in the weight path. `data/cache/gsblbr_history.csv` is only an indicator series. The throttle is not deployed.

---

## Reproduce again

```bash
# US publication-lag headline (writes data/cache and data/backtest_results):
python run_backtest.py

# CDN artifact writer (needs data/cache/macro_data.pkl; does not slice prices
# to the common start, so a fresh 2012-01-01 download will not hit 14.62%):
python scripts/run_cdn_backtest.py

# Curve already on disk, no download:
python - << 'PY'
import pandas as pd, numpy as np
eq = pd.read_csv('data/backtest_results/all_equity_curves.csv', index_col=0, parse_dates=True)
s = eq['Optimized Regime Strategy'].dropna()
r = s.pct_change().dropna()
ny = len(r)/252
tot = (1+r).prod()-1
cagr = (1+tot)**(1/ny)-1
vol = r.std()*np.sqrt(252)
dd = abs((s/s.cummax()-1).min())
print(f'US {s.index[0].date()} {s.index[-1].date()} CAGR {cagr:.4%} vol {vol:.4%} MaxDD {dd:.4%} tot {tot:.2%}')
cdn = pd.read_csv('data/backtest_results/cdn_equity_curve.csv', index_col=0, parse_dates=True).iloc[:,0].dropna()
rc = cdn.pct_change().dropna()
ny=len(rc)/252
tot=(1+rc).prod()-1
cagr=(1+tot)**(1/ny)-1
vol=rc.std()*np.sqrt(252)
dd=abs((cdn/cdn.cummax()-1).min())
print(f'CDN {cdn.index[0].date()} {cdn.index[-1].date()} CAGR {cagr:.4%} vol {vol:.4%} MaxDD {dd:.4%} Sharpe@2% {(cagr-0.02)/vol:.3f}')
print('daily win', float((rc>0).mean()), 'monthly win', float((rc.resample("ME").apply(lambda x:(1+x).prod()-1)>0).mean()))
PY
```

Live layout check (cold containers can be slow; this one returned in about 2 seconds):

```bash
curl -sS "https://etf-regime-strategist-322569756829.asia-east2.run.app/_dash-layout" -o /tmp/dash_layout.json
```

Search that JSON for `14.85%`, `12.21%`, `15.74%`, and `14.62%`.

---

## Fixes applied after this audit

Engine math is unchanged. Copy, limits, and the auditor status key changed:

1. Extra-month `regime.shift(1)` is **Execution / Timing Sensitivity**, not a production look-ahead warning. Look-ahead stays unlagged versus CPI+1mo / GDP+4mo.
2. `RISK_LIMITS.max_single_position` is `MAX_REGIME_WEIGHT` (IEF 35% in deflation). Goldilocks QQQ 30% is intentional AI-trend exposure and is not clipped to 25%. The auditor imports `RISK_LIMITS` (the old 25% fallback was a `NameError`).
3. `REGIME_VIX_DEFENSIVE` and `RISK_LIMITS.vix_spike_threshold` are **30**, the same threshold the classifiers already used. UI copy reads that constant.
4. CDN period labels use the equity-curve dates. ZQQ.TO is labeled CAD-hedged. The book still holds ZQQ, not ZNQ.
5. `CLAUDE.md` and `README.md` lead with v7 **14.85% / 13.90% / 1.03**. v5.1 **14.52% / 14.78% / 0.97** is marked historical.
6. The tax panel states its CAD CAGRs are the `ab_canadian_tax.py` study, not the USD production backtest.
7. Backtest tab and Portfolio CAGR card default to Auditor Lagged (**12.21% / 14.10% / 0.83**). Production **14.85%** stays on the Backtest control and in `20yr_comparison.csv`. CDN has no extra-month series; the US column on that tab follows the Backtest default.
