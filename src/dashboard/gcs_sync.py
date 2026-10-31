"""
src/dashboard/gcs_sync.py
=========================
Persist the daily-refreshed data caches in a GCS bucket so they survive Cloud Run's
scale-to-zero (the container filesystem is ephemeral; only the baked image data would
otherwise be shown). At startup the app pulls the latest caches from GCS; after a
`/tasks/refresh` run the fresh caches are pushed back.

No-op when GCS_BUCKET is unset (e.g. local dev) — the app just uses local/baked data.
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger('gcs_sync')
ROOT = Path(__file__).resolve().parents[2]
BUCKET = os.getenv('GCS_BUCKET', '').strip()

# QQQ Vegas price/PE pack. Display only — not an input to the v9 signal.
VEGAS_MARKET_FILES = [
    'data/qqq_vegas/market_prices.csv',
    'data/qqq_vegas/market_snapshot.json',
]

# Locked v9 sleeve. scripts/refresh_qqq_vegas_signal.py extends it.
# It is not the Merrill book and it does not read REGIME_WEIGHTS.
VEGAS_SIGNAL_FILES = [
    'data/qqq_vegas/daily_signal.csv',
    'data/qqq_vegas/equity_curve.csv',
    'data/qqq_vegas/rebalances.csv',
    'data/qqq_vegas/monthly_returns.csv',
    'data/qqq_vegas/yearly_returns.csv',
    'data/qqq_vegas/signal_current.json',
    'data/qqq_vegas/summary.json',
    'data/qqq_vegas/strategy.json',
    'data/qqq_vegas/live_snapshot.json',
]

# Notify-only risk scorecard. Display and the weekday notifier. Not a weight input.
RISK_FLAG_FILES = [
    'data/risk_flags/flags.json',
]

# Files that the daily backtest refresh regenerates and that the dashboard reads.
SYNC_FILES = [
    'data/cache/price_data.csv',
    'data/cache/macro_data.pkl',
    'data/cache/cdn_price_data.csv',
    'data/backtest_results/20yr_comparison.csv',
    'data/backtest_results/all_equity_curves.csv',
    'data/backtest_results/cdn_equity_curve.csv',
    'data/backtest_results/cdn_monthly_returns.csv',
    'data/backtest_results/cdn_strategy_config.json',
    'data/backtest_results/cdn_comparison.csv',
    'data/backtest_results/cdn_benchmark_xiu.csv',
    'data/backtest_results/cdn_lag_honesty.csv',
    'data/cache/gsblbr_history.csv',
    *VEGAS_MARKET_FILES,
    *VEGAS_SIGNAL_FILES,
    *RISK_FLAG_FILES,
]

# IBKR account snapshot — removed for public server security
IBKR_FILES = []


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def download_data():
    """GCS -> local at startup. Preserves each blob's update time as the file mtime
    so the staleness check in run_dashboard stays honest (a genuinely old GCS object
    still triggers a self-healing on-startup refresh)."""
    if not BUCKET:
        logger.info("GCS_BUCKET unset; skipping GCS download (using local/baked data).")
        return
    try:
        b = _bucket()
        for rel in SYNC_FILES + IBKR_FILES:
            blob = b.blob(rel)
            if blob.exists():
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(dest))
                if blob.updated:
                    ts = blob.updated.timestamp()
                    os.utime(dest, (ts, ts))
                logger.info(f"GCS down: {rel} (updated {blob.updated})")
            else:
                logger.info(f"GCS: {rel} not in bucket yet")
    except Exception as e:
        logger.warning(f"GCS download failed (falling back to local/baked data): {e}")


def _upload(files):
    if not BUCKET:
        logger.info("GCS_BUCKET unset; skipping GCS upload.")
        return []
    uploaded = []
    try:
        b = _bucket()
        for rel in files:
            src = ROOT / rel
            if src.exists():
                b.blob(rel).upload_from_filename(str(src))
                uploaded.append(rel)
                logger.info(f"GCS up: {rel}")
    except Exception as e:
        logger.warning(f"GCS upload failed: {e}")
    return uploaded


def download_ibkr():
    """GCS -> local for just the IBKR snapshot files. Called from a dashboard
    interval callback so a warm container picks up new snapshots (pushed by the
    local PC task or a manual refresh) WITHOUT needing a restart/redeploy.
    Returns True if a snapshot file was downloaded."""
    if not BUCKET:
        return False
    got = False
    try:
        b = _bucket()
        for rel in IBKR_FILES:
            blob = b.blob(rel)
            if blob.exists():
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(dest))
                got = True
    except Exception as e:
        logger.warning(f"GCS ibkr download failed: {e}")
    return got


def download_vegas_market():
    """GCS -> local for the QQQ/QLD price and PE cache only.

    Used by the QQQ Vegas tab so a warm container picks up the daily pack
    without a redeploy. No-op when GCS_BUCKET is unset. A failure leaves
    the files already on disk.
    """
    if not BUCKET:
        return False
    got = False
    try:
        b = _bucket()
        for rel in VEGAS_MARKET_FILES:
            blob = b.blob(rel)
            if not blob.exists():
                logger.info(f"GCS: {rel} not in bucket yet")
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dest))
            if blob.updated:
                ts = blob.updated.timestamp()
                os.utime(dest, (ts, ts))
            logger.info(f"GCS down: {rel} (updated {blob.updated})")
            got = True
    except Exception as e:
        logger.warning(f"GCS vegas market download failed (keeping local files): {e}")
    return got


def upload_data():
    """local -> GCS after a successful backtest refresh (price/macro/results)."""
    return _upload(SYNC_FILES)


def download_risk_flags():
    """GCS -> local for the notify-only scorecard. A failure keeps the local file."""
    if not BUCKET:
        return False
    got = False
    try:
        b = _bucket()
        for rel in RISK_FLAG_FILES:
            blob = b.blob(rel)
            if not blob.exists():
                logger.info(f"GCS: {rel} not in bucket yet")
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dest))
            if blob.updated:
                ts = blob.updated.timestamp()
                os.utime(dest, (ts, ts))
            logger.info(f"GCS down: {rel} (updated {blob.updated})")
            got = True
    except Exception as e:
        logger.warning(f"GCS risk-flag download failed (keeping local files): {e}")
    return got


def upload_vegas_market():
    """local -> GCS for the QQQ/QLD pack when the Merrill backtest did not upload."""
    return _upload(VEGAS_MARKET_FILES)


def download_vegas_signal():
    """GCS -> local for the v9 signal pack. A failure keeps the files on disk."""
    if not BUCKET:
        return False
    got = False
    try:
        b = _bucket()
        for rel in VEGAS_SIGNAL_FILES:
            blob = b.blob(rel)
            if not blob.exists():
                logger.info(f"GCS: {rel} not in bucket yet")
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(dest))
            if blob.updated:
                ts = blob.updated.timestamp()
                os.utime(dest, (ts, ts))
            logger.info(f"GCS down: {rel} (updated {blob.updated})")
            got = True
    except Exception as e:
        logger.warning(f"GCS vegas signal download failed (keeping local files): {e}")
    return got


def upload_vegas_signal():
    """local -> GCS for the v9 sleeve when the Merrill backtest did not upload."""
    return _upload(VEGAS_SIGNAL_FILES)


def upload_risk_flags():
    """local -> GCS for the scorecard when the Merrill backtest did not upload."""
    return _upload(RISK_FLAG_FILES)


def upload_ibkr():
    """local -> GCS after a fresh IBKR account snapshot (Execution panel data)."""
    return _upload(IBKR_FILES)
