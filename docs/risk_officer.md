# Risk Officer · 结构旗 D / E / F

Notify only. Auditor **section 6**, after the sleeve-stress panel. These flags do not change Merrill `REGIME_WEIGHTS`, QQQ Vegas entry or size, or IBKR / Moomoo orders.

**通知 / 不改仓. NOTIFY-ONLY.**

The tactical flags A/B/C stay on the QQQ Vegas card. Section 6 shows D/E/F and a collapsed read-only copy of A/B/C. The bubble score is

`0.40·S(D) + 0.35·S(E) + 0.25·S(F)`

`S` is 1 when that flag's status is `on`, and 0 otherwise (off, skipped, or pending). There is no soft score.

A rising edge is OFF→ON only. The first time a flag id is stored in `data/notify_state.json` is a baseline, not an Issue. Sticky ON does not send again. Turning a flag off updates the state and does not send.

## D_capex

Universe on the template: MSFT, GOOGL, AMZN, META, TSM, NVDA, and a SpaceX column that stays blank. SpaceX is private. This repo does not commit an OFFICIAL SpaceX figure and does not commit an estimate in that cell.

`data/risk_flags/raw_capex_hyperscalers.csv` is a template:

| status | Meaning |
|---|---|
| `EXAMPLE` | Fake numbers so the columns are obvious. Never a live print. |
| `PENDING_EARNINGS` | Latest quarter is not closed. |
| `OFFICIAL` | Live row. Not in the committed template. |

Rules:

- Drop `EXAMPLE` before any math.
- If the latest remaining row is `PENDING_EARNINGS` **and any amount is filled**, inherit the previous D flag. Do not recompute (不抢跑).
- A **blank** trailing `PENDING_EARNINGS` row is the template placeholder. It inherits only when no live OFFICIAL rows are left. A real `capex_official.csv` is scored on its own, so that placeholder does not block a completed quarter.
- An OFFICIAL row is live only when all six public names are present, the SpaceX cell is blank, and `source_notes` say SpaceX is excluded or private. A SpaceX number on an OFFICIAL row is rejected.
- `total_musd` is the six-name sum when the cell is blank. A total that disagrees with the six names by more than 1 (or 1% of the sum) is rejected.

On the live totals, aligned to calendar quarters:

- `YoY% = (total_t / total_{t-4} − 1) × 100`
- `ΔYoY = YoY_t − YoY_{t-1}` in percentage points
- ON if `(ΔYoY ≤ −5 AND YoY < 15)` OR `(ΔYoY < 0 AND prior ΔYoY < 0 AND ΔYoY + prior ΔYoY ≤ −4)`

Refresh tries SEC EDGAR XBRL (`PaymentsToAcquirePropertyPlantAndEquipment`, and the productive-assets tag, plus IFRS tags for TSMC). A calendar quarter is written only when all six public names map to it (nearest quarter-end within 50 days). The cache is `data/risk_flags/capex_official.csv` and is gitignored. The four-name dashboard pulse in `src/strategist/edgar_capex.py` is unchanged.

Until that cache exists, D stays pending / off. A failed fetch keeps the previous flag.

## E_credit

ICE BofA US High Yield OAS, FRED `BAMLH0A0HYM2`, from the public `fredgraph.csv` feed (no API key on that URL). The series is in percent; ×100 is bps. A median above 50 is treated as already in bps.

Expanding z-score, `min_periods=252`, sample standard deviation. Missing z does not trigger the z leg and does not release.

- ON if spread ≥ 450 bps **or** z ≥ 2
- Stay ON until spread < 380 bps **and** z < 1
- The published flag is the **prior** observation

Cache: `data/risk_flags/credit_oas.csv` (gitignored). A failed download keeps the previous E flag.

## F_conc

Mag7 weight **inside SPY** only. Seven companies, eight lines: AAPL, MSFT, AMZN, NVDA, META, TSLA, GOOGL, and GOOG. A file missing any of those tickers is skipped (a partial basket would look less concentrated than it is).

- ON if the weight ≥ 32%
- Stay ON until the weight ≤ 29%
- The path walks the stored history and publishes the latest as-of weight. The holdings file is already a published basket, so there is no extra one-day lag.

Refresh tries the SSGA daily SPY holdings workbook. Weights above 1.5 are read as percent. Cache: `data/risk_flags/spy_mag7_weight.csv` (gitignored). A failed download keeps the previous F flag.

## Where it runs

| Path | Role |
|---|---|
| `src/risk_officer/capex_analyzer.py` | D formula, EXAMPLE / PENDING policy, optional EDGAR cache |
| `src/risk_officer/credit_analyzer.py` | E formula and FRED CSV |
| `src/risk_officer/concentration_analyzer.py` | F formula and SPY holdings parse |
| `src/dashboard/auditor.py` | `build_risk_officer_section` |
| `scripts/refresh_risk_flags.py` | Writes D/E/F onto `flags.json` after the Yahoo tactical scorecard |
| `scripts/notify_regime.py` | Rising edge. Body includes 不改仓 and NOTIFY-ONLY |

A Yahoo price failure does not rewrite `flags.json`, so the previous structural flags stay. That matches the tactical scorecard.

## Not in this pass

- No live OFFICIAL CapEx is committed. TSMC's IFRS tag may not map; D stays pending until six public names share a quarter.
- SpaceX stays blank. No estimate is written into the cell.
- E and F stay skipped in git until a refresh actually downloads OAS and SPY holdings.
- Nothing here is deployed to Cloud Run by this change. `/tasks/refresh` picks it up on the next deploy.
