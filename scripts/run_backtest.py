"""
CLI Backtest Runner
====================
Run a full backtest of the regime-based ETF strategy from the command line.

Usage:
    python scripts/run_backtest.py [--years 10] [--capital 100000]
"""

import sys
import argparse
import logging
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description="Run ETF Regime Strategy Backtest")
    parser.add_argument("--years", type=int, default=10, help="Years of backtest history")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--output", type=str, default="data/reports/backtest_report.html",
                        help="Output HTML report path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("ETF REGIME STRATEGY BACKTEST")
    logger.info(f"Period: {args.years} years | Capital: ${args.capital:,.0f}")
    logger.info("=" * 60)

    try:
        # Step 1: Fetch data
        logger.info("\n📡 Step 1: Fetching market data...")
        import yfinance as yf
        from config.etf_universe import CORE_ETFS, ALL_ETFS
        from config.regime_rules import REGIME_ALLOCATIONS

        start_year = 2024 - args.years
        start_date = f"{start_year}-01-01"

        # Get ETF prices
        available_etfs = []
        for ticker in ALL_ETFS:
            try:
                test = yf.Ticker(ticker).history(period="5d")
                if not test.empty:
                    available_etfs.append(ticker)
            except Exception:
                pass

        logger.info(f"Available ETFs: {len(available_etfs)}/{len(ALL_ETFS)}")

        price_data = yf.download(
            available_etfs, start=start_date, auto_adjust=True
        )['Close'] if len(available_etfs) > 1 else None

        if price_data is None or price_data.empty:
            logger.error("Failed to download price data")
            return 1

        price_data = price_data.dropna(axis=1, how='all').ffill()
        logger.info(f"Price data: {price_data.shape[0]} days × {price_data.shape[1]} assets")

        # Step 2: Run backtest
        logger.info("\n📊 Step 2: Running backtests...")
        from src.backtester.engine import BacktestEngine
        from src.backtester.benchmarks import BENCHMARKS, create_benchmark_results

        engine = BacktestEngine(
            price_data=price_data,
            initial_capital=args.capital,
        )

        # Run benchmark strategies
        benchmark_results = create_benchmark_results(engine)

        # Run static regime allocation backtests for each regime
        regime_results = []
        for regime_name, weights in REGIME_ALLOCATIONS.items():
            result = engine.run_static_backtest(
                weights=weights,
                name=f"Regime: {regime_name.title()}",
            )
            regime_results.append(result)

        all_results = regime_results + benchmark_results

        # Step 3: Display results
        logger.info("\n📋 Step 3: Results Summary")
        logger.info("-" * 80)
        logger.info(f"{'Strategy':<30} {'AnnRet':>8} {'Sharpe':>8} {'MaxDD':>8} {'Vol':>8}")
        logger.info("-" * 80)

        for r in all_results:
            logger.info(
                f"{r.name:<30} {r.annual_return:>7.1%} {r.sharpe_ratio:>8.2f} "
                f"{r.max_drawdown:>7.1%} {r.volatility:>7.1%}"
            )

        logger.info("-" * 80)

        # Step 4: Generate report
        logger.info(f"\n📄 Step 4: Generating report → {args.output}")
        try:
            from src.backtester.reporter import PerformanceReporter
            reporter = PerformanceReporter()

            # Use first regime result for the report
            if regime_results and regime_results[0].equity_curve is not None:
                returns = price_data[available_etfs[:5]].pct_change().dropna().mean(axis=1)
                report_path = reporter.generate_html_report(
                    returns=returns,
                    output_path=Path(args.output),
                    title="ETF Regime Strategy Backtest Report",
                )
                if report_path:
                    logger.info(f"✅ Report saved: {report_path}")

            # Monthly heatmap
            if regime_results and regime_results[0].monthly_returns is not None:
                heatmap = reporter.generate_monthly_heatmap(regime_results[0].monthly_returns)
                logger.info(f"\nMonthly Returns Heatmap ({regime_results[0].name}):")
                print(heatmap.to_string())

        except Exception as e:
            logger.warning(f"Report generation failed (non-critical): {e}")

        logger.info("\n✅ Backtest complete!")
        return 0

    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Run: pip install -r requirements.txt")
        return 1
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
