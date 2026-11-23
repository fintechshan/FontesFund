"""WSGI callable used by Gunicorn and by ``python run_dashboard.py``.

Importing this module does not load market data and does not start a thread.
Gunicorn's ``post_worker_init`` (after fork, preload off) calls ``ensure_boot``.
The boot thread builds the Dash app. Until that finishes, ``/healthz`` is 200
and ``/readyz`` is 503. User routes are the Flask app ``run_dashboard`` registers.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from src.dashboard.runtime_state import STATE

logger = logging.getLogger("dashboard.wsgi")

_boot_lock = threading.Lock()
_boot_started = False


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def health_payload():
    regime = STATE.regime
    return {
        "ok": True,
        "live": True,
        "ready": bool(STATE.ready),
        "phase": STATE.phase,
        "comparison_clocks": STATE.clocks,
        "refreshing": bool(STATE.refreshing),
        "regime": regime or "unknown",
        "service": "etf-regime-strategist",
        "error": STATE.error,
        "timestamp": _utc_now(),
    }


def _json_response(start_response, payload, status):
    reason = {200: "OK", 503: "Service Unavailable"}.get(status, "OK")
    body = json.dumps(payload).encode("utf-8")
    start_response(
        f"{status} {reason}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body]


class DashboardWsgi:
    """Liveness stays on this wrapper so a busy Dash callback is not required.

    ``/healthz`` is liveness: 200 when the process can write a response,
    including while a refresh or the clock child is running.
    ``/readyz`` is the startup probe: 503 until the Dash app is mounted,
    then 200 for the life of the process (a later refresh does not flip it).
    """

    def __init__(self):
        self.flask = None

    def __call__(self, environ, start_response):
        path = (environ.get("PATH_INFO") or "/").rstrip("/") or "/"
        if path == "/healthz":
            return _json_response(start_response, health_payload(), 200)
        if path == "/readyz":
            payload = health_payload()
            status = 200 if STATE.ready else 503
            payload["ok"] = status == 200
            return _json_response(start_response, payload, status)
        app = self.flask
        if app is None or not STATE.ready:
            payload = health_payload()
            payload["ok"] = False
            payload["error"] = payload.get("error") or "starting"
            return _json_response(start_response, payload, 503)
        return app(environ, start_response)


server = DashboardWsgi()


def _install_test_routes(flask_app):
    hold = os.environ.get("DASHBOARD_TEST_HOLD_SEC", "").strip()
    if not hold:
        return
    seconds = float(hold)

    def _hold():
        import time
        time.sleep(seconds)
        return ("held", 200, {"Content-Type": "text/plain"})

    flask_app.add_url_rule("/_test/hold", endpoint="dashboard_test_hold", view_func=_hold)


def _boot():
    delay = os.environ.get("DASHBOARD_TEST_BOOT_DELAY", "").strip()
    if delay:
        import time
        time.sleep(float(delay))
    STATE.phase = "loading"
    STATE.error = None
    try:
        import run_dashboard as rd
        from src.dashboard.app import create_app

        rd.assemble_dashboard(sync_gcs=True)
        STATE.phase = "loading"
        app = create_app(rd.DASHBOARD_DATA)
        rd.register_routes(app.server)
        _install_test_routes(app.server)
        STATE.dash_app = app
        server.flask = app.server
        STATE.phase = "serving"
        STATE.ready = True
        logger.info("Dashboard ready (clocks=%s, regime=%s).", STATE.clocks, STATE.regime)
        rd.start_background_updater(rd.DASHBOARD_DATA)
    except Exception as exc:
        STATE.phase = "failed"
        STATE.ready = False
        STATE.error = str(exc)
        logger.exception("Dashboard boot failed")


def ensure_boot():
    """Start the boot thread once per process. Safe to call from a worker only."""
    global _boot_started
    with _boot_lock:
        if _boot_started:
            return False
        _boot_started = True
    threading.Thread(target=_boot, name="dashboard-boot", daemon=True).start()
    return True


def serve():
    """Local and container entry when not under Gunicorn. Threaded, one process.

    Bind first, then boot. That matches Gunicorn: the port accepts ``/healthz``
    while the Dash app is still loading.
    """
    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "8050"))
    logger.info("Serving threaded WSGI on 0.0.0.0:%s", port)
    httpd = make_server("0.0.0.0", port, server, threaded=True)
    ensure_boot()
    httpd.serve_forever()
