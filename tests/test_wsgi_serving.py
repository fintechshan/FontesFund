"""Serving entrypoint: real HTTP server, health, and refresh single-flight.

The server process is local. It does not call a broker, and the refresh
latch returns before run_backtest.py. DASHBOARD_SKIP_CLOCKS / DASHBOARD_SKIP_AI
are set only in that process.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(port, path, timeout, method="GET", headers=None, body=None):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, payload, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.monotonic() - started


class GcsKeepLocalTests(unittest.TestCase):
    def test_newer_local_is_kept(self):
        from src.dashboard.gcs_sync import should_replace_local

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.csv"
            path.write_text("corrected")
            older = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) - timedelta(hours=2)
            self.assertFalse(should_replace_local(path, older))
            newer = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) + timedelta(hours=2)
            self.assertTrue(should_replace_local(path, newer))
            self.assertTrue(should_replace_local(Path(tmp) / "missing.csv", older))

    def test_download_skips_newer_local_and_obeys_budget(self):
        from src.dashboard import gcs_sync

        rel = "data/cache/_wsgi_gcs_keep_test.txt"
        dest = gcs_sync.ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("corrected-book")
        downloaded = []

        class Blob:
            updated = datetime.now(timezone.utc) - timedelta(days=3)

            def exists(self, timeout=None):
                return True

            def download_to_filename(self, path, timeout=None):
                downloaded.append(path)
                Path(path).write_text("stale-bucket")

        class Bucket:
            def blob(self, name):
                return Blob()

        try:
            gcs_sync.download_data(bucket=Bucket(), files=[rel], budget_sec=30, blob_timeout=5)
            self.assertEqual(dest.read_text(), "corrected-book")
            self.assertEqual(downloaded, [])

            os.utime(dest, (1, 1))
            Blob.updated = datetime.now(timezone.utc)
            gcs_sync.download_data(bucket=Bucket(), files=[rel], budget_sec=30, blob_timeout=5)
            self.assertEqual(dest.read_text(), "stale-bucket")
            self.assertEqual(len(downloaded), 1)

            downloaded.clear()
            dest.write_text("stay")
            gcs_sync.download_data(bucket=Bucket(), files=[rel, rel], budget_sec=0, blob_timeout=5)
            self.assertEqual(dest.read_text(), "stay")
            self.assertEqual(downloaded, [])
        finally:
            if dest.exists():
                dest.unlink()


class RouteOwnershipTests(unittest.TestCase):
    def test_refresh_handler_is_the_gated_one(self):
        import run_dashboard as rd

        names = rd._tasks_refresh_body.__code__.co_names
        consts = rd._tasks_refresh_body.__code__.co_consts
        self.assertIn("evaluate_headline_gate", names)
        self.assertIn("upload_us_backtest", names)
        self.assertIn("upload_ibkr", names)
        self.assertIn("ENABLE_IBKR", consts)
        from flask import Flask
        app = Flask("route-ownership")
        rd.register_routes(app)
        self.assertEqual(app.view_functions["tasks_refresh"].__module__, "run_dashboard")
        self.assertEqual(app.view_functions["ibkr_status"].__module__, "run_dashboard")
        client = app.test_client()
        denied = client.post("/tasks/refresh")
        self.assertEqual(denied.status_code, 401)
        body = denied.get_json()
        self.assertEqual(body["error"], "unauthorized")

    def test_importing_wsgi_does_not_start_a_worker_thread(self):
        code = (
            "import threading, wsgi\n"
            "names = [t.name for t in threading.enumerate()]\n"
            "print(','.join(names))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "DASHBOARD_SKIP_CLOCKS": "1", "DASHBOARD_SKIP_AI": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("dashboard-boot", proc.stdout)
        self.assertNotIn("dashboard-updater", proc.stdout)

    def test_gunicorn_config_is_one_unpreloaded_thread_pool(self):
        spec = importlib.util.spec_from_file_location("fontes_gunicorn_conf", ROOT / "gunicorn.conf.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertFalse(mod.preload_app)
        self.assertEqual(mod.workers, 1)
        self.assertGreaterEqual(mod.threads, 8)
        self.assertEqual(mod.worker_class, "gthread")
        self.assertEqual(mod.timeout, 0)
        self.assertTrue(callable(mod.post_worker_init))


class UpdaterTests(unittest.TestCase):
    def test_updater_starts_once_and_does_not_launch_backtest(self):
        import run_dashboard as rd

        launched = []
        real_run = subprocess.run

        def _boom(*args, **kwargs):
            launched.append(args)
            raise AssertionError("updater must not subprocess")

        rd._updater_started = False
        rd.HERMES_DATA = {"latest_alert": {"alert_level": "INFO", "message": "test"}}
        rd.DASHBOARD_DATA = {"current_regime": "goldilocks"}
        env = os.environ
        old_hook = env.get("HERMES_WEBHOOK_URL")
        env.pop("HERMES_WEBHOOK_URL", None)
        subprocess.run = _boom
        try:
            self.assertTrue(rd.start_background_updater(rd.DASHBOARD_DATA))
            self.assertFalse(rd.start_background_updater(rd.DASHBOARD_DATA))
            names = [t.name for t in threading.enumerate()]
            self.assertEqual(names.count("dashboard-updater"), 1)
            time.sleep(1.3)
            self.assertEqual(launched, [])
        finally:
            subprocess.run = real_run
            if old_hook is not None:
                env["HERMES_WEBHOOK_URL"] = old_hook


class ClockInvocationTests(unittest.TestCase):
    def test_assemble_calls_clock_child_unless_skipped(self):
        import run_dashboard as rd
        from src.dashboard import startup_jobs

        calls = []

        def fake(price, macro, weights, timeout=None):
            calls.append(timeout)
            return {
                "lagged_metrics": {"targeted": {"annual_return": "1.00%"}},
                "equity_curve": None,
                "monthly_returns": None,
            }

        old = startup_jobs.compute_clocks_subprocess
        startup_jobs.compute_clocks_subprocess = fake
        old_skip = os.environ.get("DASHBOARD_SKIP_CLOCKS")
        old_ai = os.environ.get("DASHBOARD_SKIP_AI")
        os.environ.pop("DASHBOARD_SKIP_CLOCKS", None)
        os.environ["DASHBOARD_SKIP_AI"] = "1"
        os.environ.pop("GCS_BUCKET", None)
        try:
            status = rd.assemble_dashboard(sync_gcs=False)
        finally:
            startup_jobs.compute_clocks_subprocess = old
            if old_skip is None:
                os.environ.pop("DASHBOARD_SKIP_CLOCKS", None)
            else:
                os.environ["DASHBOARD_SKIP_CLOCKS"] = old_skip
            if old_ai is None:
                os.environ.pop("DASHBOARD_SKIP_AI", None)
            else:
                os.environ["DASHBOARD_SKIP_AI"] = old_ai
        self.assertEqual(calls, [None])
        self.assertEqual(status, "ready")
        self.assertEqual(rd.DASHBOARD_DATA["audit"]["lagged_metrics"]["targeted"]["annual_return"], "1.00%")


class RealServerTests(unittest.TestCase):
    def test_health_page_and_layout_stay_up_during_slow_work(self):
        port = _free_port()
        log_path = ROOT / "data" / "cache" / "_wsgi_test_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "PORT": str(port),
            "DASHBOARD_SKIP_CLOCKS": "1",
            "DASHBOARD_SKIP_AI": "1",
            "DASHBOARD_TEST_BOOT_DELAY": "1.2",
            "DASHBOARD_TEST_HOLD_SEC": "4",
            "DASHBOARD_TEST_REFRESH_HOLD": "2",
            "REFRESH_TOKEN": "test-token-not-a-secret",
            "ENABLE_IBKR": "0",
            "PYTHONUNBUFFERED": "1",
        })
        env.pop("GCS_BUCKET", None)
        env.pop("HERMES_WEBHOOK_URL", None)
        env.pop("USE_REALTIME_VINTAGE", None)
        log = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "wsgi_serve_harness.py")],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            saw_starting = False
            ready_body = None
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise AssertionError(f"server exited {proc.returncode}\n{log_path.read_text()[-4000:]}")
                try:
                    code, payload, _elapsed = _request(port, "/healthz", timeout=2)
                except Exception:
                    time.sleep(0.05)
                    continue
                self.assertEqual(code, 200)
                body = json.loads(payload)
                self.assertTrue(body["live"])
                self.assertEqual(body["service"], "etf-regime-strategist")
                self.assertIn("comparison_clocks", body)
                self.assertIn("refreshing", body)
                rcode, rpayload, _ = _request(port, "/readyz", timeout=2)
                rbody = json.loads(rpayload)
                if rcode == 503:
                    saw_starting = True
                    self.assertFalse(rbody["ready"])
                    self.assertFalse(rbody["ok"])
                if body.get("phase") == "failed":
                    raise AssertionError(f"boot failed: {body.get('error')}\n{log_path.read_text()[-4000:]}")
                if rcode == 200 and rbody.get("ready"):
                    ready_body = rbody
                    break
                time.sleep(0.05)
            self.assertTrue(saw_starting, f"never saw /readyz 503\n{log_path.read_text()[-4000:]}")
            self.assertIsNotNone(ready_body)
            self.assertTrue(ready_body["ok"])
            self.assertEqual(ready_body["phase"], "serving")
            self.assertEqual(ready_body["comparison_clocks"], "skipped")

            hold_result = {}

            def _hold():
                hold_result["triple"] = _request(port, "/_test/hold", timeout=10)

            holder = threading.Thread(target=_hold)
            holder.start()
            time.sleep(0.3)
            parallel = {}

            def _one(name, path):
                parallel[name] = _request(port, path, timeout=3)

            workers = [
                threading.Thread(target=_one, args=pair)
                for pair in (("health", "/healthz"), ("page", "/"), ("layout", "/_dash-layout"))
            ]
            started = time.monotonic()
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=4)
            wall = time.monotonic() - started
            holder.join(timeout=8)
            h_code, h_body, h_dt = parallel["health"]
            page_code, page_body, page_dt = parallel["page"]
            lay_code, lay_body, lay_dt = parallel["layout"]
            self.assertLess(h_dt, 3, "health waited on the slow handler")
            self.assertLess(page_dt, 3, "HTML waited on the slow handler")
            self.assertLess(lay_dt, 3, "layout waited on the slow handler")
            self.assertLess(wall, 3.5)
            self.assertEqual(h_code, 200)
            health = json.loads(h_body)
            self.assertTrue(health["ready"])
            self.assertFalse(health["refreshing"])
            self.assertEqual(page_code, 200)
            self.assertIn(b"ETF Regime Strategist", page_body)
            self.assertEqual(lay_code, 200)
            self.assertTrue(lay_body[:1] in (b"{", b"["))
            self.assertEqual(hold_result["triple"][0], 200)
            self.assertIn(b"held", hold_result["triple"][1])

            # The slow hold already proved the thread pool. These are the
            # production routes, still on that same process.
            checks = [
                ("/api/hermes/regime-report", 200),
                ("/api/hermes/rebalance-alert", 200),
                ("/api/ibkr/status", 200),
            ]
            for path, expect in checks:
                code, payload, _ = _request(port, path, timeout=5)
                self.assertEqual(code, expect, path)
                parsed = json.loads(payload)
                if path.endswith("ibkr/status"):
                    self.assertFalse(parsed["connected"])
                    self.assertEqual(parsed["status"], "OFFLINE")
                    self.assertNotIn("account_summary", parsed)
                if path.endswith("regime-report"):
                    self.assertIn("current_regime", parsed)

            code, payload, _ = _request(port, "/tasks/refresh", timeout=5, method="POST")
            self.assertEqual(code, 401)
            self.assertEqual(json.loads(payload)["error"], "unauthorized")

            headers = {"X-Refresh-Token": "test-token-not-a-secret"}
            results = []

            def _refresh():
                results.append(_request(
                    port, "/tasks/refresh", timeout=8, method="POST", headers=headers, body=b"",
                ))

            threads = [threading.Thread(target=_refresh) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            codes = sorted(item[0] for item in results)
            self.assertEqual(codes, [200, 409], results)
            bodies = [json.loads(item[1]) for item in results]
            self.assertTrue(any(b.get("test_hold") for b in bodies))
            self.assertTrue(any(b.get("error") == "refresh_in_progress" for b in bodies))
            fast = [item for item in results if item[0] == 409]
            self.assertLess(fast[0][2], 1.5)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, 15)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, 9)
                    proc.wait(timeout=5)
            log.close()


if __name__ == "__main__":
    unittest.main()
