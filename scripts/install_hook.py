# scripts/install_hook.py
"""Render hooks.template.json to .agents/hooks.json with this machine's venv interpreter."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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

def main() -> int:
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
    rendered = render(ROOT)
    json.loads(rendered)  # refuse to write broken JSON
    out = ROOT / ".agents" / "hooks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print("--- global install: paste the block below into ~/.gemini/config/hooks.json ---")
    print(rendered)
    return 0

if __name__ == "__main__":
    sys.exit(main())
