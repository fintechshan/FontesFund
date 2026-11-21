#!/usr/bin/env python3
"""Refresh strategy packs that are extended in place, then audit every book.

QQQ Vegas is the incremental pack. ``scripts/refresh_qqq_vegas_signal.py``
appends sessions and rewrites ``rebalances.csv`` / ``last_rebalance`` from
``pos``. The US and CDN books are rewritten in full by Cloud Scheduler
``/tasks/refresh`` (``run_backtest.py`` and ``scripts/run_cdn_backtest.py``).
This command audits those books and does not recompute their sleeves.

Exits 1 when the download is missing, the feed is too old to be the latest
US cash session, or any strategy pack fails the book audit. A current pack
with an unchanged history exits 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    del argv
    from scripts.refresh_qqq_vegas_signal import _print_report, refresh_signal
    from src.dashboard.pack_audit import audit_strategy_packs

    try:
        report = refresh_signal()
    except Exception as exc:  # noqa: BLE001 — caller keeps the previous pack
        print(f'QQQ Vegas signal pack unchanged: {exc}', file=sys.stderr)
        return 1
    _print_report(report)
    if report.get('history_repaired'):
        print('rebalance history repaired from the stored signal')
    rows = audit_strategy_packs(ROOT)
    failed = False
    for row in rows:
        print(f"pack {row.get('pack')} {row.get('status')}: {row.get('desc')}")
        if row.get('status') == 'FAIL':
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
