#!/usr/bin/env python3
"""Antigravity PreToolUse hook: always prints exactly one JSON decision on stdout."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")

_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

logging.basicConfig(stream=sys.stderr, level=logging.ERROR, force=True)

from jev_eval.config import load_settings                       # noqa: E402
from jev_eval.decide import Decision, extract_args, finalize_tier2  # noqa: E402
from jev_eval.deterministic import evaluate_tool_call           # noqa: E402
from jev_eval.jev_client import evaluate_command                # noqa: E402
from jev_eval.logging_setup import audit, build_audit_logger    # noqa: E402

def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True))

# GUI hosts (Electron/VS Code subprocesses) may keep the write end of the stdin
# pipe open after delivering the payload, so EOF-terminated reads hang forever.
_READ_DEADLINE_S = 1.0

def _read_stdin_payload(deadline_s: float) -> str | None:
    """Collect the hook payload without waiting for pipe EOF.

    Reads incrementally in a daemon thread and returns as soon as the buffer
    parses as a complete JSON document — no strict prefix of a top-level JSON
    object is valid, so the first successful parse means the payload is
    complete, regardless of newlines or pipe state. Returns the raw text on
    EOF even when unparseable (caller reports "malformed hook payload");
    returns None on deadline, empty input, or reader failure (caller fails
    closed with "payload read timeout / empty input").
    """
    buffer = bytearray()
    lock = threading.Lock()
    data_event = threading.Event()
    state = {"eof": False}

    def _pump() -> None:
        try:
            stream = sys.stdin.buffer
            while True:
                chunk = stream.read1(65536)
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
            return snapshot.decode("utf-8", errors="replace") if snapshot else None

def main() -> int:
    event = "PreToolUse"
    if "--event" in sys.argv:
        idx = sys.argv.index("--event")
        if idx + 1 < len(sys.argv):
            event = sys.argv[idx + 1]
    try:
        raw = _read_stdin_payload(_READ_DEADLINE_S)
        if raw is None:
            _emit({"decision": "ask", "reason": "payload read timeout / empty input"})
            return 0
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        _emit({"decision": "ask", "reason": f"malformed hook payload: {exc}"})
        return 0
    if event != "PreToolUse":
        _emit({})
        return 0
    try:
        tool_call = payload.get("toolCall") or {}
        tool_name = tool_call.get("name") or ""
        args = tool_call.get("args") or {}
        workspace_paths = payload.get("workspacePaths") or []
        conversation_id = payload.get("conversationId") or ""

        settings = load_settings(workspace_dir=os.getcwd())
        logger = build_audit_logger(settings.log_file)
        ex = extract_args(tool_name, args)
        t1 = evaluate_tool_call(tool_name, ex["command"], ex["cwd"], ex["target"],
                                workspace_paths, settings.allow_network_commands)
        if t1 is not None:
            decision = Decision(t1.decision, t1.reason, t1.tier)
        elif tool_name == "run_command":
            verdict, cause = evaluate_command(ex["command"], ex["cwd"], workspace_paths, settings)
            decision = finalize_tier2(settings, verdict, cause)
        else:
            decision = Decision("ask", f"unhandled tool {tool_name!r}", "fallback")
        audit(logger, conversationId=conversation_id, tool=tool_name,
              input=(ex["command"] or ex["target"])[:200], tier=decision.tier,
              decision=decision.decision, reason=decision.reason,
              category=decision.category, confidence=decision.confidence,
              latency_ms=decision.latency_ms, fail_mode=settings.fail_mode)
        _emit({"decision": decision.decision, "reason": decision.reason})
    except Exception as exc:
        _emit({"decision": "ask", "reason": f"evaluator crash: {exc}"})
    finally:
        sys.stdout.flush()
    return 0

if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    # The stdin pump daemon may still be blocked in a read, holding the stdin
    # buffer lock; normal interpreter finalization would then abort with
    # "_enter_buffered_busy" (fatal error, ~1s dump, exit != 0). stdout is
    # flushed and the audit record is already written — exit immediately.
    os._exit(_code)
