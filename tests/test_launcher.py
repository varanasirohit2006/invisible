import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

PROJECT = Path(__file__).resolve().parents[1]
PROCESS_OPTIONS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def launch(port, data_dir, *args):
    return subprocess.run(
        [
            sys.executable,
            str(PROJECT / "run.py"),
            "--port",
            str(port),
            "--data-dir",
            str(data_dir),
            *args,
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=15,
        **PROCESS_OPTIONS,
    )


@contextmanager
def health_server(payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_duplicate_launch_returns_success_before_initializing_storage(tmp_path):
    runtime = tmp_path / "unused-runtime"
    with health_server({"service": "invisible-work-detector", "status": "ok"}) as port:
        result = launch(port, runtime, "--demo", "--no-agent", "--show-token")
    assert result.returncode == 0, result.stderr
    assert f"already running: http://127.0.0.1:{port}" in result.stdout
    assert "Startup options apply only" in result.stdout
    assert "Pairing token:" not in result.stdout
    assert not runtime.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"service": "another-app", "status": "ok"},
        {"service": "invisible-work-detector", "status": "starting"},
        ["unexpected", "health", "response"],
    ],
)
def test_unrelated_server_gets_actionable_port_error(tmp_path, payload):
    runtime = tmp_path / "unused-runtime"
    with health_server(payload) as port:
        result = launch(port, runtime)
    assert result.returncode == 2, result.stderr
    assert f"Port {port}" in result.stderr
    assert "-Port" in result.stderr
    assert "Traceback" not in result.stderr
    assert not runtime.exists()


def test_non_http_port_owner_does_not_start_another_agent(tmp_path):
    runtime = tmp_path / "unused-runtime"
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        result = launch(occupied.getsockname()[1], runtime)
    assert result.returncode == 2, result.stderr
    assert "already in use" in result.stderr
    assert not runtime.exists()


def test_real_server_starts_on_reserved_socket_and_duplicate_does_not_disturb_it(tmp_path):
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    runtime = tmp_path / "runtime"
    with (
        (tmp_path / "stdout.log").open("w") as stdout,
        (tmp_path / "stderr.log").open("w") as stderr,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                str(PROJECT / "run.py"),
                "--port",
                str(port),
                "--data-dir",
                str(runtime),
                "--no-agent",
            ],
            cwd=PROJECT,
            stdout=stdout,
            stderr=stderr,
            **PROCESS_OPTIONS,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=1, trust_env=False
            ) as client:
                deadline = time.monotonic() + 15
                while True:
                    assert process.poll() is None, (tmp_path / "stderr.log").read_text()
                    try:
                        response = client.get("/api/health")
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert time.monotonic() < deadline, "Server did not become healthy"
                    time.sleep(0.1)
                duplicate_runtime = tmp_path / "duplicate-runtime"
                result = launch(port, duplicate_runtime, "--show-token")
                assert result.returncode == 0, result.stderr
                assert "already running" in result.stdout
                assert not duplicate_runtime.exists()
                assert process.poll() is None
                assert client.get("/api/health").json()["status"] == "ok"
        finally:
            process.terminate()
            process.wait(timeout=10)
