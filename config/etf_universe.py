"""
config/etf_universe.py
======================
Complete ETF universe for the Investment Application.

Each ETF is described by an :class:`ETFInfo` dataclass that records its
category, cost, leverage characteristics, and which macro regimes it may
participate in.  Helper functions allow quick lookups by ticker, category,
or regime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ETFInfo:
    """Immutable descriptor for a single ETF."""

    ticker: str
    name: str
    category: str
    expense_ratio: float
    leveraged: bool = False
    leverage_factor: float = 1.0
    regime_allowed: list[str] = field(
        default_factory=lambda: ["goldilocks", "reflation", "stagflation", "deflation"]
    )
    dividend_yield: float = 0.0
    domicile: str = "US"


# ---------------------------------------------------------------------------
# Universe definition
# ---------------------------------------------------------------------------

# -- US Large Cap ----------------------------------------------------------
SPY = ETFInfo("SPY", "SPDR S&P 500 ETF Trust", "US Large Cap", 0.0009, dividend_yield=0.013, domicile="US")
VOO = ETFInfo("VOO", "Vanguard S&P 500 ETF", "US Large Cap", 0.0003, dividend_yield=0.013, domicile="US")
XLY = ETFInfo("XLY", "Consumer Discretionary Select Sector SPDR Fund", "Consumer Discretionary", 0.0009, dividend_yield=0.007, domicile="US")

# -- US Growth -------------------------------------------------------------
QQQ = ETFInfo("QQQ", "Invesco QQQ Trust", "US Growth", 0.0020, dividend_yield=0.005, domicile="US")

# -- US Small Cap -----------------------------------------------------------
IWM = ETFInfo("IWM", "iShares Russell 2000 ETF", "US Small Cap", 0.0019, dividend_yield=0.014, domicile="US")

# -- International Developed -----------------------------------------------
VEA = ETFInfo("VEA", "Vanguard FTSE Developed Markets ETF", "International Developed", 0.0005, dividend_yield=0.031, domicile="US")

# -- Emerging Markets -------------------------------------------------------
VWO = ETFInfo("VWO", "Vanguard FTSE Emerging Markets ETF", "Emerging Markets", 0.0008, dividend_yield=0.028, domicile="US")

# -- Long Bonds -------------------------------------------------------------
TLT = ETFInfo("TLT", "iShares 20+ Year Treasury Bond ETF", "Long Bonds", 0.0015, dividend_yield=0.035, domicile="US")

# -- Mid Bonds --------------------------------------------------------------
IEF = ETFInfo("IEF", "iShares 7-10 Year Treasury Bond ETF", "Mid Bonds", 0.0015, dividend_yield=0.028, domicile="US")

# -- Short Bonds ------------------------------------------------------------
SHY = ETFInfo("SHY", "iShares 1-3 Year Treasury Bond ETF", "Short Bonds", 0.0015, dividend_yield=0.031, domicile="US")

# -- Aggregate Bonds --------------------------------------------------------
AGG = ETFInfo("AGG", "iShares Core U.S. Aggregate Bond ETF", "Aggregate Bonds", 0.0003, dividend_yield=0.032, domicile="US")

# -- TIPS -------------------------------------------------------------------
TIP = ETFInfo("TIP", "iShares TIPS Bond ETF", "TIPS", 0.0019, dividend_yield=0.025, domicile="US")

# -- Gold -------------------------------------------------------------------
GLD = ETFInfo("GLD", "SPDR Gold Shares", "Gold", 0.0040, dividend_yield=0.0, domicile="US")

# -- Commodities ------------------------------------------------------------
DBC = ETFInfo("DBC", "Invesco DB Commodity Index Tracking Fund", "Commodities", 0.0085, dividend_yield=0.015, domicile="US")

# -- Real Estate ------------------------------------------------------------
VNQ = ETFInfo("VNQ", "Vanguard Real Estate ETF", "Real Estate", 0.0012, dividend_yield=0.038, domicile="US")

# -- Managed Futures --------------------------------------------------------
DBMF = ETFInfo("DBMF", "iMGP DBi Managed Futures Strategy ETF", "Managed Futures", 0.0085, dividend_yield=0.020, domicile="US")

# -- Anti-Beta --------------------------------------------------------------
BTAL = ETFInfo("BTAL", "AGFiQ U.S. Market Neutral Anti-Beta Fund", "Anti-Beta", 0.0151, dividend_yield=0.015, domicile="US")

# -- High-Yield Equity (Covered-Call Income) --------------------------------
SPYI = ETFInfo("SPYI", "NEOS S&P 500 High Income ETF", "High-Yield Equity", 0.0068, dividend_yield=0.120, domicile="US")
QQQI = ETFInfo("QQQI", "NEOS Nasdaq-100 High Income ETF", "High-Yield Equity", 0.0068, dividend_yield=0.120, domicile="US")

# -- Semiconductors ---------------------------------------------------------
SOXX = ETFInfo("SOXX", "iShares Semiconductor ETF", "Semiconductors", 0.0035, dividend_yield=0.007, domicile="US")
SMH = ETFInfo("SMH", "VanEck Semiconductor ETF", "Semiconductors", 0.0035, dividend_yield=0.005, domicile="US")
XSD = ETFInfo("XSD", "SPDR S&P Semiconductor ETF (equal-weight)", "Semiconductors", 0.0035, dividend_yield=0.003, domicile="US")

# -- AI / Tech Theme --------------------------------------------------------
DRAM = ETFInfo("DRAM", "AI Memory & Semiconductor Theme ETF", "AI/Tech Theme", 0.0065, dividend_yield=0.0, domicile="US")
AIPO = ETFInfo("AIPO", "Defiance AI & Power Infrastructure ETF", "AI/Tech Theme", 0.0065, dividend_yield=0.0, domicile="US")

# -- Uranium / Nuclear -----------------------------------------------------
URA = ETFInfo("URA", "Global X Uranium ETF", "Uranium", 0.0085, dividend_yield=0.025, domicile="US")

# -- Canadian Equity / Income ----------------------------------------------
XEI_TO = ETFInfo("XEI.TO", "iShares S&P/TSX Composite High Dividend Index ETF", "Canadian Equity", 0.0022, dividend_yield=0.055, domicile="CA")
ZWB_TO = ETFInfo("ZWB.TO", "BMO Covered Call Canadian Banks ETF", "Canadian Equity", 0.0072, dividend_yield=0.073, domicile="CA")

# -- Leveraged ETFs ---------------------------------------------------------
TQQQ = ETFInfo(
    "TQQQ",
    "ProShares UltraPro QQQ",
    "Leveraged",
    0.0086,
    leveraged=True,
    leverage_factor=3.0,
    regime_allowed=["goldilocks"],
    dividend_yield=0.010,
    domicile="US"
)
SOXL = ETFInfo(
    "SOXL",
    "Direxion Daily Semiconductor Bull 3X Shares",
    "Leveraged",
    0.0076,
    leveraged=True,
    leverage_factor=3.0,
    regime_allowed=["goldilocks"],
    dividend_yield=0.005,
    domicile="US"
)
# GGLL (Direxion Daily GOOGL Bull 2X) removed 2026-06-22 — decommissioned, no
# price data, not in the tested universe. SSO (2x S&P 500) covers the 2x sleeve.


# ---------------------------------------------------------------------------
# Curated lists
# ---------------------------------------------------------------------------

CORE_ETFS: list[ETFInfo] = [
    SPY, VOO, QQQ, IWM, VEA, VWO,
    TLT, IEF, SHY, AGG, TIP,
    GLD, DBC, VNQ, DBMF, BTAL,
    SOXX, SMH, XSD, DRAM, AIPO,
    URA, XLY, XEI_TO, ZWB_TO,
]
"""Non-leveraged ETFs eligible for all regimes."""

INCOME_ETFS: list[ETFInfo] = [SPYI, QQQI]
"""Covered-call / high-income equity ETFs."""

TECH_ETFS: list[ETFInfo] = [QQQ, SOXX, SMH, XSD, DRAM, AIPO]
"""Technology & semiconductor-focused ETFs (the AI-trend complex)."""

LEVERAGED_ETFS: list[ETFInfo] = [TQQQ, SOXL]
"""Leveraged / geared ETFs — regime-restricted."""

ALL_ETFS: list[ETFInfo] = CORE_ETFS + INCOME_ETFS + LEVERAGED_ETFS
"""Full universe of tradeable ETFs."""

# Internal lookup dictionary (ticker -> ETFInfo)
_TICKER_MAP: dict[str, ETFInfo] = {etf.ticker: etf for etf in ALL_ETFS}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_etf(ticker: str) -> Optional[ETFInfo]:
    """Return the :class:`ETFInfo` for *ticker*, or ``None`` if not found.

    Parameters
    ----------
    ticker:
        Upper-case ETF ticker symbol (e.g. ``"SPY"``).

    Returns
    -------
    Optional[ETFInfo]
        The matching ETF descriptor, or ``None``.
    """
    result = _TICKER_MAP.get(ticker.upper())
    if result is None:
        logger.warning("Ticker '%s' not found in ETF universe.", ticker)
    return result


def get_etfs_by_category(category: str) -> list[ETFInfo]:
    """Return all ETFs whose category matches *category* (case-insensitive).

    Parameters
    ----------
    category:
        Category string, e.g. ``"US Large Cap"``.

    Returns
    -------
    list[ETFInfo]
        Matching ETFs (may be empty).
    """
    cat_lower = category.lower()
    return [etf for etf in ALL_ETFS if etf.category.lower() == cat_lower]


def get_regime_allowed_etfs(regime: str) -> list[ETFInfo]:
    """Return all ETFs that are allowed to trade in the given *regime*.

    Parameters
    ----------
    regime:
        One of ``"goldilocks"``, ``"reflation"``, ``"stagflation"``,
        ``"deflation"``.

    Returns
    -------
    list[ETFInfo]
        ETFs whose ``regime_allowed`` includes *regime*.
    """
    regime_lower = regime.lower()
    return [etf for etf in ALL_ETFS if regime_lower in etf.regime_allowed]
