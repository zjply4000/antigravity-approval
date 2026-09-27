# src/jev_eval/decide.py
"""Pure tiered decision matrix (spec §5). No I/O."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .deterministic import evaluate_tool_call
from .jev_client import Verdict

@dataclass(frozen=True)
class Decision:
    decision: str   # allow | deny | ask | force_ask
    reason: str
    tier: str       # blocklist | whitelist | path_guard | network_gate | write_policy | artifact | jev | fallback
    category: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None

def extract_args(tool_name: str, args: dict) -> dict:
    args = args or {}

    def pick(*keys: str) -> str:
        for key in keys:
            value = args.get(key)
            if value:
                # Antigravity's planner wraps arg values in literal quotes
                # (observed: CommandLine='"git status; git log -n 5"'); one
                # wrapping layer is stripped so tokenization sees the command.
                text = str(value).strip()
                if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
                    text = text[1:-1].strip()
                return text
        return ""

    if tool_name == "run_command":
        return {"command": pick("CommandLine", "command"),
                "cwd": pick("Cwd", "cwd"), "target": ""}
    if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
        return {"command": "", "cwd": pick("Cwd", "cwd"),
                "target": pick("TargetFile", "AbsolutePath", "target_file", "file_path", "filePath", "path", "target")}
    return {"command": "", "cwd": "", "target": ""}

from .formatter import format_fallback_reason, format_tier2_reason

def finalize_tier2(settings: Settings, verdict: Verdict | None,
                   cause: str | None = None) -> Decision:
    """Matrix rows 5, 6, 8. `cause` carries the tier-2 failure reason when verdict is None."""
    if verdict is None:
        fallback_msg = format_fallback_reason(cause)
        if settings.fail_mode == "open":
            return Decision("allow",
                            f"JEV_FAIL_MODE=open: {fallback_msg}",
                            "fallback")
        return Decision("ask", fallback_msg, "fallback")
    approvable = (verdict.category in ("read_only", "standard_dev")
                  or (verdict.category == "network_outbound" and settings.allow_network_commands))
    reason = format_tier2_reason(
        verdict.category,
        verdict.confidence,
        settings.confidence_threshold,
        approvable=approvable,
        allow_network=settings.allow_network_commands,
    )
    if approvable and verdict.confidence >= settings.confidence_threshold:
        return Decision("allow", reason, "jev", verdict.category, verdict.confidence,
                        verdict.latency_ms)
    return Decision("ask", reason, "jev",
                    verdict.category, verdict.confidence, verdict.latency_ms)

def decide(tool_name: str, raw_args: dict, workspace_paths: list[str], settings: Settings,
           verdict: Verdict | None, cause: str | None = None,
           extra_write_roots: list[str] | None = None,
           path_policy: str = "strict_deny") -> Decision:
    """Pure pipeline: Tier 1 then Tier 2. `cause` is the tier-2 failure reason (verdict None)."""
    ex = extract_args(tool_name, raw_args)
    t1 = evaluate_tool_call(tool_name, ex["command"], ex["cwd"], ex["target"],
                            workspace_paths, settings.allow_network_commands,
                            extra_write_roots=extra_write_roots,
                            path_policy=path_policy)
    if t1 is not None:
        return Decision(t1.decision, t1.reason, t1.tier)
    if tool_name == "run_command":
        return finalize_tier2(settings, verdict, cause)
    return Decision("ask", f"unhandled tool {tool_name!r}", "fallback")
