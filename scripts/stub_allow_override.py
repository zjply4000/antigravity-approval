#!/usr/bin/env python3
"""Bisection stub F: allow WITH an explicit permissionOverrides entry.

The hooks doc's own example pairs a decision with `permissionOverrides`
(e.g. ["command(npm test)"]). Hypothesis: this build only honors `allow`
when the hook declares which permission it grants. This stub drains stdin
(briefly), extracts the command from the payload, and returns allow +
permissionOverrides naming that exact command."""
import json
import os
import sys
import threading

buffer = bytearray()
done = threading.Event()

def _pump() -> None:
    try:
        while True:
            chunk = sys.stdin.buffer.read1(65536)
            if not chunk:
                break
            buffer.extend(chunk)
    except Exception:
        pass
    finally:
        done.set()

threading.Thread(target=_pump, daemon=True).start()
done.wait(timeout=2.0)

command = ""
try:
    payload = json.loads(bytes(buffer).decode("utf-8", errors="replace"))
    tool_call = payload.get("toolCall") or {}
    args = tool_call.get("args") or {}
    command = str(args.get("CommandLine") or args.get("command") or "").strip()
    if len(command) >= 2 and command[0] == command[-1] and command[0] in "\"'":
        command = command[1:-1]
except Exception:
    pass

out = {"decision": "allow", "reason": "stub F: allow + permissionOverride"}
if command:
    out["permissionOverrides"] = [f"command({command})"]
sys.stdout.write(json.dumps(out) + "\n")
sys.stdout.flush()
os._exit(0)
