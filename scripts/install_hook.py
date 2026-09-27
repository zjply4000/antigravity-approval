# scripts/install_hook.py
"""Render hooks.template.json to .agents/hooks.json with this machine's venv interpreter."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_HOOKS = ROOT / ".agents" / "hooks.json"
DEFAULT_GLOBAL_HOOKS = Path.home() / ".gemini" / "config" / "hooks.json"

def _cmd_safe(path: str) -> str:
    """Make a path safe for Antigravity's cmd.exe hook spawn.

    Antigravity re-quotes hook commands through cmd.exe (Go's EscapeArg turns
    inner quotes into \\\"), so ANY quoted token fails with "not recognized as
    an internal or external command". Paths without spaces need no quotes;
    paths with spaces are converted to their 8.3 short form when available.
    """
    if " " not in path:
        return path
    if os.name != "nt":
        raise SystemExit(f"ERROR: path contains spaces, which breaks Antigravity's "
                         f"cmd.exe hook spawn: {path}\n"
                         "Install to a space-free location.")
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):
        return buf.value.replace("\\", "/")
    raise SystemExit(f"ERROR: path contains spaces and no 8.3 short name is available: {path}\n"
                     "Antigravity's cmd.exe hook spawn mangles quoted paths; "
                     "reinstall to a space-free location.")

def render(root: Path) -> str:
    template = (root / "hooks.template.json").read_text(encoding="utf-8")
    venv_py = _cmd_safe(venv_python(root).as_posix())
    script = _cmd_safe((root / "scripts" / "jev_evaluator.py").as_posix())
    return (template
            .replace("{{VENV_PYTHON}}", venv_py)
            .replace("{{EVALUATOR_SCRIPT}}", script))

def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def merge_hook(existing_json_str: str, rendered_hook: dict) -> dict:
    """Non-destructively merge jev-evaluator into existing hooks data."""
    if not existing_json_str.strip():
        data = {}
    else:
        try:
            data = json.loads(existing_json_str)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["jev-evaluator"] = rendered_hook["jev-evaluator"]
    return data

def install(
    target_path: Path,
    root: Path = ROOT,
) -> Path:
    """Safely install and merge the Antigravity PreToolUse hook into target_path.

    Creates an original backup `hooks.json.orig.bak` (if not already present)
    and a timestamped backup `hooks.json.<YYYYMMDD_HHMMSS>.bak` before writing.
    Preserves all other third-party hooks in hooks.json.
    """
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    raw = ""
    if target_path.exists():
        orig_bak = target_path.with_name(f"{target_path.name}.orig.bak")
        if not orig_bak.exists():
            shutil.copy2(target_path, orig_bak)

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        ts_bak = target_path.with_name(f"{target_path.name}.{now_str}.bak")
        shutil.copy2(target_path, ts_bak)

        try:
            raw = target_path.read_text(encoding="utf-8")
        except Exception:
            raw = ""

    rendered_dict = json.loads(render(root))
    merged = merge_hook(raw, rendered_dict)
    target_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target_path

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Jev evaluator PreToolUse hook for Antigravity.")
    parser.add_argument("--global", "-g", dest="is_global", action="store_true",
                        help="Install globally to ~/.gemini/config/hooks.json")
    parser.add_argument("--dest", dest="dest", type=Path, default=None,
                        help="Custom destination hooks.json path")
    args = parser.parse_args(argv)

    py = venv_python(ROOT)
    if not py.exists():
        print(f"ERROR: venv interpreter missing: {py}", file=sys.stderr)
        print("Create it with: python -m venv .venv && .venv/Scripts/python.exe -m pip install -e \".[dev]\"",
              file=sys.stderr)
        return 1
    check = subprocess.run([str(py), "-c", "import typesafe_sdk"], capture_output=True)
    if check.returncode != 0:
        print("ERROR: typesafe-sdk is not importable in the venv.", file=sys.stderr)
        print(f"Install it with: {py} -m pip install typesafe-sdk", file=sys.stderr)
        return 1

    if args.dest:
        target = args.dest
    elif args.is_global:
        target = DEFAULT_GLOBAL_HOOKS
    else:
        target = DEFAULT_PROJECT_HOOKS

    out = install(target, ROOT)
    print(f"Successfully installed hook to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
