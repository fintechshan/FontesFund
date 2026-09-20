"""
config/settings.py
==================
App-wide configuration for the ETF Investment Application.

Loads environment variables from a .env file and exposes all settings
as module-level constants. Data directories are created on import.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
import os

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root & .env loading
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
# SECURITY: No hardcoded key fallback. Set FRED_API_KEY in .env or as a
# Cloud Run environment variable. The app will warn and degrade gracefully
# if the key is missing (yfinance data still works; only FRED series fail).
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "")
if not FRED_API_KEY:
    logger.warning(
        "FRED_API_KEY is not set. Macro data from FRED will be unavailable. "
        "Set this via Cloud Run --set-env-vars or a .env file."
    )
FINNHUB_API_KEY: str = os.getenv("FINNHUB_API_KEY", "")

# ---------------------------------------------------------------------------
# IBKR Connection
# ---------------------------------------------------------------------------
IBKR_HOST: str = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT: int = int(os.getenv("IBKR_PORT", "4002"))
IBKR_CLIENT_ID: int = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_ACCOUNT: str = os.getenv("IBKR_ACCOUNT", "")

# ---------------------------------------------------------------------------
# Portfolio / Rebalance
# ---------------------------------------------------------------------------
INITIAL_CAPITAL: float = float(os.getenv("INITIAL_CAPITAL", "100000"))
MONTHLY_CONTRIBUTION: float = float(os.getenv("MONTHLY_CONTRIBUTION", "10000"))
REBALANCE_FREQUENCY: str = "monthly"
REBALANCE_DAY: int = int(os.getenv("REBALANCE_DAY", "1"))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR: Path = PROJECT_ROOT / "data"
CACHE_DIR: Path = DATA_DIR / "cache"
DB_PATH: Path = DATA_DIR / "db" / "investment.db"

# ---------------------------------------------------------------------------
# Ensure directories exist
# ---------------------------------------------------------------------------
for _dir in (DATA_DIR, CACHE_DIR, DB_PATH.parent):
    _dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Ensured directory exists: %s", _dir)
