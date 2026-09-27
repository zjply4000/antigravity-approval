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

def test_install_creates_file_and_preserves_existing_keys(tmp_path):
    from install_hook import install
    target = tmp_path / "hooks.json"
    initial_content = {
        "notifier": {"enabled": True, "PreToolUse": []},
        "custom-lint": {"command": "lint.sh"}
    }
    target.write_text(json.dumps(initial_content), encoding="utf-8")
    
    res = install(target, Path(__file__).resolve().parents[1])
    assert res == target
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "jev-evaluator" in data
    assert "notifier" in data
    assert "custom-lint" in data
    assert data["notifier"]["enabled"] is True

def test_install_creates_orig_and_timestamped_backups(tmp_path):
    from install_hook import install
    target = tmp_path / "hooks.json"
    target.write_text(json.dumps({"existing": 1}), encoding="utf-8")

    install(target, Path(__file__).resolve().parents[1])
    orig_bak = target.with_name(f"{target.name}.orig.bak")
    assert orig_bak.exists()
    assert json.loads(orig_bak.read_text(encoding="utf-8")) == {"existing": 1}

    # Run again: orig_bak must NOT be overwritten, new timestamped bak should exist
    target.write_text(json.dumps({"existing": 2}), encoding="utf-8")
    install(target, Path(__file__).resolve().parents[1])
    assert json.loads(orig_bak.read_text(encoding="utf-8")) == {"existing": 1}
    baks = list(tmp_path.glob("hooks.json.*.bak"))
    assert len(baks) >= 1

