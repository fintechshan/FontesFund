"""A / B / C clocks on one price file, plus history coverage.

Does not change ETF weights and does not shorten CPI+1 or GDP+4.

  A  revised CPI/GDP, fixed CPI+1 / GDP+4, same-month VIX and SPY momentum
  B  same publication lag, but those two market series lagged one month
  C  first-release CPI and GDP on real release dates (no extra +1/+4)

B's market lag is ``market_signals(..., same_month=False)``, which matches
``resample('MS').shift(1)`` at each month-start. CPI and GDP are not shifted
a second time.

CPIAUCNS (not seasonally adjusted) is reported only when FRED_API_KEY is set
and ``get_series_all_releases('CPIAUCNS')`` succeeds. Without a key, C uses
the Philadelphia Fed PCPI vintage (seasonally adjusted family) and the NSA
row is marked not_run.

Usage:
    python scripts/ab_vintage.py

Writes:
    data/backtest_results/lag_honesty.csv
    data/backtest_results/coverage_windows.csv
    data/backtest_results/vintage_publication_lags.csv
    data/cache/vintage_cpi_yoy.csv
    data/cache/vintage_gdp_yoy.csv
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ab_vintage")

SLEEVE = ("QQQ", "SOXX", "SPY", "IEF", "GLD", "DBMF", "AIPO")


def _load():
    price = pd.read_csv(ROOT / "data" / "cache" / "price_data.csv", index_col=0, parse_dates=True)
    price = price.ffill()
    macro_path = ROOT / "data" / "cache" / "macro_data.pkl"
    if not macro_path.exists():
        raise SystemExit(f"Missing {macro_path}.")
    import pickle
    with open(macro_path, "rb") as fh:
        macro = pickle.load(fh)
    return price, macro


def _weights(price):
    from config.regime_rules import REGIME_WEIGHTS
    available = set(price.columns)
    out = {}
    for name, raw in REGIME_WEIGHTS.items():
        filtered = {k: v for k, v in raw.items() if k in available}
        total = sum(filtered.values())
        out[name] = {k: v / total for k, v in filtered.items()} if total else {}
    return out


def _rf(macro, price) -> float:
    ff = macro.get("ff_rate", pd.Series(dtype=float))
    if ff is None or len(ff) == 0:
        return 0.02
    ff = ff.copy()
    ff.index = pd.to_datetime(ff.index)
    ff = ff.loc[str(price.index.min().date()):]
    return float(ff.mean() / 100.0) if len(ff) else 0.02


def _row(mode, res, **extra) -> dict:
    return {
        "mode": mode,
        "cagr": res.annual_return,
        "max_dd": res.max_drawdown,
        "sharpe": res.sharpe_ratio,
        "volatility": res.volatility,
        "sortino": res.sortino_ratio,
        "calmar": res.calmar_ratio,
        "total_return": res.total_return,
        "start": res.start_date,
        "end": res.end_date,
        **extra,
    }


def _coverage(price: pd.DataFrame) -> pd.DataFrame:
    n = len(price)
    rows = []
    for ticker in SLEEVE:
        if ticker not in price.columns:
            rows.append({"ticker": ticker, "first_date": "", "sessions": 0, "coverage": 0.0, "missing": 1.0})
            continue
        s = price[ticker].dropna()
        sessions = int(len(s))
        rows.append({
            "ticker": ticker,
            "first_date": str(s.index.min().date()) if sessions else "",
            "sessions": sessions,
            "coverage": sessions / n if n else 0.0,
            "missing": 1.0 - (sessions / n if n else 0.0),
        })
    return pd.DataFrame(rows)


def _philly_lags() -> pd.DataFrame | None:
    from src.backtester.regime_clock import (
        PHILLY_CPI_FILE,
        PHILLY_DIR,
        PHILLY_GDP_FILE,
        publication_lag_days,
        releases_from_philly_sheet,
        summarize_lags,
    )
    cpi_path = PHILLY_DIR / PHILLY_CPI_FILE
    gdp_path = PHILLY_DIR / PHILLY_GDP_FILE
    alt_cpi = Path("/tmp/philly") / PHILLY_CPI_FILE
    alt_gdp = Path("/tmp/philly") / PHILLY_GDP_FILE
    if not cpi_path.exists() and alt_cpi.exists():
        cpi_path = alt_cpi
    if not gdp_path.exists() and alt_gdp.exists():
        gdp_path = alt_gdp
    if not cpi_path.exists() or not gdp_path.exists():
        logger.warning("No Philly workbooks on disk. Publication-lag table skipped.")
        return None
    cpi = pd.read_excel(cpi_path, sheet_name=0, header=0)
    gdp = pd.read_excel(gdp_path, sheet_name=0, header=0)
    rows = []
    for name, frame, quarterly in (
        ("PCPI", cpi, False),
        ("ROUTPUT", gdp, True),
    ):
        summary = summarize_lags(publication_lag_days(releases_from_philly_sheet(frame), quarterly))
        rows.append({"series": name, "source": "philadelphia_fed_rtdsm_midmonth", **summary})
    return pd.DataFrame(rows)


def main():
    from config.regime_rules import STRATEGY_PARAMS
    from src.backtester.engine import BacktestEngine
    from src.backtester.regime_clock import (
        MODE_LOOKAHEAD,
        MODE_TARGETED,
        MODE_VINTAGE,
        CPI_NSA_SERIES,
        classify_regimes,
        load_realtime_vintage,
    )

    price, macro = _load()
    weights = _weights(price)
    coverage = _coverage(price)
    logger.info("Sleeve coverage (share of the price index with a print):")
    logger.info("\n%s", coverage.to_string(index=False))

    present = [t for t in SLEEVE if t in price.columns and price[t].notna().any()]
    common_start = max(price[t].first_valid_index() for t in present)
    logger.info("Common inception (every listed sleeve name has a print): %s", common_start.date())

    vintage = load_realtime_vintage()
    nsa_payload = None
    if os.getenv("FRED_API_KEY", "").strip():
        try:
            from src.backtester.regime_clock import fetch_fredapi_vintage
            fresh = fetch_fredapi_vintage(os.environ["FRED_API_KEY"])
            if fresh.get("cpi_nsa_yoy_release") is not None and len(fresh["cpi_nsa_yoy_release"]) >= 24:
                nsa_payload = fresh
                vintage = fresh
        except Exception as exc:
            logger.warning("FRED vintage refresh failed: %s", exc)

    modes = {
        "A_lookahead": MODE_LOOKAHEAD,
        "B_targeted": MODE_TARGETED,
        "C_vintage_sa": MODE_VINTAGE,
    }
    histories = {}
    for label, mode in modes.items():
        hist, _, info = classify_regimes(
            macro, price, mode=mode,
            vintage=vintage if mode == MODE_VINTAGE else None,
        )
        if info.get("vintage_fallback"):
            logger.warning("%s fell back: %s", label, info.get("vintage_error"))
        histories[label] = (hist, info)

    if nsa_payload is not None:
        nsa_only = dict(nsa_payload)
        nsa_only["cpi_yoy_release"] = nsa_payload["cpi_nsa_yoy_release"]
        nsa_only["source"] = f"fredapi_first_release_{CPI_NSA_SERIES}"
        hist, _, info = classify_regimes(
            macro, price, mode=MODE_VINTAGE, vintage=nsa_only,
        )
        histories["C_vintage_nsa"] = (hist, info)
    else:
        logger.warning(
            "C_NSA not run. Set FRED_API_KEY so get_series_all_releases('%s') can build it. "
            "The SA vintage is Philadelphia Fed PCPI or the saved table.",
            CPI_NSA_SERIES,
        )

    engine = BacktestEngine(price, initial_capital=100_000, risk_free_rate=_rf(macro, price))
    vix = macro.get("vix")
    rows = []
    for label, (hist, info) in histories.items():
        logger.info("Backtesting %s ...", label)
        res = engine.run_optimized_regime_backtest(
            regime_history=hist,
            regime_weights=weights,
            name=label,
            vix_data=vix,
            **STRATEGY_PARAMS,
        )
        rows.append(_row(
            label, res,
            window="full_sample",
            vintage_source=info.get("vintage_source"),
            vintage_fallback=bool(info.get("vintage_fallback")),
            missing_etf_policy="renormalize_drop",
        ))
        logger.info(
            "%s  CAGR %.2f%%  MaxDD %.2f%%  Sharpe %.2f",
            label, 100 * res.annual_return, 100 * res.max_drawdown, res.sharpe_ratio,
        )

    sliced = price.loc[common_start:]
    hist_b, info_b = histories["B_targeted"]
    res_common = BacktestEngine(
        sliced, initial_capital=100_000, risk_free_rate=_rf(macro, sliced),
    ).run_optimized_regime_backtest(
        regime_history=hist_b,
        regime_weights=_weights(sliced),
        name="B_common_inception",
        vix_data=vix,
        **STRATEGY_PARAMS,
    )
    rows.append(_row(
        "B_targeted_common_inception", res_common,
        window="common_inception",
        vintage_source=None,
        vintage_fallback=False,
        missing_etf_policy="all_sleeve_names_listed",
    ))
    logger.info(
        "B common inception %s  CAGR %.2f%%  MaxDD %.2f%%  Sharpe %.2f",
        res_common.start_date, 100 * res_common.annual_return,
        100 * res_common.max_drawdown, res_common.sharpe_ratio,
    )

    out = pd.DataFrame(rows).set_index("mode")
    dest = ROOT / "data" / "backtest_results" / "lag_honesty.csv"
    out.to_csv(dest)
    cov_dest = ROOT / "data" / "backtest_results" / "coverage_windows.csv"
    coverage.to_csv(cov_dest, index=False)
    logger.info("Wrote %s and %s", dest, cov_dest)

    lags = _philly_lags()
    if nsa_payload is not None and nsa_payload.get("cpi_nsa_release_lag_days") is not None:
        from src.backtester.regime_clock import summarize_lags
        extra = []
        for key, series_name in (
            ("cpi_release_lag_days", "CPIAUCSL"),
            ("gdp_release_lag_days", "GDPC1"),
            ("cpi_nsa_release_lag_days", "CPIAUCNS"),
        ):
            if nsa_payload.get(key) is not None:
                extra.append({
                    "series": series_name,
                    "source": "fredapi_all_releases",
                    **summarize_lags(nsa_payload[key]),
                })
        extra_df = pd.DataFrame(extra)
        lags = extra_df if lags is None else pd.concat([lags, extra_df], ignore_index=True)
    if lags is not None:
        lag_dest = ROOT / "data" / "backtest_results" / "vintage_publication_lags.csv"
        lags.to_csv(lag_dest, index=False)
        logger.info("Publication lag (days from period-end to first vintage):\n%s", lags.to_string(index=False))
        logger.info("Wrote %s", lag_dest)

    print(out.to_string())
    print(coverage.to_string(index=False))
    return out


if __name__ == "__main__":
    main()
