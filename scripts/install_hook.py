# scripts/install_hook.py
"""Render hooks.template.json to .agents/hooks.json with this machine's venv interpreter."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def render(root: Path) -> str:
    template = (root / "hooks.template.json").read_text(encoding="utf-8")
    venv_py = venv_python(root).as_posix()
    return template.replace("{{VENV_PYTHON}}", venv_py).replace("{{EVALUATOR_DIR}}", root.as_posix())

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
