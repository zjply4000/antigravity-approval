# tests/test_install_hook.py
import json
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
    assert str(root.as_posix() + "/.venv/Scripts/python.exe") in cmd
    assert "{{EVALUATOR_DIR}}" not in rendered
