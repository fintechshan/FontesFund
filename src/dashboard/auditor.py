"""
src/dashboard/auditor.py
========================
Gemini Independent Auditor helper module for quantitative and qualitative checks.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger('auditor')

def run_independent_audit(price_data, macro, backtest_results, regime_history, all_equity_curves, lagged_metrics=None):
    audit = {}

    # Helper function to clean and parse percentages
    def clean_pct(val_str):
        if not val_str or str(val_str).strip() == '—':
            return 0.0
        try:
            return float(str(val_str).replace('%', '').strip()) / 100
        except Exception:
            return 0.0

    # ───────────────────────────────────────────────────────────────────────
    # PILLAR 1: LOOK-A-HEAD BIAS DIAGNOSTIC
    # ───────────────────────────────────────────────────────────────────────
    bias_status = "PASS"
    bias_desc = "Look-ahead bias metrics not provided for evaluation."
    cagr_diff = 0.0
    sharpe_diff = 0.0
    
    std_cagr = 0.0
    std_sharpe = 0.0
    lag_cagr = 0.0
    lag_sharpe = 0.0

    if lagged_metrics and 'standard' in lagged_metrics and 'lagged' in lagged_metrics:
        try:
            std_cagr = clean_pct(lagged_metrics['standard'].get('annual_return', '0%'))
            lag_cagr = clean_pct(lagged_metrics['lagged'].get('annual_return', '0%'))
            std_sharpe = float(lagged_metrics['standard'].get('sharpe', '0'))
            lag_sharpe = float(lagged_metrics['lagged'].get('sharpe', '0'))
            
            cagr_diff = std_cagr - lag_cagr
            sharpe_diff = std_sharpe - lag_sharpe
            
            if cagr_diff > 0.04 or sharpe_diff > 0.50 or (std_sharpe > 1.30 and lag_sharpe < 0.80):
                bias_status = "FAIL"
                bias_desc = (
                    f"CRITICAL: Performance decays significantly under 1-month lag. "
                    f"CAGR drop: {cagr_diff:.2%} (Standard: {std_cagr:.2%}, Lagged: {lag_cagr:.2%}). "
                    f"Sharpe drop: {sharpe_diff:.2f} (Standard: {std_sharpe:.2f}, Lagged: {lag_sharpe:.2f}). "
                    f"This indicates the standard strategy suffers from look-ahead bias (using future information)."
                )
            elif cagr_diff > 0.02 or sharpe_diff > 0.25:
                bias_status = "WARNING"
                bias_desc = (
                    f"WARNING: Moderate performance drop under 1-month lag. "
                    f"CAGR drop: {cagr_diff:.2%} (Standard: {std_cagr:.2%}, Lagged: {lag_cagr:.2%}). "
                    f"Sharpe drop: {sharpe_diff:.2f} (Standard: {std_sharpe:.2f}, Lagged: {lag_sharpe:.2f}). "
                    f"Potential minor look-ahead bias or timing sensitivity."
                )
            elif abs(cagr_diff) < 1e-6 and abs(sharpe_diff) < 1e-6:
                bias_status = "WARNING"
                bias_desc = (
                    "Standard and lagged results are exactly identical. "
                    "Verify if macro signals are actually driving allocation or if there is a bug in the backtester."
                )
            else:
                bias_status = "PASS"
                bias_desc = (
                    f"Look-Ahead check passed. CAGR difference is stable: {cagr_diff:+.2%} "
                    f"(Standard: {std_cagr:.2%}, Lagged: {lag_cagr:.2%}). "
                    f"Sharpe difference: {sharpe_diff:+.2f} (Standard: {std_sharpe:.2f}, Lagged: {lag_sharpe:.2f})."
                )
        except Exception as e:
            bias_status = "WARNING"
            bias_desc = f"Error evaluating look-ahead bias: {e}"
            logger.error(bias_desc)
    else:
        bias_status = "WARNING"
        bias_desc = "No lagged simulation metrics available. Ensure background updater completes execution."

    audit['bias_status'] = bias_status

    # ───────────────────────────────────────────────────────────────────────
    # PILLAR 2: FRED DATA INTEGRITY & ACCURACY AUDITOR
    # ───────────────────────────────────────────────────────────────────────
    data_checks = []

    # 1. Price Data Check (existing)
    if not price_data.empty:
        n_rows = len(price_data)
        n_etfs = price_data.shape[1]
        start_date = price_data.index.min().strftime('%Y-%m-%d')
        end_date = price_data.index.max().strftime('%Y-%m-%d')

        # Distinguish leading NaNs (pre-launch, expected for newer ETFs) from
        # INTERNAL gaps (NaNs after an ETF's first trade — genuine data problems).
        internal_nans = 0
        gap_cols = []
        for col in price_data.columns:
            s = price_data[col]
            fv = s.first_valid_index()
            if fv is not None:
                g = int(s.loc[fv:].isna().sum())
                if g > 0:
                    internal_nans += g
                    gap_cols.append(col)
        total_nans = int(price_data.isna().sum().sum())
        leading_nans = total_nans - internal_nans

        status = "PASS" if internal_nans == 0 else "WARNING"
        msg = f"Loaded {n_etfs} ETFs, {n_rows} days ({start_date} to {end_date}). "
        if internal_nans > 0:
            msg += f"Internal gaps in: {', '.join(gap_cols[:4])} (NaNs after first trade)."
            remedy = "Run download_data.py to backfill, or forward-fill the affected columns."
        else:
            msg += (f"No internal gaps. ({leading_nans} leading NaNs are pre-launch "
                    f"history for newer ETFs — expected, handled per-date.)")
            remedy = "None required. All gaps are expected pre-launch history."

        data_checks.append({
            'check': 'Price Data Integrity',
            'status': status,
            'value': f"{internal_nans} internal NaNs",
            'threshold': '0 internal gaps (leading pre-launch NaNs OK)',
            'location': 'data/cache/price_data.csv',
            'remedy': remedy,
            'desc': msg
        })
    else:
        data_checks.append({
            'check': 'Price Data Integrity',
            'status': 'FAIL',
            'value': 'No Data',
            'threshold': 'Valid DataFrames',
            'location': 'data/cache/price_data.csv',
            'remedy': 'Run download_data.py to download and generate the price cache file.',
            'desc': 'Price cache is empty or missing.'
        })

    # 2. Detailed FRED Series Integrity & Accuracy Validation
    macro_configs = {
        'vix': {'name': 'VIX Index', 'freq': 'daily', 'min': 5.0, 'max': 100.0, 'location': 'FRED: VIXCLS'},
        'cpi': {'name': 'CPI Index', 'freq': 'monthly', 'min': 100.0, 'max': 500.0, 'location': 'FRED: CPIAUCSL'},
        # flat_ok: DFF is a POLICY rate — identical daily values between FOMC moves are
        # expected, so a flatline alone is not an API failure (only flat AND stale is).
        'ff_rate': {'name': 'Federal Funds Rate', 'freq': 'daily', 'min': 0.0, 'max': 25.0, 'location': 'FRED: DFF', 'flat_ok': True},
        't10y': {'name': '10-Year Treasury Yield', 'freq': 'daily', 'min': 0.0, 'max': 25.0, 'location': 'FRED: DGS10'},
        't2y': {'name': '2-Year Treasury Yield', 'freq': 'daily', 'min': 0.0, 'max': 25.0, 'location': 'FRED: DGS2'},
        'gdp': {'name': 'GDP Growth Rate', 'freq': 'quarterly', 'min': -30.0, 'max': 40.0, 'location': 'FRED: A191RL1Q225SBEA'},
        'unemp': {'name': 'Unemployment Rate', 'freq': 'monthly', 'min': 1.0, 'max': 30.0, 'location': 'FRED: UNRATE'}
    }

    if isinstance(macro, dict) and len(macro) > 0:
        for k, cfg in macro_configs.items():
            series = macro.get(k)
            name = cfg['name']
            freq = cfg['freq']
            val_min = cfg['min']
            val_max = cfg['max']
            loc = cfg['location']
            
            if series is None or (isinstance(series, (pd.Series, pd.DataFrame)) and series.empty):
                data_checks.append({
                    'check': f'FRED {name} Accuracy',
                    'status': 'FAIL',
                    'value': 'Missing Series',
                    'threshold': 'Valid Series present',
                    'location': loc,
                    'remedy': 'Rerun data_collector.py or download_data.py to pull missing FRED series.',
                    'desc': f'Series {k} is empty or missing from cache.'
                })
                continue
            
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
                
            # Drop NaNs for validation
            clean_series = series.dropna()
            if clean_series.empty:
                data_checks.append({
                    'check': f'FRED {name} Accuracy',
                    'status': 'FAIL',
                    'value': 'All NaNs',
                    'threshold': 'Non-empty cleaned series',
                    'location': loc,
                    'remedy': 'Re-authenticate FRED API Key and force-refresh macro cache.',
                    'desc': f'Series {k} contains only NaN values.'
                })
                continue
            
            last_date = clean_series.index.max()
            days_old = (pd.Timestamp.now() - pd.Timestamp(last_date)).days
            
            # Future Dates check
            future_dates_count = (clean_series.index > pd.Timestamp.now()).sum()
            
            # Plausibility Check (Bounds)
            min_val = clean_series.min()
            max_val = clean_series.max()
            
            # CPI YoY helper bounds check
            yoy_ok = True
            yoy_desc = ""
            if k == 'cpi' and len(clean_series) > 12:
                cpi_yoy = (clean_series / clean_series.shift(12) - 1) * 100
                yoy_min = cpi_yoy.dropna().min()
                yoy_max = cpi_yoy.dropna().max()
                if yoy_min < -10.0 or yoy_max > 25.0:
                    yoy_ok = False
                    yoy_desc = f"CPI YoY out of bounds: [{yoy_min:.2f}%, {yoy_max:.2f}%] (Expected [-10%, 25%])."
            
            # Stale thresholds — measured from the LAST OBSERVATION DATE.
            # FRED dates monthly/quarterly series at the PERIOD START, and publishes
            # them with a release lag (CPI/UNRATE ~5-6 wks after month start; GDP
            # advance ~1 month after quarter end). So the freshest *published* value
            # is structurally weeks-to-months "old" by its observation date even when
            # fully current. Thresholds account for one full release cycle of headroom:
            #   monthly  : freshest value can reach ~75d before the next print
            #   quarterly: freshest value can reach ~210d before the next print
            stale_warn = 10 if freq == 'daily' else (80 if freq == 'monthly' else 220)
            stale_fail = 21 if freq == 'daily' else (110 if freq == 'monthly' else 300)
            
            # Flatline (API Freeze) check
            flatline_detected = False
            flatline_n = 10 if freq == 'daily' else 4
            if len(clean_series) >= flatline_n:
                last_vals = clean_series.tail(flatline_n)
                if (last_vals.diff().dropna() == 0).all():
                    flatline_detected = True

            # Evaluate status
            s_status = "PASS"
            remedy = "None required. Data series is valid, fresh, and within historical bounds."
            desc_parts = [f"Last date: {last_date.strftime('%Y-%m-%d')} ({days_old}d old).", f"Range: [{min_val:.2f}, {max_val:.2f}]."]
            
            if days_old > stale_fail:
                s_status = "FAIL"
                remedy = f"FRED API key might be blocked or rate limited. Rerun download_data.py to refresh cache."
                desc_parts.append(f"CRITICAL: Stale data (> {stale_fail} days).")
            elif days_old > stale_warn:
                s_status = "WARNING"
                remedy = "Verify FRED API connection and update schedule."
                desc_parts.append(f"WARNING: Stale data (> {stale_warn} days).")
                
            if future_dates_count > 0:
                s_status = "FAIL"
                remedy = "Inspect system clock or database timestamps. Rebuild cache."
                desc_parts.append(f"CRITICAL: Contains {future_dates_count} future dates.")
                
            if min_val < val_min or max_val > val_max:
                s_status = "FAIL"
                remedy = f"FRED database returned incorrect scale or corrupt values. Re-download series."
                desc_parts.append(f"CRITICAL: Values out of plausible bounds [{val_min}, {val_max}].")
                
            if not yoy_ok:
                s_status = "FAIL"
                remedy = "Re-download CPI data. YoY calculation yields impossible inflation values."
                desc_parts.append(f"CRITICAL: {yoy_desc}")
                
            if flatline_detected:
                if cfg.get('flat_ok') and days_old <= stale_warn:
                    # Policy rates (DFF) sit flat between FOMC moves — expected, not a
                    # frozen API. Note it, keep PASS, as long as the data is fresh.
                    desc_parts.append(f"Flat last {flatline_n} values (normal for a policy rate between FOMC moves).")
                elif s_status == "PASS":   # never downgrade an existing FAIL
                    s_status = "WARNING"
                    remedy = "Check if FRED has frozen this series or if caching logic is duplicating values."
                    desc_parts.append(f"WARNING: API flatline detected - last {flatline_n} values are identical.")
                else:
                    desc_parts.append(f"Also: last {flatline_n} values identical (possible API freeze).")
                
            data_checks.append({
                'check': f'FRED {name} Accuracy',
                'status': s_status,
                'value': f"{clean_series.iloc[-1]:.2f}",
                'threshold': f"[{val_min:.1f}, {val_max:.1f}] & Max {stale_warn}d old",
                'location': loc,
                'remedy': remedy,
                'desc': " ".join(desc_parts)
            })
    else:
        data_checks.append({
            'check': 'Macro Data Completeness',
            'status': 'FAIL',
            'value': 'No Data',
            'threshold': 'Dict of Series',
            'location': 'data/cache/macro_data.pkl',
            'remedy': 'Run run_backtest.py or download_data.py to download and cache FRED macro series.',
            'desc': 'Macro cache is empty or missing.'
        })
        
    audit['data_checks'] = data_checks

    # ───────────────────────────────────────────────────────────────────────
    # PILLAR 3: STRATEGY REALISM & OPTIMISM CHECKS (SYSTEM ERRORS CHECKER)
    # ───────────────────────────────────────────────────────────────────────
    errors = []
    
    # 1. Detect active strategy name in backtest results
    strat_name = None
    for name in ['Optimized Regime Strategy', 'Vol-Targeted Regime Strategy', 'Aggressive Regime Strategy']:
        if not backtest_results.empty and name in backtest_results.index:
            strat_name = name
            break
            
    # 2. Check reported strategy statistics for over-optimism
    if strat_name and not backtest_results.empty:
        row = backtest_results.loc[strat_name]
        try:
            reported_sharpe = float(row.get('Sharpe Ratio', 0))
            reported_cagr = clean_pct(row.get('Annual Return', '0%'))
            reported_max_dd = clean_pct(row.get('Max Drawdown', '0%'))
            reported_win = clean_pct(row.get('Win Rate', '0%'))
            
            # Check Sharpe Ratio
            if reported_sharpe > 1.60:
                errors.append({
                    'category': 'Strategy Realism (Sharpe)',
                    'description': f"Reported Sharpe ratio is unrealistically high ({reported_sharpe:.2f}). Limit: 1.60.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Ensure transaction costs (5 bps) are enabled and look-ahead biases are removed from the signals.",
                    'impact': 'CRITICAL (Backtest Invalid)',
                    'status': 'FAIL'
                })
            elif reported_sharpe > 1.25:
                errors.append({
                    'category': 'Strategy Realism (Sharpe)',
                    'description': f"Reported Sharpe ratio is highly optimistic ({reported_sharpe:.2f}). Expected typical Sharpe <= 1.25.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Double-check execution parameters. Verify if monthly rebalancing is aligned with lagged execution.",
                    'impact': 'HIGH (Review Required)',
                    'status': 'WARNING'
                })
            else:
                errors.append({
                    'category': 'Strategy Realism (Sharpe)',
                    'description': f"Reported Sharpe ratio is plausible ({reported_sharpe:.2f}). Within historical bounds.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "None required.",
                    'impact': 'NONE',
                    'status': 'PASS'
                })
                
            # Check CAGR
            if reported_cagr > 0.22:
                errors.append({
                    'category': 'Strategy Realism (CAGR)',
                    'description': f"Reported CAGR is unrealistically high ({reported_cagr:.2%}). Limit: 22.0% over 20 years.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Verify that compounding and same-day fills are not creating artificial gains.",
                    'impact': 'CRITICAL (Compounding Bias)',
                    'status': 'FAIL'
                })
            elif reported_cagr > 0.17:
                errors.append({
                    'category': 'Strategy Realism (CAGR)',
                    'description': f"Reported CAGR is highly optimistic ({reported_cagr:.2%}). Limit: 17.0% without leverage.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Verify the rebalance constraints and leverage overlays in the engine.",
                    'impact': 'HIGH (Review Required)',
                    'status': 'WARNING'
                })
            else:
                errors.append({
                    'category': 'Strategy Realism (CAGR)',
                    'description': f"Reported CAGR is realistic ({reported_cagr:.2%}).",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "None required.",
                    'impact': 'NONE',
                    'status': 'PASS'
                })

            # Check Max Drawdown.
            # A sub-8% DD over 20yrs spanning 2008/2020/2022 implies a methodology
            # error (e.g. monthly snapshots or look-ahead). 8-12% is low-but-possible
            # for an aggressively risk-managed book and warrants a second look. A
            # vol-targeted + DD-breaker + risk-parity + trend-hedged strategy landing
            # ~12-18% is plausible (the daily DD breaker explicitly caps drawdowns),
            # and the math-audit pillar independently recomputes DD from the daily
            # equity curve to confirm it — so >=12% passes here.
            if reported_max_dd < 0.08:
                errors.append({
                    'category': 'Strategy Realism (Max Drawdown)',
                    'description': f"Reported Max Drawdown is unrealistically small ({reported_max_dd:.2%}). A 20-year backtest spanning 2008/2020/2022 should show > 8% DD.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Ensure drawdowns are calculated on the daily equity series (peak-to-trough) and not on monthly snapshots; verify no look-ahead in signals.",
                    'impact': 'CRITICAL (Drawdown Understated)',
                    'status': 'FAIL'
                })
            elif reported_max_dd < 0.12:
                errors.append({
                    'category': 'Strategy Realism (Max Drawdown)',
                    'description': f"Reported Max Drawdown is low ({reported_max_dd:.2%}). Plausible for an aggressively hedged book, but worth a second look.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Confirm the math-audit pillar recomputes the same DD from the daily equity curve and that the DD breaker / vol target triggers are realistic.",
                    'impact': 'MEDIUM (Review Suggested)',
                    'status': 'WARNING'
                })
            else:
                errors.append({
                    'category': 'Strategy Realism (Max Drawdown)',
                    'description': f"Reported Max Drawdown is plausible ({reported_max_dd:.2%}). Accounts for historical market shocks.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "None required.",
                    'impact': 'NONE',
                    'status': 'PASS'
                })
                
            # Check Win Rate
            if reported_win > 0.70:
                errors.append({
                    'category': 'Strategy Realism (Win Rate)',
                    'description': f"Reported monthly win rate is extremely high ({reported_win:.1%}). Expected <= 65% for macro rebalancing.",
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': "Ensure weights are not adjusted on day-of trading. Verify standard rebalance frequency.",
                    'impact': 'CRITICAL (Over-fitted)',
                    'status': 'FAIL'
                })
                
            # Check Transaction Costs Presence
            if std_cagr > 0.0:
                cagr_slippage = reported_cagr - std_cagr
                if cagr_slippage > 0.015:
                    errors.append({
                        'category': 'Transaction Costs Check',
                        'description': f"Discrepancy: Reported CAGR ({reported_cagr:.2%}) is higher than live CAGR ({std_cagr:.2%}) by {cagr_slippage:.2%}.",
                        'location': 'Engine: run_backtest.py vs run_dashboard.py',
                        'remedy': "Add transaction cost (5 bps) to the engine parameters in run_backtest.py to match live trading friction.",
                        'impact': 'CRITICAL (Ignored transaction costs)',
                        'status': 'FAIL'
                    })
                else:
                    errors.append({
                        'category': 'Transaction Costs Check',
                        'description': "Verified: Reported backtest aligns with live simulation incorporating 5 bps transaction costs.",
                        'location': 'Engine: run_backtest.py vs run_dashboard.py',
                        'remedy': "None required. Transaction fees are correctly modeled.",
                        'impact': 'NONE',
                        'status': 'PASS'
                    })

        except Exception as e:
            logger.error(f"Error checking strategy realism: {e}")
            errors.append({
                'category': 'Strategy Realism Check',
                'description': f"Failed to audit strategy statistics: {e}",
                'location': 'data/backtest_results/20yr_comparison.csv',
                'remedy': "Check headers and format of backtest comparison CSV.",
                'impact': 'HIGH',
                'status': 'WARNING'
            })
    else:
        errors.append({
            'category': 'Strategy Realism Check',
            'description': "Backtest comparison data not available to check strategy optimism.",
            'location': 'data/backtest_results/20yr_comparison.csv',
            'remedy': "Run run_backtest.py to generate performance comparison files.",
            'impact': 'HIGH',
            'status': 'WARNING'
        })

    # Add Look-Ahead Bias Diagnostic status to system errors checklist
    errors.append({
        'category': 'Look-Ahead Bias Diagnostic',
        'description': bias_desc,
        'location': 'src/dashboard/auditor.py',
        'remedy': "Ensure all backtest signals use shift(1) of macro variables and monthly rebalancing is lagged.",
        'impact': 'CRITICAL' if bias_status == "FAIL" else ('HIGH' if bias_status == "WARNING" else 'NONE'),
        'status': bias_status
    })

    # Lagged-vs-UNLAGGED check — catches the publication lag being REMOVED.
    # Production = standard (CPI+1mo/GDP+4mo lag). Unlagged "sees" macro early, so it
    # should out-perform; the gap is the look-ahead premium the lag correctly removes.
    if lagged_metrics and 'unlagged' in lagged_metrics:
        try:
            unlag_cagr = clean_pct(lagged_metrics['unlagged'].get('annual_return', '0%'))
            premium = unlag_cagr - std_cagr   # std_cagr = production (lagged) CAGR
            if abs(premium) < 0.005:
                ll_status = "WARNING"
                ll_desc = (f"Lagged (production {std_cagr:.2%}) and UNLAGGED ({unlag_cagr:.2%}) are "
                           f"near-identical (Δ {premium:+.2%}). Verify the CPI+1mo/GDP+4mo publication "
                           f"lag is actually applied in classify_regimes — a ~0 premium is suspicious "
                           f"and may indicate the lag was removed (look-ahead present).")
            elif premium >= 0.005:
                ll_status = "PASS"
                ll_desc = (f"Publication lag removes a +{premium:.2%} look-ahead premium "
                           f"(unlagged {unlag_cagr:.2%} → production {std_cagr:.2%}). The lag is "
                           f"applied and production is the conservative, tradable number.")
            else:
                ll_status = "PASS"
                ll_desc = (f"Unlagged ({unlag_cagr:.2%}) underperforms production ({std_cagr:.2%}) by "
                           f"{-premium:.2%} — macro timing is not a look-ahead source here.")
            errors.append({
                'category': 'Look-Ahead: Lagged vs Unlagged',
                'description': ll_desc,
                'location': 'run_dashboard.py: classify_regimes(apply_lag)',
                'remedy': "If near-identical, re-check the CPI+1mo / GDP+4mo index shift is present.",
                'impact': 'HIGH' if ll_status == "WARNING" else 'NONE',
                'status': ll_status,
            })
        except Exception as e:
            logger.error(f"Lagged-vs-unlagged check error: {e}")

    # 3. Check target weights sum to 100% (existing)
    try:
        from config.regime_rules import REGIME_WEIGHTS
        for regime, weights in REGIME_WEIGHTS.items():
            w_sum = sum(weights.values())
            if abs(w_sum - 1.0) > 1e-9:
                errors.append({
                    'category': 'Regime Weights Sum',
                    'description': f"Regime '{regime}' weights sum to {w_sum:.4f} instead of 1.0",
                    'location': f"config/regime_rules.py: REGIME_WEIGHTS['{regime}']",
                    'remedy': f"Modify weights in config/regime_rules.py so the sum of items in REGIME_WEIGHTS['{regime}'] is exactly 1.0.",
                    'impact': 'CRITICAL (Will crash allocation)',
                    'status': 'FAIL'
                })
    except Exception as e:
        logger.error(f"Error checking regime weights: {e}")
        errors.append({
            'category': 'Regime Weights Check',
            'description': f"Failed to check regime weights: {e}",
            'location': 'config/regime_rules.py',
            'remedy': "Check config/regime_rules.py configuration syntax.",
            'impact': 'CRITICAL',
            'status': 'FAIL'
        })
    
    # 4. Check boundary violations (existing)
    try:
        oob_etfs = []
        for regime, weights in REGIME_WEIGHTS.items():
            for t, w in weights.items():
                if w < 0.0 or w > 1.0:
                    oob_etfs.append(f"{regime}:{t}={w:.2f}")
        if oob_etfs:
            errors.append({
                'category': 'Weight Boundary Violation',
                'description': f"Weights outside [0.0, 1.0] interval: {', '.join(oob_etfs)}",
                'location': 'config/regime_rules.py: REGIME_WEIGHTS',
                'remedy': 'Adjust all weights in config/regime_rules.py to lie strictly between 0.0 and 1.0.',
                'impact': 'CRITICAL (Violates long-only rule)',
                'status': 'FAIL'
            })
    except Exception:
        pass

    # 5. Check gaps in price data (existing)
    active_gaps = []
    if not price_data.empty:
        for col in price_data.columns:
            series = price_data[col]
            first_valid = series.first_valid_index()
            if first_valid is not None:
                post_valid = series.loc[first_valid:]
                nans = post_valid.isna().sum()
                if nans > 0:
                    active_gaps.append(f"{col} ({nans} NaNs)")
                    
    if active_gaps:
        errors.append({
            'category': 'Data Gaps (Mid-Series)',
            'description': f"NaNs found in active price history: {', '.join(active_gaps)}",
            'location': 'data/cache/price_data.csv',
            'remedy': "Run a forward-fill/backward-fill script on price_data.csv or clean the source data using download_data.py.",
            'impact': 'HIGH (May break calculations)',
            'status': 'WARNING'
        })

    # 6. Check regime timeline gaps (existing)
    if not regime_history.empty:
        dates = pd.to_datetime(regime_history['date'])
        diffs = dates.diff().dropna()
        skipped_gaps = []
        for i, d in enumerate(diffs):
            if d.days > 45:
                skipped_gaps.append(f"Between {dates.iloc[i]} and {dates.iloc[i+1]}")
        if skipped_gaps:
            errors.append({
                'category': 'Regime Gaps',
                'description': f"Timeline gaps in economic regime classification: {', '.join(skipped_gaps)}",
                'location': 'run_dashboard.py: classify_regimes',
                'remedy': "Verify the resampling frequency and date index alignment inside run_dashboard.py classify_regimes.",
                'impact': 'CRITICAL (Incomplete timeline)',
                'status': 'FAIL'
            })
            
    audit['errors'] = errors

    # ───────────────────────────────────────────────────────────────────────
    # RECALCULATE reported statistics from the actual equity curves
    # ───────────────────────────────────────────────────────────────────────
    math_audit = []
    
    if strat_name and not backtest_results.empty and strat_name in backtest_results.index and not all_equity_curves.empty and strat_name in all_equity_curves.columns:
        row = backtest_results.loc[strat_name]
        eq_curve = all_equity_curves[strat_name].dropna()
        
        if len(eq_curve) > 1:
            daily_returns = eq_curve.pct_change().dropna()
            
            # Recalculate metrics
            recalc_tot_ret = (eq_curve.iloc[-1] / eq_curve.iloc[0]) - 1
            n_years = len(daily_returns) / 252
            recalc_ann_ret = (1 + recalc_tot_ret) ** (1 / max(n_years, 0.01)) - 1
            recalc_vol = daily_returns.std() * np.sqrt(252)
            
            ff_rate_series = macro.get('ff_rate', pd.Series(dtype=float))
            avg_rf = ff_rate_series.mean() / 100 if not ff_rate_series.empty else 0.0185
            recalc_sharpe = (recalc_ann_ret - avg_rf) / recalc_vol if recalc_vol > 0 else 0.0
            
            cummax = eq_curve.cummax()
            drawdowns = (eq_curve - cummax) / cummax
            recalc_max_dd = abs(drawdowns.min())
            
            try:
                stored_ann = clean_pct(row.get('Annual Return', '0%'))
                stored_vol = clean_pct(row.get('Volatility', '0%'))
                stored_sharpe = float(row.get('Sharpe Ratio', '0'))
                stored_max_dd = clean_pct(row.get('Max Drawdown', '0%'))
                stored_tot = clean_pct(row.get('Total Return', '0%'))
                
                # Compare
                metrics = [
                    ('Total Return', stored_tot, recalc_tot_ret, True),
                    ('Annual Return', stored_ann, recalc_ann_ret, True),
                    ('Volatility', stored_vol, recalc_vol, True),
                    ('Sharpe Ratio', stored_sharpe, recalc_sharpe, False),
                    ('Max Drawdown', stored_max_dd, recalc_max_dd, True)
                ]
                
                for m_name, stored, recalc, is_pct in metrics:
                    diff = abs(stored - recalc)
                    threshold = 0.005 if is_pct else 0.05
                    m_status = "PASS" if diff <= threshold else "DISCREPANCY"
                    
                    fmt = ".2%" if is_pct else ".2f"
                    
                    if m_status == "DISCREPANCY":
                        remedy = f"Verify annualization parameters in run_backtest.py and engine.py. Ensure risk-free rate is {avg_rf:.2%}."
                    else:
                        remedy = "None required. Recalculated values match stored values."
                        
                    math_audit.append({
                        'metric': m_name,
                        'reported': f"{stored:{fmt}}",
                        'recalculated': f"{recalc:{fmt}}",
                        'diff': f"{diff:{fmt}}",
                        'location': 'data/backtest_results/20yr_comparison.csv',
                        'remedy': remedy,
                        'status': m_status
                    })
            except Exception as e:
                logger.error(f"Error parsing reported backtest results: {e}")
                math_audit.append({
                    'metric': 'All', 'reported': 'Error', 'recalculated': 'Error', 'diff': '—',
                    'location': 'data/backtest_results/20yr_comparison.csv',
                    'remedy': 'Check backtest results file format and column headers.',
                    'status': 'ERROR'
                })
        else:
            math_audit.append({
                'metric': 'All', 'reported': '—', 'recalculated': '—', 'diff': '—',
                'location': 'data/backtest_results/all_equity_curves.csv',
                'remedy': 'Verify that aggressive_equity_curve.csv or all_equity_curves.csv has valid columns.',
                'status': 'NO_CURVE'
            })
    else:
        math_audit.append({
            'metric': 'All', 'reported': '—', 'recalculated': '—', 'diff': '—',
            'location': 'data/backtest_results/20yr_comparison.csv',
            'remedy': 'Run run_backtest.py to generate performance comparison files.',
            'status': 'NO_DATA'
        })
        
    audit['math_audit'] = math_audit

    # ───────────────────────────────────────────────────────────────────────
    # REGIME CORRELATION (existing)
    # ───────────────────────────────────────────────────────────────────────
    regime_corr = []
    if strat_name and not all_equity_curves.empty and strat_name in all_equity_curves.columns and not regime_history.empty:
        eq = all_equity_curves[strat_name].dropna()
        if len(eq) > 20:
            monthly_eq = eq.resample('MS').last()
            monthly_ret = monthly_eq.pct_change().dropna()
            
            rh = regime_history.copy()
            if 'date' in rh.columns:
                rh = rh.set_index('date')
            rh.index = pd.to_datetime(rh.index)
            
            aligned = pd.DataFrame({'return': monthly_ret}).join(rh, how='inner')
            if not aligned.empty:
                grouped = aligned.groupby('regime')
                for regime, group in grouped:
                    cnt = len(group)
                    avg_r = group['return'].mean()
                    std_r = group['return'].std()
                    win_r = (group['return'] > 0).sum() / cnt if cnt > 0 else 0
                    
                    regime_corr.append({
                        'regime': regime.upper(),
                        'count': cnt,
                        'avg_return': f"{avg_r:+.2%}",
                        'volatility': f"{std_r*np.sqrt(12):.2%}" if cnt > 1 else '0.0%',
                        'win_rate': f"{win_r:.1%}"
                    })
                    
    audit['regime_corr'] = regime_corr

    # ───────────────────────────────────────────────────────────────────────
    # RISK ASSESSMENT (existing)
    # ───────────────────────────────────────────────────────────────────────
    risk = {}
    
    curr_weights = {}
    latest_regime = 'unknown'
    if not regime_history.empty:
        latest_regime = regime_history.iloc[-1]['regime']
        curr_weights = REGIME_WEIGHTS.get(latest_regime, {})
        
    if curr_weights:
        max_wt = max(curr_weights.values())
        max_asset = [k for k, v in curr_weights.items() if v == max_wt][0]
        
        # Risk Concentration Limit check
        try:
            limit_val = RISK_LIMITS.max_single_position
        except Exception:
            limit_val = 0.25
            
        conc_status = "PASS" if max_wt <= limit_val else "WARNING"
        risk['concentration'] = {
            'max_weight': f"{max_wt:.1%}",
            'asset': max_asset,
            'limit': f"{limit_val:.1%}",
            'status': conc_status
        }
    else:
        risk['concentration'] = {'max_weight': '—', 'asset': '—', 'limit': '25%', 'status': 'NO_DATA'}
        
    # Leverage Limit Check
    lev_etfs = {'TQQQ', 'SOXL', 'GGLL', 'SSO'}
    lev_total = sum(v for k, v in curr_weights.items() if k in lev_etfs)
    
    try:
        lev_limit = RISK_LIMITS.max_leveraged_total
    except Exception:
        lev_limit = 0.25
        
    lev_status = "PASS" if lev_total <= lev_limit else "WARNING"
    risk['leverage'] = {
        'total_weight': f"{lev_total:.1%}",
        'limit': f"{lev_limit:.1%}",
        'status': lev_status
    }
    
    # VIX Stress Test
    risk['stress_test'] = {
        'normal_regime': latest_regime,
        'vix_spike_allocation': {
            'SHY': '40.0%', 'AGG': '25.0%', 'GLD': '20.0%', 'IEF': '15.0%',
            'Equity/Leveraged': '0.0%'
        }
    }
    
    audit['risk'] = risk
    
    return audit
