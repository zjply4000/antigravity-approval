# src/jev_eval/reader.py
"""Shared non-blocking stdin reader with deadline pump and EOF short-circuit."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import BinaryIO


def read_stdin_payload(deadline_s: float | None = None,
                       stream: BinaryIO | None = None) -> str | None:
    if deadline_s is None:
        try:
            deadline_s = int(os.environ.get("JEV_STDIN_TIMEOUT_MS", "1000")) / 1000.0
        except (ValueError, TypeError):
            deadline_s = 1.0

    in_stream = stream if stream is not None else sys.stdin.buffer
    buffer = bytearray()
    lock = threading.Lock()
    data_event = threading.Event()
    state = {"eof": False}

    def _pump() -> None:
        try:
            while True:
                # read1() if available, else read() for custom stream
                reader = getattr(in_stream, "read1", in_stream.read)
                chunk = reader(65536)
                if not chunk:
                    break
                with lock:
                    buffer.extend(chunk)
                data_event.set()
        except Exception:
            pass  # reader failure -> deadline / fail-closed path
        finally:
            with lock:
                state["eof"] = True
            data_event.set()

    threading.Thread(target=_pump, daemon=True).start()
    deadline = time.monotonic() + deadline_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        data_event.wait(remaining)
        data_event.clear()
        with lock:
            snapshot = bytes(buffer)
            eof = state["eof"]
        if snapshot:
            try:
                json.loads(snapshot.decode("utf-8"))
                return snapshot.decode("utf-8")
            except ValueError:
                pass  # incomplete payload — keep reading until complete or EOF
        if eof:
            # EOF reached: return parsed or decoded
            return snapshot.decode("utf-8", errors="replace") if snapshot else None
