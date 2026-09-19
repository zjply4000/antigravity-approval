#!/usr/bin/env python3
"""Bisection stub C: drains stdin exactly like jev_evaluator (pump thread),
then allows immediately. Isolates the stdin-draining behavior from evaluation
latency. Never reads the network; exits via os._exit like the real hook."""
import os
import sys
import threading

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
done.wait(timeout=2.0)  # payload arrives in one burst; don't wait for EOF

sys.stdout.write('{"decision": "allow", "reason": "stub C: drains stdin"}\n')
sys.stdout.flush()
os._exit(0)
