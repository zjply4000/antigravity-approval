#!/usr/bin/env python3
"""One live Jev call. Manual use only: .venv/Scripts/python.exe scripts/smoke_live.py"""
from __future__ import annotations

import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from jev_eval.config import load_settings
from jev_eval.jev_client import evaluate_command

def main() -> int:
    cwd = os.getcwd()
    settings = load_settings(workspace_dir=cwd)
    if not settings.api_key:
        print("TYPESAFE_API_KEY is not configured (env or ~/.gemini/config/jev.env).",
              file=sys.stderr)
        return 1
    verdict = evaluate_command("npm test", cwd, [cwd], settings)
    if verdict is None:
        print("Tier-2 evaluation returned None (timeout/error/missing key) — "
              "hook would escalate to 'ask'.", file=sys.stderr)
        return 1
    print(f"category={verdict.category} confidence={verdict.confidence:.3f} "
          f"latency_ms={verdict.latency_ms}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
