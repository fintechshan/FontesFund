"""Gunicorn application object: ``wsgi:server``.

This module does not register routes and does not start a background thread.
``gunicorn.conf.py`` calls ``ensure_boot`` from ``post_worker_init``, which
runs in the forked worker. Do not pass ``--preload``. A preloaded master
would import native libraries and then fork; threads started before that
fork do not survive, and BLAS / tokenizers locks can deadlock in the child.
"""
from src.dashboard.wsgi_app import server

__all__ = ["server"]
