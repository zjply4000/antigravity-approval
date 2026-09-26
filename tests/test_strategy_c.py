# tests/test_strategy_c.py
"""Tests for Strategy C parameterized path protection and arg fallbacks."""
import os
import sys
import pytest

from jev_eval.config import Settings
from jev_eval.decide import Decision, decide, extract_args
from jev_eval.deterministic import (
    _credential_dirs,
    check_file_target,
    evaluate_tool_call,
)


def make_settings(**over):
    base = dict(
        api_key="sk",
        base_url="https://mock",
        confidence_threshold=0.96,
        eval_timeout_ms=1500,
        allow_network_commands=False,
        fail_mode="closed",
        log_file=None,
    )
    base.update(over)
    return Settings(**base)


def test_credential_dirs_contains_ssh_and_gnupg():
    cdirs = _credential_dirs()
    ssh_norm = os.path.normcase(os.path.abspath(os.path.expanduser("~/.ssh")))
    gnupg_norm = os.path.normcase(os.path.abspath(os.path.expanduser("~/.gnupg")))
    assert ssh_norm in cdirs
    assert gnupg_norm in cdirs


def test_system_dir_denied_under_strategy_c(tmp_path):
    ws = str(tmp_path / "workspace")
    system_path = "C:/Windows/System32/drivers/etc/hosts" if sys.platform == "win32" else "/etc/hosts"

    # Under strategy_c, system directory MUST still be hard-denied
    hit_c = check_file_target(system_path, ws, [ws], path_policy="strategy_c")
    assert hit_c is not None
    assert hit_c[0] == "deny"
    assert "system directory or sensitive credential" in hit_c[1]

    # Under strict_deny, also denied
    hit_strict = check_file_target(system_path, ws, [ws], path_policy="strict_deny")
    assert hit_strict is not None
    assert hit_strict[0] == "deny"


def test_credential_file_denied_under_strategy_c(tmp_path):
    ws = str(tmp_path / "workspace")
    ssh_key = os.path.expanduser("~/.ssh/id_rsa")
    gnupg_key = os.path.expanduser("~/.gnupg/secring.gpg")

    for cred in (ssh_key, gnupg_key):
        hit = check_file_target(cred, ws, [ws], path_policy="strategy_c")
        assert hit is not None
        assert hit[0] == "deny"
        assert "system directory or sensitive credential" in hit[1]


def test_regular_outside_workspace_asks_under_strategy_c(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()

    # Under strategy_c: regular outside workspace -> ask
    hit_c = check_file_target(str(outside), str(ws), [str(ws)], path_policy="strategy_c")
    assert hit_c is not None
    assert hit_c[0] == "ask"
    assert hit_c[1] == "target path outside workspace"


def test_regular_outside_workspace_denies_under_strict_deny(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside" / "notes.txt"
    outside.parent.mkdir()

    # Under strict_deny (and default): regular outside workspace -> deny
    hit_default = check_file_target(str(outside), str(ws), [str(ws)])
    assert hit_default is not None
    assert hit_default[0] == "deny"
    assert hit_default[1] == "target path outside workspace"

    hit_strict = check_file_target(str(outside), str(ws), [str(ws)], path_policy="strict_deny")
    assert hit_strict is not None
    assert hit_strict[0] == "deny"
    assert hit_strict[1] == "target path outside workspace"


def test_evaluate_tool_call_strategy_c(tmp_path):
    ws = str(tmp_path / "workspace")
    outside = str(tmp_path / "outside" / "file.py")
    system_path = "C:/Windows/System32/cmd.exe" if sys.platform == "win32" else "/bin/sh"

    # Outside workspace under strategy_c -> Tier1Outcome ask (path_guard)
    out_c = evaluate_tool_call(
        "write_to_file", "", ws, outside, [ws], allow_network=False, path_policy="strategy_c"
    )
    assert out_c is not None
    assert out_c.decision == "ask"
    assert out_c.tier == "path_guard"
    assert out_c.reason == "target path outside workspace"

    # System path under strategy_c -> Tier1Outcome deny (path_guard)
    out_sys = evaluate_tool_call(
        "write_to_file", "", ws, system_path, [ws], allow_network=False, path_policy="strategy_c"
    )
    assert out_sys is not None
    assert out_sys.decision == "deny"
    assert out_sys.tier == "path_guard"
    assert "system directory or sensitive credential" in out_sys.reason

    # Default policy -> deny (path_guard)
    out_default = evaluate_tool_call(
        "write_to_file", "", ws, outside, [ws], allow_network=False
    )
    assert out_default is not None
    assert out_default.decision == "deny"
    assert out_default.tier == "path_guard"


def test_decide_respects_path_policy(tmp_path):
    ws = str(tmp_path / "workspace")
    outside = str(tmp_path / "outside" / "script.py")
    system_path = "C:/Windows/notepad.exe" if sys.platform == "win32" else "/usr/bin/python3"
    settings = make_settings()

    # strategy_c on regular outside -> ask
    d_c = decide(
        "write_to_file",
        {"target": outside},
        [ws],
        settings,
        None,
        path_policy="strategy_c",
    )
    assert d_c.decision == "ask"
    assert d_c.tier == "path_guard"
    assert d_c.reason == "target path outside workspace"

    # strategy_c on system path -> deny
    d_sys = decide(
        "write_to_file",
        {"target": system_path},
        [ws],
        settings,
        None,
        path_policy="strategy_c",
    )
    assert d_sys.decision == "deny"
    assert d_sys.tier == "path_guard"
    assert "system directory or sensitive credential" in d_sys.reason

    # default (strict_deny) on regular outside -> deny
    d_strict = decide(
        "write_to_file",
        {"TargetFile": outside},
        [ws],
        settings,
        None,
    )
    assert d_strict.decision == "deny"
    assert d_strict.tier == "path_guard"


def test_extract_args_path_and_target_fallbacks():
    # 'path' fallback
    ex_path = extract_args("write_to_file", {"path": "C:/ws/foo.py"})
    assert ex_path["target"] == "C:/ws/foo.py"

    # 'target' fallback
    ex_target = extract_args("replace_file_content", {"target": "C:/ws/bar.py"})
    assert ex_target["target"] == "C:/ws/bar.py"

    # Priority check: TargetFile should beat path and target
    ex_prio = extract_args(
        "multi_replace_file_content",
        {"TargetFile": "C:/ws/primary.py", "path": "C:/ws/secondary.py", "target": "C:/ws/third.py"},
    )
    assert ex_prio["target"] == "C:/ws/primary.py"

    # AbsolutePath beats path
    ex_abs = extract_args(
        "write_to_file",
        {"AbsolutePath": "C:/ws/primary.py", "path": "C:/ws/secondary.py"},
    )
    assert ex_abs["target"] == "C:/ws/primary.py"
