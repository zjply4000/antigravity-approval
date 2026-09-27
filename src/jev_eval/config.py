# src/jev_eval/config.py
"""Settings loading: process env > workspace env > user file > defaults."""
from __future__ import annotations

import json
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
    path_policy: str = "strategy_c"

_DEFAULTS: dict[str, str] = {
    "TYPESAFE_BASE_URL": "https://api.typesafe.ai",
    "CONFIDENCE_THRESHOLD": "0.96",
    "EVAL_TIMEOUT_MS": "8000",
    "ALLOW_NETWORK_COMMANDS": "false",
    "JEV_FAIL_MODE": "closed",
    "JEV_LOG_FILE": str(Path.home() / ".gemini" / "logs" / "jev_evaluator.log"),
    "JEV_PATH_POLICY": "strategy_c",
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

def _parse_config_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text) if text.strip() else {}
            if isinstance(data, dict):
                key_map = {
                    "typesafe_api_key": "TYPESAFE_API_KEY",
                    "api_key": "TYPESAFE_API_KEY",
                    "typesafe_base_url": "TYPESAFE_BASE_URL",
                    "base_url": "TYPESAFE_BASE_URL",
                    "confidence_threshold": "CONFIDENCE_THRESHOLD",
                    "eval_timeout_ms": "EVAL_TIMEOUT_MS",
                    "allow_network_commands": "ALLOW_NETWORK_COMMANDS",
                    "fail_mode": "JEV_FAIL_MODE",
                    "log_file": "JEV_LOG_FILE",
                }
                out: dict[str, str] = {}
                for k, v in data.items():
                    if v is not None:
                        val_str = str(v).strip()
                        if val_str and val_str.lower() != "null":
                            target_k = key_map.get(k.lower(), k.upper())
                            out[target_k] = val_str
                return out
        except Exception:
            return {}
    return _parse_env_file(path)

def load_settings(env: Mapping[str, str] | None = None,
                  workspace_dir: Path | str | None = None,
                  user_file: Path | str | None = None,
                  host: str = "antigravity") -> Settings:
    env = dict(os.environ if env is None else env)
    merged = dict(_DEFAULTS)
    ws_path = Path(workspace_dir) if workspace_dir is not None else None

    if host == "zcode":
        merged["JEV_LOG_FILE"] = str(Path.home() / ".zcode" / "cli" / "log" / "jev_evaluator.log")
        z_json = Path.home() / ".zcode" / "jev_approval" / "config.json"
        merged.update(_parse_config_file(z_json))
        z_user = Path(user_file) if user_file else (Path.home() / ".zcode" / "jev.env")
        merged.update(_parse_config_file(z_user))
        if ws_path:
            merged.update(_parse_config_file(ws_path / ".zcode" / "jev_approval" / "config.json"))
            merged.update(_parse_config_file(ws_path / ".zcode" / "jev.env"))
        # Fallback for TYPESAFE_API_KEY only if not present in env or zcode env files
        if not env.get("TYPESAFE_API_KEY") and not merged.get("TYPESAFE_API_KEY"):
            gemini_user = _parse_config_file(Path.home() / ".gemini" / "config" / "jev.env")
            if gemini_user.get("TYPESAFE_API_KEY"):
                merged["TYPESAFE_API_KEY"] = gemini_user["TYPESAFE_API_KEY"]
    else:
        merged["JEV_LOG_FILE"] = str(Path.home() / ".gemini" / "logs" / "jev_evaluator.log")
        a_json = Path.home() / ".antigravity" / "jev_approval" / "config.json"
        merged.update(_parse_config_file(a_json))
        a_user = Path(user_file) if user_file else (Path.home() / ".gemini" / "config" / "jev.env")
        merged.update(_parse_config_file(a_user))
        if ws_path:
            merged.update(_parse_config_file(ws_path / ".agents" / "jev_approval" / "config.json"))
            merged.update(_parse_config_file(ws_path / ".agents" / "jev.env"))

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
        timeout_ms = 8000
    fail_mode = merged["JEV_FAIL_MODE"].strip().lower()
    if fail_mode not in ("closed", "open"):
        fail_mode = "closed"
    path_policy = merged.get("JEV_PATH_POLICY", "strategy_c").strip().lower()
    if path_policy not in ("strategy_c", "strict_deny"):
        path_policy = "strategy_c"
    api_key = env.get("TYPESAFE_API_KEY") or merged.get("TYPESAFE_API_KEY") or None
    return Settings(
        api_key=api_key,
        base_url=merged["TYPESAFE_BASE_URL"],
        confidence_threshold=threshold,
        eval_timeout_ms=timeout_ms,
        allow_network_commands=merged["ALLOW_NETWORK_COMMANDS"].strip().lower() in _TRUE,
        fail_mode=fail_mode,
        log_file=Path(merged["JEV_LOG_FILE"]).expanduser(),
        path_policy=path_policy,
    )

def export_sdk_environ(settings: Settings) -> None:
    """Publish SDK settings as process env BEFORE typesafe_sdk is imported."""
    os.environ["TYPESAFE_API_KEY"] = settings.api_key or ""
    os.environ["TYPESAFE_BASE_URL"] = settings.base_url

def resolve_workspace_dir(cwd: str) -> str:
    """Antigravity spawns hooks with CWD = <workspace>/.agents; the workspace
    root — where .agents/jev.env lives — is that directory's parent."""
    base = os.path.basename(cwd.rstrip("/\\"))
    return os.path.dirname(cwd.rstrip("/\\")) if base == ".agents" else cwd
