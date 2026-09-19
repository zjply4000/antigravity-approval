#!/usr/bin/env python3
"""Bisection stub D: drains stdin (like stub C) plus a 300 ms delay before
answering. Isolates answer latency: if Antigravity honors this stub but not
the real hook (~80 ms), latency is not the mechanism; if it ignores this one
too while honoring faster stubs, Antigravity's read window is the cause."""
import os
import sys
import threading
import time

buffer = bytearray()
lock = threading.Lock()
done = threading.Event()

def _pump() -> None:
    try:
        while True:
            chunk = sys.stdin.buffer.read1(65536)
            if not chunk:
                break
            with lock:
                buffer.extend(chunk)
    except Exception:
        pass
    finally:
        done.set()

threading.Thread(target=_pump, daemon=True).start()
done.wait(timeout=2.0)
time.sleep(0.3)

sys.stdout.write('{"decision": "allow", "reason": "stub D: drains stdin + 300ms delay"}\n')
sys.stdout.flush()
os._exit(0)
