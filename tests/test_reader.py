# tests/test_reader.py
from __future__ import annotations

import io
import json
import time
from typing import BinaryIO
import pytest
from jev_eval.reader import read_stdin_payload


class BlockingStream:
    """Simulates an open pipe that yields initial data and then blocks without EOF."""
    def __init__(self, data: bytes, delay: float = 3.0):
        self._data = data
        self._sent = False
        self._delay = delay

    def read1(self, n: int = 65536) -> bytes:
        if not self._sent:
            self._sent = True
            return self._data
        time.sleep(self._delay)
        return b""

    def read(self, n: int = -1) -> bytes:
        return self.read1(n)


def test_reader_parses_valid_json_on_eof():
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    stream = io.BytesIO((json.dumps(payload) + "\n").encode("utf-8"))
    res = read_stdin_payload(deadline_s=0.5, stream=stream)
    assert res is not None
    assert json.loads(res) == payload


def test_reader_empty_input_returns_none():
    stream = io.BytesIO(b"")
    res = read_stdin_payload(deadline_s=0.1, stream=stream)
    assert res is None


def test_reader_parses_valid_json_without_eof():
    payload = {"toolCall": {"name": "run_command", "args": {"CommandLine": "dir"}}}
    data = json.dumps(payload).encode("utf-8")
    stream = BlockingStream(data, delay=3.0)
    t0 = time.monotonic()
    res = read_stdin_payload(deadline_s=2.0, stream=stream)
    elapsed = time.monotonic() - t0
    assert res is not None
    assert json.loads(res) == payload
    # Must return promptly once valid JSON is parsed, well before stream delay or deadline
    assert elapsed < 0.5


def test_reader_malformed_json_on_eof():
    stream = io.BytesIO(b"this is not json")
    res = read_stdin_payload(deadline_s=0.5, stream=stream)
    assert res == "this is not json"


class HangingStream:
    """Simulates a stream that blocks on read without emitting data."""
    def __init__(self, delay: float = 2.0):
        self._delay = delay

    def read1(self, n: int = 65536) -> bytes:
        time.sleep(self._delay)
        return b""

    def read(self, n: int = -1) -> bytes:
        return self.read1(n)


def test_reader_timeout_on_silent_stream():
    stream = HangingStream(delay=2.0)
    t0 = time.monotonic()
    res = read_stdin_payload(deadline_s=0.2, stream=stream)
    elapsed = time.monotonic() - t0
    assert res is None
    assert elapsed >= 0.18


def test_reader_respects_env_timeout(monkeypatch):
    monkeypatch.setenv("JEV_STDIN_TIMEOUT_MS", "250")
    stream = HangingStream(delay=2.0)
    t0 = time.monotonic()
    res = read_stdin_payload(deadline_s=None, stream=stream)
    elapsed = time.monotonic() - t0
    assert res is None
    assert 0.2 <= elapsed < 0.8

