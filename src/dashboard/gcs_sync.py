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
import time
from pathlib import Path

from src.dashboard.headline_gate import BASELINE_REL

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

# Paper 2-day confirmation. Not the locked v9 sleeve and not a live order.
VEGAS_SHADOW_FILES = [
    'data/qqq_vegas/shadow_2day_confirm/daily_signal.csv',
    'data/qqq_vegas/shadow_2day_confirm/equity_curve.csv',
    'data/qqq_vegas/shadow_2day_confirm/rebalances.csv',
    'data/qqq_vegas/shadow_2day_confirm/monthly_returns.csv',
    'data/qqq_vegas/shadow_2day_confirm/yearly_returns.csv',
    'data/qqq_vegas/shadow_2day_confirm/summary.json',
]

# Notify-only risk scorecard. Display and the weekday notifier. Not a weight input.
RISK_FLAG_FILES = [
    'data/risk_flags/flags.json',
]

# US package the headline gate is allowed to publish. Pushed as soon as the
# gate passes, before the CDN and Vegas steps, so a scheduler deadline cannot
# drop the heatmap inputs on the floor after the backtest has already succeeded.
US_BACKTEST_FILES = [
    'data/cache/price_data.csv',
    'data/cache/macro_data.pkl',
    'data/backtest_results/20yr_comparison.csv',
    # Last accepted B_targeted headline. Missing from the bucket until the
    # first targeted upload; the gate then uses lag_honesty.csv.
    BASELINE_REL,
    'data/backtest_results/all_equity_curves.csv',
]

# Files that the daily backtest refresh regenerates and that the dashboard reads.
SYNC_FILES = [
    *US_BACKTEST_FILES,
    'data/cache/cdn_price_data.csv',
    'data/backtest_results/cdn_equity_curve.csv',
    'data/backtest_results/cdn_monthly_returns.csv',
    'data/backtest_results/cdn_strategy_config.json',
    'data/backtest_results/cdn_comparison.csv',
    'data/backtest_results/cdn_benchmark_xiu.csv',
    'data/backtest_results/cdn_lag_honesty.csv',
    'data/cache/gsblbr_history.csv',
    *VEGAS_MARKET_FILES,
    *VEGAS_SIGNAL_FILES,
    *VEGAS_SHADOW_FILES,
    *RISK_FLAG_FILES,
]

# IBKR account snapshot — removed for public server security
IBKR_FILES = []


def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(BUCKET)


def _env_seconds(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def should_replace_local(local: Path, remote_updated) -> bool:
    """True when the bucket object should overwrite ``local``.

    A missing local file is replaced. A local file that is newer than the
    bucket object is kept. That is the corrected book baked into an image
    built after the last daily upload. A newer bucket object is the daily
    refresh and is downloaded. Equal timestamps (within one second) keep
    the local file so a retry does not churn the book.
    """
    if not local.exists():
        return True
    if remote_updated is None:
        return True
    try:
        remote_ts = remote_updated.timestamp()
    except Exception:
        return True
    return remote_ts > local.stat().st_mtime + 1.0


def download_data(bucket=None, files=None, budget_sec=None, blob_timeout=None):
    """GCS -> local at startup.

    Each blob call is bounded (``GCS_BLOB_TIMEOUT_SEC``, default 15s) and the
    whole pass stops at ``GCS_DOWNLOAD_BUDGET_SEC`` (default 45s). Files not
    reached keep the image copy. A newer local file is not overwritten.
    The downloaded object's update time becomes the file mtime so a genuinely
    old object still looks old to anything that checks age.
    """
    if bucket is None and not BUCKET:
        logger.info("GCS_BUCKET unset; skipping GCS download (using local/baked data).")
        return
    budget = _env_seconds("GCS_DOWNLOAD_BUDGET_SEC", 45.0) if budget_sec is None else budget_sec
    timeout = _env_seconds("GCS_BLOB_TIMEOUT_SEC", 15.0) if blob_timeout is None else blob_timeout
    names = list(SYNC_FILES + IBKR_FILES if files is None else files)
    deadline = time.monotonic() + max(0.0, budget)
    try:
        b = _bucket() if bucket is None else bucket
    except Exception as e:
        logger.warning(f"GCS download failed (falling back to local/baked data): {e}")
        return
    for rel in names:
        if time.monotonic() >= deadline:
            logger.warning(
                "GCS download budget (%.0fs) exhausted; keeping the remaining local files.",
                budget,
            )
            break
        try:
            blob = b.blob(rel)
            if not blob.exists(timeout=timeout):
                logger.info(f"GCS: {rel} not in bucket yet")
                continue
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not should_replace_local(dest, blob.updated):
                logger.info(f"GCS keep local (newer than bucket): {rel}")
                continue
            blob.download_to_filename(str(dest), timeout=timeout)
            if blob.updated:
                ts = blob.updated.timestamp()
                os.utime(dest, (ts, ts))
            logger.info(f"GCS down: {rel} (updated {blob.updated})")
        except Exception as e:
            logger.warning(f"GCS download skipped {rel} (keeping local file): {e}")


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


def upload_us_backtest():
    """local -> GCS for the targeted US package only.

    ``/tasks/refresh`` calls this as soon as the headline gate passes.
    CDN, Vegas, and the risk scorecard are uploaded later with ``upload_data``.
    """
    return _upload(US_BACKTEST_FILES)


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


def upload_vegas_shadow():
    """local -> GCS for the paper 2-day shadow. Does not upload the official sleeve."""
    return _upload(VEGAS_SHADOW_FILES)


def upload_risk_flags():
    """local -> GCS for the scorecard when the Merrill backtest did not upload."""
    return _upload(RISK_FLAG_FILES)


def upload_ibkr():
    """local -> GCS after a fresh IBKR account snapshot (Execution panel data)."""
    return _upload(IBKR_FILES)
