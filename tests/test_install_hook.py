# tests/test_install_hook.py
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from install_hook import render

def test_render_produces_valid_json_with_absolute_path():
    root = Path(__file__).resolve().parents[1]
    rendered = render(root)
    data = json.loads(rendered)
    rule = data["jev-evaluator"]["PreToolUse"][0]
    hook = rule["hooks"][0]
    assert "multi_replace_file_content" in rule["matcher"]
    cmd = hook["command"]
    venv_rel = ".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python"
    assert str(root.as_posix() + "/" + venv_rel) in cmd
    assert "{{VENV_PYTHON}}" not in rendered
    assert "{{EVALUATOR_SCRIPT}}" not in rendered

def test_rendered_command_is_cmd_safe_no_quoted_tokens():
    """Antigravity's cmd.exe hook spawn mangles quoted tokens (Go EscapeArg
    escapes inner quotes, cmd then looks for a program literally named
    \\"D:/...python.exe\\"). Paths without spaces must render unquoted."""
    root = Path(__file__).resolve().parents[1]
    cmd = json.loads(render(root))["jev-evaluator"]["PreToolUse"][0]["hooks"][0]["command"]
    assert '"' not in cmd, f"quoted token breaks Antigravity's cmd spawn: {cmd}"
    assert cmd.endswith("--event PreToolUse")
