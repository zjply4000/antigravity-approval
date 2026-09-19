#!/usr/bin/env python3
"""Antigravity PreToolUse hook: always prints exactly one JSON decision on stdout."""
from __future__ import annotations

import json
import logging
import os
import sys
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

def main() -> int:
    event = "PreToolUse"
    if "--event" in sys.argv:
        idx = sys.argv.index("--event")
        if idx + 1 < len(sys.argv):
            event = sys.argv[idx + 1]
    try:
        raw = sys.stdin.read()
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
            verdict = evaluate_command(ex["command"], ex["cwd"], workspace_paths, settings)
            decision = finalize_tier2(settings, verdict)
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
    sys.exit(main())
