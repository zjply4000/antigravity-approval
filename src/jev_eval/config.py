# src/jev_eval/config.py
"""Settings loading: process env > workspace .agents/jev.env > user file > defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_TRUE = {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    confidence_threshold: float
    eval_timeout_ms: int
    allow_network_commands: bool
    fail_mode: str  # "closed" | "open"
    log_file: Path

_DEFAULTS: dict[str, str] = {
    "TYPESAFE_BASE_URL": "https://api.typesafe.ai",
    "CONFIDENCE_THRESHOLD": "0.96",
    "EVAL_TIMEOUT_MS": "1500",
    "ALLOW_NETWORK_COMMANDS": "false",
    "JEV_FAIL_MODE": "closed",
    "JEV_LOG_FILE": str(Path.home() / ".gemini" / "logs" / "jev_evaluator.log"),
}

def _parse_env_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out

def load_settings(env: Mapping[str, str] | None = None,
                  workspace_dir: Path | None = None,
                  user_file: Path | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    merged = dict(_DEFAULTS)
    merged.update(_parse_env_file(user_file or Path.home() / ".gemini" / "config" / "jev.env"))
    if workspace_dir is not None:
        merged.update(_parse_env_file(Path(workspace_dir) / ".agents" / "jev.env"))
    for key in merged:
        if env.get(key):
            merged[key] = env[key]
    try:
        threshold = float(merged["CONFIDENCE_THRESHOLD"])
    except ValueError:
        threshold = 0.96
    if not 0.0 <= threshold <= 1.0:
        threshold = 0.96
    try:
        timeout_ms = max(100, int(merged["EVAL_TIMEOUT_MS"]))
    except ValueError:
        timeout_ms = 1500
    fail_mode = merged["JEV_FAIL_MODE"].strip().lower()
    if fail_mode not in ("closed", "open"):
        fail_mode = "closed"
    api_key = env.get("TYPESAFE_API_KEY") or merged.get("TYPESAFE_API_KEY") or None
    return Settings(
        api_key=api_key,
        base_url=merged["TYPESAFE_BASE_URL"],
        confidence_threshold=threshold,
        eval_timeout_ms=timeout_ms,
        allow_network_commands=merged["ALLOW_NETWORK_COMMANDS"].strip().lower() in _TRUE,
        fail_mode=fail_mode,
        log_file=Path(merged["JEV_LOG_FILE"]).expanduser(),
    )

def export_sdk_environ(settings: Settings) -> None:
    """Publish SDK settings as process env BEFORE typesafe_sdk is imported."""
    os.environ["TYPESAFE_API_KEY"] = settings.api_key or ""
    os.environ["TYPESAFE_BASE_URL"] = settings.base_url
