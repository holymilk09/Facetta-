"""Run the complete local Facetta stack as one supervised process.

The Studio web bundle can remain visible in a browser after Metro or the API
has exited. Starting both services here, behind readiness checks, prevents that
cached shell from being mistaken for a healthy end-to-end preview.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MOBILE_ROOT = REPOSITORY_ROOT / "mobile"
API_HEALTH_URL = "http://127.0.0.1:8000/health"


def api_is_healthy(*, timeout: float = 1.0) -> bool:
    try:
        with urlopen(API_HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def port_is_open(port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_until(
    predicate,
    *,
    process: subprocess.Popen[bytes],
    label: str,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"{label} exited during startup with code {exit_code}")
        if predicate():
            return
        time.sleep(0.2)
    raise RuntimeError(f"{label} was not ready after {timeout:.0f} seconds")


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def check_stack() -> int:
    api_ok = api_is_healthy()
    studio_ok = port_is_open(8081)
    print(f"API 8000: {'healthy' if api_ok else 'offline'}")
    print(f"Studio 8081: {'listening' if studio_ok else 'offline'}")
    return 0 if api_ok and studio_ok else 1


def run_stack() -> int:
    if api_is_healthy() or port_is_open(8000):
        raise RuntimeError(
            "port 8000 is already in use; stop the existing API before running "
            "the supervised preview"
        )
    if port_is_open(8081):
        raise RuntimeError(
            "port 8081 is already in use; stop the existing Studio preview "
            "before running the supervised preview"
        )

    environment = os.environ.copy()
    environment.update({
        "FACETTA_ENV": "development",
        "FACETTA_AUTH_MODE": "test",
        "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
    })
    api: subprocess.Popen[bytes] | None = None
    studio: subprocess.Popen[bytes] | None = None
    try:
        print("Starting Facetta API on http://127.0.0.1:8000 ...", flush=True)
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "facetta.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
        )
        wait_until(api_is_healthy, process=api, label="Facetta API", timeout=20)
        print("API is healthy.", flush=True)

        print("Starting Facetta Studio on http://127.0.0.1:8081 ...", flush=True)
        studio = subprocess.Popen(
            ["npm", "run", "preview:bypass"],
            cwd=MOBILE_ROOT,
            env=environment,
        )
        wait_until(
            lambda: port_is_open(8081),
            process=studio,
            label="Facetta Studio",
            timeout=45,
        )
        print("Facetta is ready: http://127.0.0.1:8081/", flush=True)

        while True:
            api_exit = api.poll()
            studio_exit = studio.poll()
            if api_exit is not None:
                raise RuntimeError(f"Facetta API stopped with code {api_exit}")
            if studio_exit is not None:
                raise RuntimeError(f"Facetta Studio stopped with code {studio_exit}")
            if not api_is_healthy(timeout=1.0):
                raise RuntimeError("Facetta API failed its health check")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopping Facetta ...", flush=True)
        return 0
    finally:
        stop_process(studio)
        stop_process(api)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="check whether the API and Studio preview are currently reachable",
    )
    args = parser.parse_args()
    try:
        return check_stack() if args.check else run_stack()
    except RuntimeError as exc:
        print(f"Facetta preview failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
