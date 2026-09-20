"""
ab_covered_call.py — PLANNING ONLY. Estimate a covered-call (buy-write) overlay on
the v7 7-ETF holdings and emit a JSON for the dashboard's read-only estimator panel.

v7 Universe: QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO
(TLT replaced by IEF; URA replaced by AIPO; SPYI removed — not a separate sleeve)

Premium is driven by volatility: ATM 1-month call premium ~0.1152*vol (Black-Scholes,
zero-rate approx). Empirically an ATM monthly buy-write distributes ~0.55*vol/yr;
a ~0.30-delta / ~5%-OTM write ~0.30*vol/yr (less income, keeps more upside).

HONEST FRAMING: premium is INCOME, not extra total return -- it sells upside for cash.
On the AI-growth sleeves (QQQ/SOXX/AIPO) that caps the very upside the strategy exists
to capture, so net total return DROPS in bull markets.
Best use: modest OTM writes on the liquid income/defensive sleeves (SPY/IEF/GLD).
DBMF options are typically illiquid -- excluded from the recommended overlay.
"""
import json
from datetime import datetime
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
px_path = ROOT / 'data' / 'cache' / 'price_data.csv'
px = pd.read_csv(px_path, index_col=0, parse_dates=True).ffill()

# v7 portfolio -- goldilocks regime weights (reference regime, ~70% of time)
W = {
    'QQQ':  0.30,
    'SOXX': 0.20,
    'SPY':  0.25,
    'IEF':  0.08,
    'GLD':  0.10,
    'DBMF': 0.04,
    'AIPO': 0.03,
}

ROLE = {
    'QQQ':  'growth',
    'SOXX': 'growth',
    'AIPO': 'growth',
    'SPY':  'income',
    'IEF':  'defensive',
    'GLD':  'income',
    'DBMF': 'defensive-illiquid',
}

VERDICT = {
    'growth':             'POOR -- caps the AI/growth upside the strategy targets',
    'income':             'OK -- income sleeve, modest OTM write reasonable',
    'defensive':          'OK -- defensive sleeve, OTM premium cushions drawdown',
    'defensive-illiquid': 'SKIP -- illiquid options market; not worth execution risk',
}

rows = []
for t, w in sorted(W.items(), key=lambda x: -x[1]):
    if t not in px.columns:
        print(f"WARNING: {t} not in price data -- skipping")
        continue
    vol = px[t].pct_change().dropna().tail(252).std() * np.sqrt(252)
    role = ROLE[t]
    rows.append({
        'ticker':  t,
        'weight':  w,
        'vol':     float(vol),
        'atm_mo':  float(0.1152 * vol),
        'atm_ann': float(0.55 * vol),
        'otm_ann': float(0.30 * vol),
        'role':    role,
        'verdict': VERDICT[role],
    })

# Portfolio-level income estimates
atm_all = sum(r['weight'] * r['atm_ann'] for r in rows)
otm_all = sum(r['weight'] * r['otm_ann'] for r in rows)
# Recommended overlay: SPY + IEF + GLD only (liquid options, income/defensive role)
otm_inc = sum(r['weight'] * r['otm_ann'] for r in rows
              if r['role'] in ('income', 'defensive'))

metrics = [
    {'metric': 'Premium yield (annualized)',     'target': 'gross premium collected / NAV',      'why': 'income the overlay generates'},
    {'metric': 'Net distribution yield',         'target': 'after buybacks & costs',             'why': 'what actually reaches you'},
    {'metric': 'Upside capture ratio',           'target': '>= 70% (OTM strikes)',               'why': 'how much rally you keep'},
    {'metric': 'Downside capture ratio',         'target': '< 100% (premium cushion)',           'why': 'drawdown softening from premium'},
    {'metric': 'Net total return vs underlying', 'target': '>= buy-hold in flat/choppy markets', 'why': 'THE bottom line -- income != return'},
    {'metric': 'Volatility reduction',           'target': '15-30% lower than underlying',       'why': 'main risk benefit'},
    {'metric': 'Strike moneyness / delta',       'target': '~0.30D (~5% OTM)',                   'why': 'income vs upside-retention knob'},
    {'metric': 'Days to expiry (DTE)',           'target': '30 days, monthly roll',              'why': 'best theta/gamma balance'},
    {'metric': 'Assignment frequency',           'target': '< 30% of months called away',        'why': 'turnover & tax drag'},
    {'metric': 'Foregone upside ($)',            'target': 'track cumulative',                   'why': 'real hidden cost in bull markets'},
]

study = {
    'as_of': datetime.now().strftime('%Y-%m-%d'),
    'model': ('ATM 1-mo premium ~0.1152*vol; ATM annual income ~0.55*vol; '
              'OTM (~0.30-delta) ~0.30*vol. vol = trailing-1y realized. v7 7-ETF portfolio.'),
    'per_etf': rows,
    'portfolio': {
        'atm_all':         float(atm_all),
        'otm_all':         float(otm_all),
        'otm_income_only': float(otm_inc),
    },
    'metrics': metrics,
    'recommendation': (
        'Do NOT write calls on QQQ/SOXX/AIPO -- that caps the AI/tech/infrastructure '
        'upside the strategy is built to capture; foregone 2023-2026 gains would have '
        'far exceeded the premium. DBMF options are illiquid -- skip. '
        'A modest ~0.30-delta / 30-DTE write on the liquid income+defensive sleeves '
        '(SPY/GLD/IEF) could add ~%.1f%%/yr of cleaner income with limited upside cost '
        '-- but lowers total return in bull markets and is income, not free alpha. '
        'Execution: ibkr_covered_calls.py (WRITE_ON: SPY 3%%, GLD 5%%, IEF 2%% OTM).' % (otm_inc * 100)
    ),
    'caveats': (
        'Estimates from realized vol + Black-Scholes ATM approximation (implied vol '
        'is usually 10-20%% higher -- actual premiums may exceed these figures). '
        'Net total return of buy-write indices (XYLD/BXM) historically runs ~1-3%%/yr '
        'BELOW buy-hold with ~25-30%% less vol. IEF options carry lower premium than '
        'TLT due to shorter duration / lower vol (~6.7%% vs ~14.5%%). '
        'Informational only, not investment advice.'
    ),
}

out_path = ROOT / 'data' / 'cache' / 'covered_call_study.json'
json.dump(study, open(out_path, 'w'), indent=2)

print('v7 per-ETF covered-call income (ATM / OTM):')
for r in rows:
    print(f"  {r['ticker']:5s}  wt={r['weight']:.0%}  vol={r['vol']:5.1%} | "
          f"ATM {r['atm_ann']:5.1%} | OTM {r['otm_ann']:5.1%} | {r['role']}")
print(f"\nPortfolio gross income: ATM-all ~{atm_all:.1%} | OTM-all ~{otm_all:.1%} | "
      f"OTM income/defensive-only ~{otm_inc:.1%}")
print(f"Wrote {out_path}")

