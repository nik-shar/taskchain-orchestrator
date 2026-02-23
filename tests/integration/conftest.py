from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib import error, request

import pytest


def _pick_free_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("Socket operations are blocked in this environment.")


def _wait_for_health(base_url: str, timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with request.urlopen(f"{base_url}/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise TimeoutError(f"Server did not become healthy within {timeout_s:.1f}s")


def _start_server(env: dict[str, str], port: int, cwd: Path) -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "orchestrator_api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    return subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


@pytest.fixture
def api_base_url() -> Iterator[str]:
    if os.getenv("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "Set RUN_POSTGRES_INTEGRATION_TESTS=1 and ORCHESTRATOR_DATABASE_URL "
            "to run integration tests against PostgreSQL."
        )
    database_url = os.getenv("ORCHESTRATOR_DATABASE_URL")
    if not database_url:
        pytest.skip("ORCHESTRATOR_DATABASE_URL is required for integration tests.")

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["ORCHESTRATOR_DATABASE_URL"] = database_url
    env["ORCHESTRATOR_PLANNER_MODE"] = "deterministic"
    env["ORCHESTRATOR_EXECUTOR_MODE"] = "deterministic"

    server = _start_server(env=env, port=port, cwd=Path.cwd())
    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


@pytest.fixture
def api_base_url_live_llm() -> Iterator[str]:
    if os.getenv("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
        pytest.skip(
            "Set RUN_POSTGRES_INTEGRATION_TESTS=1 and ORCHESTRATOR_DATABASE_URL "
            "to run integration tests against PostgreSQL."
        )
    database_url = os.getenv("ORCHESTRATOR_DATABASE_URL")
    if not database_url:
        pytest.skip("ORCHESTRATOR_DATABASE_URL is required for integration tests.")
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live LLM integration tests.")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for live LLM integration tests.")

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["ORCHESTRATOR_DATABASE_URL"] = database_url
    env["ORCHESTRATOR_PLANNER_MODE"] = "llm"
    env["ORCHESTRATOR_EXECUTOR_MODE"] = "llm"

    server = _start_server(env=env, port=port, cwd=Path.cwd())
    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def http_post_json(
    base_url: str,
    path: str,
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    raw_payload = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{base_url}{path}",
        method="POST",
        data=raw_payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=20.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body)


def http_get_json(base_url: str, path: str) -> tuple[int, dict[str, object]]:
    req = request.Request(url=f"{base_url}{path}", method="GET")
    try:
        with request.urlopen(req, timeout=20.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body)


@pytest.fixture
def post_json():
    return http_post_json


@pytest.fixture
def get_json():
    return http_get_json
