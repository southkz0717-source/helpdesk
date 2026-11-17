"""Start the real service (uvicorn) on a free port with an empty database for E2E tests."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(tmp_path_factory) -> str:
    port = free_port()
    env = {**os.environ, "HELPDESK_DB": str(tmp_path_factory.mktemp("e2e") / "e2e.db")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{url}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("helpdesk did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(server_url) -> str:
    """pytest-playwright uses base_url for page.goto("/...")."""
    return server_url
