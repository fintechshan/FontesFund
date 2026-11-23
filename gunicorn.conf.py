"""Gunicorn settings for the one Cloud Run container.

One worker: the Dash process already holds the price cache, and a second
worker would double that RSS under the 2Gi limit. Threads, not processes,
so ``/healthz``, ``/``, and ``/_dash-layout`` stay reachable while
``/tasks/refresh`` waits on a subprocess.

``timeout = 0`` disables Gunicorn's silent-worker kill. The refresh handler
blocks in ``subprocess.run`` for longer than any 30s or 300s worker timeout,
and a kill mid-upload is worse than letting Cloud Run's request timeout
bound the HTTP call. Stage budgets inside the handler are the application
limit (see docs/cloud_run_serving.md).

``preload_app`` stays false. See ``wsgi.py``.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
threads = 8
worker_class = "gthread"
timeout = 0
graceful_timeout = 30
keepalive = 5
preload_app = False


def post_worker_init(worker):
    from src.dashboard.wsgi_app import ensure_boot
    ensure_boot()
