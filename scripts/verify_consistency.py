"""Compare saved US and CDN backtest rows with their equity curves and heatmaps.

Exit 0 when they are one series. Exit 1 when the heatmap compound, the
equity-curve total return, the 252-day CAGR, or the daily max drawdown
disagrees with the reported row.

A calendar-year CAGR of that same total return can sit a few basis points
away. A month-end snapshot of drawdown can sit about one to two percentage
points away from the daily peak-to-trough. Those two gaps are printed and
do not fail the check.

    python scripts/verify_consistency.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.cdn_regime_rules import CDN_AB_WINNER
from src.backtester.consistency import verify_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison",
        default=str(ROOT / "data" / "backtest_results" / "20yr_comparison.csv"),
    )
    parser.add_argument(
        "--equity",
        default=str(ROOT / "data" / "backtest_results" / "aggressive_equity_curve.csv"),
    )
    parser.add_argument(
        "--monthly",
        default=str(ROOT / "data" / "backtest_results" / "aggressive_monthly_returns.csv"),
    )
    parser.add_argument("--strategy", default="Optimized Regime Strategy")
    parser.add_argument(
        "--skip-cdn",
        action="store_true",
        help="Check only the US book.",
    )
    args = parser.parse_args(argv)
    report = verify_files(args.comparison, args.equity, args.monthly, args.strategy)
    print(report.text())
    ok = report.ok
    if not args.skip_cdn:
        cdn = verify_files(
            ROOT / "data" / "backtest_results" / "cdn_comparison.csv",
            ROOT / "data" / "backtest_results" / "cdn_equity_curve.csv",
            ROOT / "data" / "backtest_results" / "cdn_monthly_returns.csv",
            CDN_AB_WINNER,
        )
        print(cdn.text())
        ok = ok and cdn.ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
