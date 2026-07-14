"""Run the production Studio TypeScript gateway against a real FastAPI process.

Usage:
    PYTHONPATH=src uv run python scripts/run_studio_client_api_acceptance.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"acceptance API exited before startup:\n{output}")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                health = json.loads(response.read())
            if response.status == 200 and health.get("status") == "ok":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    raise RuntimeError("timed out waiting for the acceptance API")


def main() -> int:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="facetta-studio-client-") as temporary:
        environment = {
            **os.environ,
            "FACETTA_ENV": "test",
            "FACETTA_AUTH_MODE": "test",
            "FACETTA_ACCEPTANCE_DB_PATH": str(Path(temporary) / "acceptance.sqlite"),
            "PYTHONPATH": str(ROOT / "src"),
        }
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "studio_client_acceptance_server:app",
                "--app-dir",
                str(ROOT / "scripts"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_until_ready(base_url, server)
            completed = subprocess.run(
                [
                    "npx",
                    "tsx",
                    "scripts/studio_client_api_acceptance.ts",
                    base_url,
                ],
                cwd=ROOT / "mobile",
                env=environment,
                check=False,
            )
            return completed.returncode
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            if server.returncode not in {0, -15} and server.stdout:
                sys.stderr.write(server.stdout.read())


if __name__ == "__main__":
    raise SystemExit(main())
