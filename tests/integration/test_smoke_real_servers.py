"""End-to-end smoke test over real HTTP.

Boots both services as actual uvicorn subprocesses on ephemeral ports and
drives the full integration path with network traffic: POST a rule on the
Manager, observe it via GET /blocked on the Sync API (the exact call the
browser extension makes), then verify the ETag/304 handshake. This is the
strongest proof of inter-service communication in the suite; the other modules
run both ASGI apps in-process for speed and determinism.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(module: str, port: int, env_extra: dict[str, str]) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": str(ROOT), **env_extra}
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env=env,
    )


def _wait_healthy(base_url: str, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"service at {base_url} never became healthy: {last_exc}")


def test_end_to_end_over_real_http(tmp_path):
    sync_port, manager_port = _free_port(), _free_port()
    sync_base = f"http://127.0.0.1:{sync_port}"

    sync_proc = _start(
        "services.sync_api.main:sync_app", sync_port, {"TOMATTO_SYNC_DB": str(tmp_path / "sync.db")}
    )
    manager_proc = _start(
        "services.manager_api.main:manager_app",
        manager_port,
        {
            "TOMATTO_MANAGER_DB": str(tmp_path / "manager.db"),
            "TOMATTO_SYNC_URL": sync_base,
        },
    )
    try:
        _wait_healthy(sync_base)
        _wait_healthy(f"http://127.0.0.1:{manager_port}")

        # Manager -> Sync write-through over real HTTP
        resp = httpx.post(
            f"http://127.0.0.1:{manager_port}/rules", json={"domain": "real-http.example.com"}, timeout=5.0
        )
        assert resp.status_code == 201
        assert resp.json()["sync_status"] == "synced"

        # The extension's exact poll request, with ETag handshake
        first = httpx.get(f"{sync_base}/blocked", timeout=5.0)
        assert first.status_code == 200
        assert "real-http.example.com" in [s["domain"] for s in first.json()["sites"]]

        second = httpx.get(
            f"{sync_base}/blocked", headers={"If-None-Match": first.headers["etag"]}, timeout=5.0
        )
        assert second.status_code == 304
    finally:
        for proc in (manager_proc, sync_proc):
            proc.terminate()
        for proc in (manager_proc, sync_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
