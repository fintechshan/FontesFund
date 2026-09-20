"""
Benchmark Strategies Module
============================
Defines benchmark portfolio allocations for comparison against the regime strategy.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtester.engine import BacktestEngine, BacktestResult

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#                         BENCHMARK DEFINITIONS                               #
# --------------------------------------------------------------------------- #

BENCHMARKS: dict[str, dict[str, float]] = {
    "60/40 Portfolio": {
        "SPY": 0.60,
        "AGG": 0.40,
    },
    "All Weather": {
        "SPY": 0.30,
        "TLT": 0.40,
        "IEF": 0.15,
        "GLD": 0.075,
        "DBC": 0.075,
    },
    "S&P 500 Buy & Hold": {
        "SPY": 1.0,
    },
    "100% Bonds": {
        "AGG": 0.50,
        "TLT": 0.30,
        "SHY": 0.20,
    },
    "Equal Weight Core": {
        # Will be filled dynamically from CORE_ETFS
    },
    "Tech Tilt": {
        "QQQ": 0.30,
        "SPY": 0.20,
        "SOXX": 0.10,
        "TLT": 0.15,
        "GLD": 0.10,
        "AGG": 0.10,
        "VEA": 0.05,
    },
    "Income Focus": {
        "SPYI": 0.25,
        "QQQI": 0.20,
        "AGG": 0.20,
        "TLT": 0.15,
        "GLD": 0.10,
        "VNQ": 0.10,
    },
}


def _build_equal_weight() -> dict[str, float]:
    """Build equal-weight portfolio from CORE_ETFS."""
    try:
        from config.etf_universe import CORE_ETFS
        n = len(CORE_ETFS)
        if n > 0:
            weight = round(1.0 / n, 4)
            return {etf.ticker: weight for etf in CORE_ETFS}
    except ImportError:
        logger.warning("Could not import CORE_ETFS, using fallback equal weight")

    # Fallback
    tickers = ["SPY", "QQQ", "IWM", "VEA", "VWO", "TLT", "IEF", "GLD", "AGG", "VNQ"]
    w = round(1.0 / len(tickers), 4)
    return {t: w for t in tickers}


# Initialize equal weight benchmark
BENCHMARKS["Equal Weight Core"] = _build_equal_weight()


def get_benchmark(name: str) -> dict[str, float]:
    """
    Get benchmark weights by name.

    Args:
        name: Benchmark strategy name.

    Returns:
        Dict of ticker -> weight.

    Raises:
        KeyError: If benchmark name not found.
    """
    if name not in BENCHMARKS:
        available = ", ".join(BENCHMARKS.keys())
        raise KeyError(f"Unknown benchmark '{name}'. Available: {available}")
    return BENCHMARKS[name]


def list_benchmarks() -> list[str]:
    """Return list of available benchmark names."""
    return list(BENCHMARKS.keys())


def create_benchmark_results(engine: "BacktestEngine") -> list["BacktestResult"]:
    """
    Run all benchmark strategies through the backtest engine.

    Args:
        engine: Initialized BacktestEngine with price data.

    Returns:
        List of BacktestResult objects, one per benchmark.
    """
    results = []
    for name, weights in BENCHMARKS.items():
        try:
            result = engine.run_static_backtest(weights=weights, name=name)
            results.append(result)
            logger.info(
                f"Benchmark '{name}': return={result.annual_return:.2%}, "
                f"sharpe={result.sharpe_ratio:.2f}, maxDD={result.max_drawdown:.2%}"
            )
        except Exception as e:
            logger.error(f"Benchmark '{name}' failed: {e}")

    return results
