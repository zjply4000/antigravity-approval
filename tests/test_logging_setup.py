# tests/test_logging_setup.py
import json
from jev_eval.logging_setup import build_audit_logger, audit

def test_audit_writes_one_json_line(tmp_path):
    log = tmp_path / "audit.log"
    logger = build_audit_logger(log)
    audit(logger, tool="run_command", decision="allow", confidence=0.982)
    line = log.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["tool"] == "run_command"
    assert record["decision"] == "allow"
    assert record["confidence"] == 0.982
    assert "ts" in record

def test_build_is_idempotent(tmp_path):
    log = tmp_path / "audit.log"
    a = build_audit_logger(log)
    b = build_audit_logger(log)
    assert a is b
    audit(a, x=1)
    audit(b, x=2)
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2

def test_audit_never_raises(tmp_path, monkeypatch):
    logger = build_audit_logger(tmp_path / "audit.log")
    monkeypatch.setattr(logger, "info", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    audit(logger, tool="x")  # must not raise
