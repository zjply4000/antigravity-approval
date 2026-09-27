# tests/test_e2e.py
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jev_evaluator.py"

def _popen_env() -> dict:
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)  # keep tests network-free
    tmp_home = tempfile.mkdtemp()
    env["USERPROFILE"] = tmp_home   # redirect Path.home() on Windows (config + audit log)
    env["HOME"] = tmp_home          # redirect Path.home() on POSIX
    return env

def run_hook(payload: str, extra_env: dict | None = None, importtime: bool = False):
    env = _popen_env()
    env.update(extra_env or {})
    tmp_home = env["HOME"]
    cmd = [sys.executable]
    if importtime:
        cmd.append("-X")
        cmd.append("importtime")
    cmd.append(str(SCRIPT))
    return subprocess.run(cmd, input=payload, capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=tmp_home, timeout=60)

def fixture(name: str) -> str:
    return (ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")

def test_benign_whitelisted_allows_without_network():
    proc = run_hook(fixture("benign.json"))
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)  # stdout must be exactly one JSON object
    assert decision["decision"] == "allow"

def test_destructive_denies():
    proc = run_hook(fixture("destructive.json"))
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "deny"

def test_write_tool_allows_safe_source():
    proc = run_hook(fixture("write_file.json"))
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "allow"
    assert "代码编写" in decision["reason"]

def test_write_tool_sensitive_file_asks():
    payload = json.dumps({
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": "D:/proj/.env", "Content": "SECRET=1"}},
        "workspacePaths": ["D:/proj"],
    })
    proc = run_hook(payload)
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "ask"
    assert "敏感配置" in decision["reason"]

def test_malformed_payload_asks_with_exit_zero():
    proc = run_hook("not json at all")
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "ask"
    assert "malformed" in decision["reason"]

def test_ambiguous_without_api_key_asks_closed():
    payload = fixture("benign.json").replace("git status", "npm test")
    proc = run_hook(payload)
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "ask"

def test_stdout_purity_diagnostics_go_to_stderr():
    proc = run_hook(fixture("benign.json"))
    assert proc.stdout.strip().startswith("{") and proc.stdout.strip().endswith("}")
    json.loads(proc.stdout)  # single object; extra output would break json.loads
    assert "decision" not in proc.stderr

def test_tier1_never_imports_sdk():
    proc = run_hook(fixture("benign.json"), importtime=True)
    assert "typesafe_sdk" not in proc.stderr

def _answer_with_open_stdin(payload: str) -> str:
    """Spawn the hook, deliver the payload, and keep stdin OPEN (no EOF) —
    mirroring the Antigravity GUI host, which never closes the pipe. Returns
    the decision line; fails if the hook does not answer within 5 s."""
    proc = subprocess.Popen([sys.executable, str(SCRIPT)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", env=_popen_env())
    try:
        proc.stdin.write(payload)
        proc.stdin.flush()
        outcome: dict = {}

        def _read():
            outcome["line"] = proc.stdout.readline()

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        reader.join(timeout=5.0)
        assert "line" in outcome, "hook hung: no decision before stdin EOF"
        return outcome["line"]
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        proc.wait(timeout=10)
        assert proc.returncode == 0, f"hook exited {proc.returncode} on held-open stdin"

def test_open_stdin_newline_answers_without_eof():
    """Antigravity sends a minified JSON line and keeps the pipe open."""
    line = _answer_with_open_stdin(fixture("benign.json") + "\n")
    assert json.loads(line)["decision"] == "allow"

def test_open_stdin_burst_without_newline_answers():
    """Antigravity may also send a single burst with NO trailing newline."""
    line = _answer_with_open_stdin(fixture("benign.json"))
    assert json.loads(line)["decision"] == "allow"

def test_outside_workspace_write_asks_under_strategy_c(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()
    payload = json.dumps({
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": str(outside), "Content": "hello"}},
        "workspacePaths": [str(ws)],
    })
    proc = run_hook(payload)
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "ask"
    assert "工作区外部" in decision["reason"]

def test_system_path_write_denies_under_strategy_c(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    sys_path = "C:/Windows/System32/evil.dll" if sys.platform == "win32" else "/etc/evil.conf"
    payload = json.dumps({
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": sys_path, "Content": "evil"}},
        "workspacePaths": [str(ws)],
    })
    proc = run_hook(payload)
    assert proc.returncode == 0
    decision = json.loads(proc.stdout)
    assert decision["decision"] == "deny"
    assert "系统目录或私钥凭据" in decision["reason"]

