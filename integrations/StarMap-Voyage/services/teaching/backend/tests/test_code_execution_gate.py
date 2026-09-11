import asyncio
import sys

import pytest
from fastapi import HTTPException

import api_server


def test_run_code_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("STARMAP_ENABLE_CODE_EXECUTION", raising=False)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("subprocess must not run while code execution is disabled")

    monkeypatch.setattr(api_server.subprocess, "run", unexpected_run)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_server.run_code(code="print('hello')", file=None))

    assert exc_info.value.status_code == 403
    assert "STARMAP_ENABLE_CODE_EXECUTION" in exc_info.value.detail


def test_run_code_uses_current_python_when_enabled(monkeypatch):
    monkeypatch.setenv("STARMAP_ENABLE_CODE_EXECUTION", "true")
    invocation = {}

    class Result:
        stdout = "hello\n"
        stderr = ""
        returncode = 0

    def fake_run(command, **kwargs):
        invocation["command"] = command
        return Result()

    monkeypatch.setattr(api_server.subprocess, "run", fake_run)

    response = asyncio.run(api_server.run_code(code="print('hello')", file=None))

    assert invocation["command"][0] == sys.executable
    assert response["stdout"] == "hello\n"
