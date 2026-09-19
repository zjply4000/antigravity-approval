# tests/test_e2e.py
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jev_evaluator.py"

def run_hook(payload: str, extra_env: dict | None = None, importtime: bool = False):
    env = dict(os.environ)
    env.pop("TYPESAFE_API_KEY", None)  # keep tests network-free
    env.update(extra_env or {})
    tmp_home = tempfile.mkdtemp()
    env["USERPROFILE"] = tmp_home   # redirect Path.home() on Windows (config + audit log)
    env["HOME"] = tmp_home          # redirect Path.home() on POSIX
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

def test_write_tool_asks():
    proc = run_hook(fixture("write_file.json"))
    assert json.loads(proc.stdout)["decision"] == "ask"

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
