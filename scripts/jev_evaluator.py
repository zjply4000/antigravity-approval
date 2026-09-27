#!/usr/bin/env python3
"""Antigravity PreToolUse hook: always prints exactly one JSON decision on stdout."""
from __future__ import annotations

import os
import sys
import time

# --- DIAGNOSTIC PROBE (inert unless enabled) --------------------------------
# Lifecycle markers to <script dir>/_hook_probe.log, written before any heavy
# imports, so a GUI-host spawn stall is visible from outside. Active only when
# the log file already exists (create it to enable; delete to disable).
_PROBE_T0 = time.perf_counter()

def _probe(marker: str) -> None:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_hook_probe.log")
        if not os.path.exists(path):
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} +{time.perf_counter() - _PROBE_T0:7.3f}s "
                    f"pid={os.getpid()} {marker}\n")
    except Exception:
        pass

_probe(f"spawned exe={sys.executable!r} argv={sys.argv!r} cwd={os.getcwd()!r}")
# ---------------------------------------------------------------------------

import json
import logging
import threading
import warnings

_probe("stdlib imports done")

warnings.filterwarnings("ignore")

_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

logging.basicConfig(stream=sys.stderr, level=logging.ERROR, force=True)

from jev_eval.config import load_settings, resolve_workspace_dir   # noqa: E402
from jev_eval.decide import Decision, extract_args, finalize_tier2  # noqa: E402
from jev_eval.deterministic import evaluate_tool_call           # noqa: E402
from jev_eval.formatter import format_fallback_reason           # noqa: E402
from jev_eval.jev_client import evaluate_command                # noqa: E402
from jev_eval.logging_setup import audit, build_audit_logger    # noqa: E402
from jev_eval.reader import read_stdin_payload                  # noqa: E402

_probe("jev_eval imports done")

def _emit(payload: dict) -> None:
    # Trailing newline: JSON parses either way, and line-based readers on the
    # host side get the decision without waiting for pipe EOF.
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")

def main() -> int:
    event = "PreToolUse"
    if "--event" in sys.argv:
        idx = sys.argv.index("--event")
        if idx + 1 < len(sys.argv):
            event = sys.argv[idx + 1]
    try:
        raw = read_stdin_payload()
        _probe(f"stdin returned: {'None' if raw is None else f'{len(raw)} bytes'}")
        if raw is None:
            _probe("fail-closed: payload read timeout / empty input")
            _emit({"decision": "ask", "reason": format_fallback_reason("payload read timeout / empty input")})
            return 0
        payload = json.loads(raw) if raw.strip() else {}
        _probe(f"payload parsed: tool={((payload.get('toolCall') or {}).get('name'))!r}")
    except Exception as exc:
        _probe(f"malformed payload: {exc}")
        _emit({"decision": "ask", "reason": format_fallback_reason(f"malformed hook payload: {exc}")})
        return 0
    if event != "PreToolUse":
        _probe(f"event={event!r} -> empty decision")
        _emit({})
        return 0
    try:
        tool_call = payload.get("toolCall") or {}
        tool_name = tool_call.get("name") or ""
        args = tool_call.get("args") or {}
        workspace_paths = payload.get("workspacePaths") or []
        conversation_id = payload.get("conversationId") or ""
        artifact_dir = payload.get("artifactDirectoryPath") or ""

        settings = load_settings(workspace_dir=resolve_workspace_dir(os.getcwd()))
        try:
            logger = build_audit_logger(settings.log_file)
        except Exception:
            logger = None
        ex = extract_args(tool_name, args)
        t1 = evaluate_tool_call(tool_name, ex["command"], ex["cwd"], ex["target"],
                                workspace_paths, settings.allow_network_commands,
                                extra_write_roots=[artifact_dir] if artifact_dir else None,
                                path_policy=settings.path_policy)
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
        _probe(f"decision emitted: {decision.decision} ({decision.reason[:60]})")
    except Exception as exc:
        _probe(f"evaluator crash: {exc}")
        _emit({"decision": "ask", "reason": format_fallback_reason(f"evaluator crash: {exc}")})
    finally:
        sys.stdout.flush()
    return 0

if __name__ == "__main__":
    _code = main()
    sys.stdout.flush()
    _probe(f"os._exit({_code})")
    # The stdin pump daemon may still be blocked in a read, holding the stdin
    # buffer lock; normal interpreter finalization would then abort with
    # "_enter_buffered_busy" (fatal error, ~1s dump, exit != 0). stdout is
    # flushed and the audit record is already written — exit immediately.
    os._exit(_code)
