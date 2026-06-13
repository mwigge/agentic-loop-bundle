#!/usr/bin/env python3
"""Unit tests for the streaming subprocess runner used by run_agent/run_verification."""

from __future__ import annotations

import importlib.util
import io
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "loopctl", ROOT / "runtime" / "loopctl.py"
)
assert SPEC and SPEC.loader
loopctl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = loopctl
SPEC.loader.exec_module(loopctl)


def test_stream_subprocess_streams_and_captures_output() -> None:
    captured_err = io.StringIO()
    with mock.patch("sys.stderr", captured_err):
        result = loopctl.stream_subprocess("printf 'line1\\nline2\\n'", "demo", None, 5)
    assert result.returncode == 0
    assert result.stdout == "line1\nline2\n"
    live_output = captured_err.getvalue()
    assert "[demo] line1" in live_output
    assert "[demo] line2" in live_output


def test_stream_subprocess_forwards_stdin_prompt() -> None:
    with mock.patch("sys.stderr", io.StringIO()):
        result = loopctl.stream_subprocess("cat", "demo", "hello world", 5)
    assert result.returncode == 0
    assert result.stdout == "hello world"


def test_stream_subprocess_emits_heartbeat_when_idle() -> None:
    captured_err = io.StringIO()
    with (
        mock.patch("sys.stderr", captured_err),
        mock.patch.object(loopctl, "HEARTBEAT_SECONDS", 0.05),
    ):
        result = loopctl.stream_subprocess("sleep 0.3", "demo", None, 5)
    assert result.returncode == 0
    assert "[demo] still running" in captured_err.getvalue()


def test_stream_subprocess_times_out_and_kills_process() -> None:
    with mock.patch("sys.stderr", io.StringIO()):
        try:
            loopctl.stream_subprocess("sleep 5", "demo", None, 0.2)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError("expected TimeoutExpired for a slow command")


def test_run_verification_writes_combined_output() -> None:
    with tempfile.TemporaryDirectory() as run_dir_name:
        run_dir = pathlib.Path(run_dir_name)
        telemetry = loopctl.OpenTelemetry(
            loopctl.JsonlTelemetry("test-run", run_dir, {}), "test-service"
        )
        output_path = run_dir / "verify.txt"
        with mock.patch("sys.stderr", io.StringIO()):
            code = loopctl.run_verification(
                telemetry, "printf out; printf err >&2", output_path, 5
            )
        assert code == 0
        content = output_path.read_text()
        assert "out" in content
        assert "err" in content


def test_run_agent_writes_stdout_and_stderr_files() -> None:
    with tempfile.TemporaryDirectory() as run_dir_name:
        run_dir = pathlib.Path(run_dir_name)
        telemetry = loopctl.OpenTelemetry(
            loopctl.JsonlTelemetry("test-run", run_dir, {}), "test-service"
        )
        output_path = run_dir / "agent.txt"
        with mock.patch("sys.stderr", io.StringIO()):
            code = loopctl.run_agent(
                telemetry,
                "cat; printf 'warn\\n' >&2",
                "implement",
                "hello\n",
                output_path,
                5,
            )
        assert code == 0
        assert output_path.read_text() == "hello\n"
        assert output_path.with_suffix(".stderr.txt").read_text() == "warn\n"


def main() -> int:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("loopctl stream tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
