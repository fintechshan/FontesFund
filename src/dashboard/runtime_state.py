"""Process-wide serving flags.

Health and readiness read this. The refresh lock is the single-flight gate
shared by ``/tasks/refresh`` so two scheduler retries cannot run two backtests.
"""
from __future__ import annotations

import threading

class RuntimeState:
    def __init__(self):
        self._refresh = threading.Lock()
        self.ready = False
        self.phase = "booting"  # booting, loading, clocks, serving, failed
        self.clocks = "pending"  # pending, running, ready, failed, skipped
        self.refreshing = False
        self.error = None
        self.regime = None
        self.dash_app = None

    def begin_refresh(self) -> bool:
        if not self._refresh.acquire(blocking=False):
            return False
        self.refreshing = True
        return True

    def end_refresh(self) -> None:
        self.refreshing = False
        try:
            self._refresh.release()
        except RuntimeError:
            pass


STATE = RuntimeState()
