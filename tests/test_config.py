# tests/test_config.py
from pathlib import Path
from jev_eval.config import load_settings, export_sdk_environ

def test_defaults():
    s = load_settings(env={}, user_file=Path("nonexistent.env"), workspace_dir=None)
    assert s.api_key is None
    assert s.base_url == "https://api.typesafe.ai"
    assert s.confidence_threshold == 0.96
    assert s.eval_timeout_ms == 8000
    assert s.allow_network_commands is False
    assert s.fail_mode == "closed"

def test_env_overrides_everything(tmp_path):
    user = tmp_path / "user.env"
    user.write_text("CONFIDENCE_THRESHOLD=0.5\n")
    s = load_settings(env={"CONFIDENCE_THRESHOLD": "0.99", "TYPESAFE_API_KEY": "sk-test"},
                      user_file=user, workspace_dir=None)
    assert s.confidence_threshold == 0.99
    assert s.api_key == "sk-test"

def test_workspace_file_beats_user_file(tmp_path):
    user = tmp_path / "user.env"; user.write_text("CONFIDENCE_THRESHOLD=0.5\n")
    ws = tmp_path / ".agents"; ws.mkdir()
    (ws / "jev.env").write_text("CONFIDENCE_THRESHOLD=0.8\nALLOW_NETWORK_COMMANDS=true\n")
    s = load_settings(env={}, user_file=user, workspace_dir=tmp_path)
    assert s.confidence_threshold == 0.8
    assert s.allow_network_commands is True

def test_invalid_values_fall_back_to_defaults(tmp_path):
    user = tmp_path / "user.env"
    user.write_text("CONFIDENCE_THRESHOLD=notafloat\nEVAL_TIMEOUT_MS=-5\nJEV_FAIL_MODE=yolo\n")
    s = load_settings(env={}, user_file=user, workspace_dir=None)
    assert s.confidence_threshold == 0.96
    assert s.eval_timeout_ms == 100   # -5 parses but clamps to the 100 ms floor
    assert s.fail_mode == "closed"

def test_non_utf8_env_file_falls_back_to_defaults(tmp_path):
    user = tmp_path / "user.env"
    user.write_bytes("CONFIDENCE_THRESHOLD=0.7\n".encode("utf-16"))
    s = load_settings(env={}, user_file=user, workspace_dir=None)
    assert s.confidence_threshold == 0.96  # unreadable file treated as absent

def test_resolve_workspace_dir_handles_agents_cwd():
    from jev_eval.config import resolve_workspace_dir
    assert resolve_workspace_dir("d:/Projects/ws/.agents") == "d:/Projects/ws"
    assert resolve_workspace_dir("d:/Projects/ws") == "d:/Projects/ws"

def test_json_null_values_do_not_become_none_string(tmp_path):
    json_file = tmp_path / "config.json"
    json_file.write_text('{"typesafe_api_key": null, "eval_timeout_ms": 5000}\n', encoding="utf-8")
    s = load_settings(env={}, user_file=json_file, workspace_dir=None)
    assert s.api_key is None
    assert s.eval_timeout_ms == 5000

