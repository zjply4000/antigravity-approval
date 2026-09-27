# tests/test_logging_setup.py
import json
import logging
import logging.handlers
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

def test_binds_requested_file_when_foreign_handlers_present(tmp_path):
    # Test runners attach their own capture handlers to this module-level
    # logger; binding must not short-circuit on a non-empty handler list.
    logger = logging.getLogger("jev_eval.audit")
    foreign = logging.NullHandler()
    logger.addHandler(foreign)
    log = tmp_path / "audit.log"
    try:
        build_audit_logger(log)
        audit(logger, marker="bound-under-foreign")
        assert "bound-under-foreign" in log.read_text(encoding="utf-8")
        assert foreign in logger.handlers  # foreign handlers are left alone
    finally:
        logger.removeHandler(foreign)

def test_rebinds_when_requested_path_changes(tmp_path):
    logger = logging.getLogger("jev_eval.audit")
    first = tmp_path / "first.log"
    build_audit_logger(first)
    audit(logger, marker="to-first")
    assert "to-first" in first.read_text(encoding="utf-8")

    second = tmp_path / "second.log"
    build_audit_logger(second)
    audit(logger, marker="to-second")
    assert "to-second" in second.read_text(encoding="utf-8")
    assert "to-second" not in first.read_text(encoding="utf-8")
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert [h.baseFilename for h in file_handlers] == [str(second)]
