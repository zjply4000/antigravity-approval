# tests/test_config_multihost.py
from __future__ import annotations

from pathlib import Path
import pytest
from jev_eval.config import load_settings


def test_antigravity_host_ignores_zcode_env(tmp_path):
    zcode_env = tmp_path / ".zcode" / "jev.env"
    zcode_env.parent.mkdir(parents=True)
    zcode_env.write_text("ALLOW_NETWORK_COMMANDS=true\n", encoding="utf-8")

    settings = load_settings(env={}, host="antigravity", workspace_dir=tmp_path)
    assert settings.allow_network_commands is False


def test_zcode_host_reads_zcode_env(tmp_path):
    zcode_env = tmp_path / ".zcode" / "jev.env"
    zcode_env.parent.mkdir(parents=True)
    zcode_env.write_text("ALLOW_NETWORK_COMMANDS=true\n", encoding="utf-8")

    settings = load_settings(env={}, host="zcode", workspace_dir=tmp_path)
    assert settings.allow_network_commands is True


def test_zcode_host_default_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = load_settings(env={}, host="zcode")
    expected = tmp_path / ".zcode" / "cli" / "log" / "jev_evaluator.log"
    assert settings.log_file == expected


def test_antigravity_host_default_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = load_settings(env={}, host="antigravity")
    expected = tmp_path / ".gemini" / "logs" / "jev_evaluator.log"
    assert settings.log_file == expected


def test_zcode_api_key_fallback_to_gemini(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    gemini_env = tmp_path / ".gemini" / "config" / "jev.env"
    gemini_env.parent.mkdir(parents=True)
    gemini_env.write_text("TYPESAFE_API_KEY=fallback-gemini-key\n", encoding="utf-8")

    settings = load_settings(env={}, host="zcode")
    assert settings.api_key == "fallback-gemini-key"


def test_zcode_api_key_zcode_env_beats_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    gemini_env = tmp_path / ".gemini" / "config" / "jev.env"
    gemini_env.parent.mkdir(parents=True)
    gemini_env.write_text("TYPESAFE_API_KEY=fallback-gemini-key\n", encoding="utf-8")

    zcode_env = tmp_path / ".zcode" / "jev.env"
    zcode_env.parent.mkdir(parents=True)
    zcode_env.write_text("TYPESAFE_API_KEY=zcode-specific-key\n", encoding="utf-8")

    settings = load_settings(env={}, host="zcode")
    assert settings.api_key == "zcode-specific-key"


def test_zcode_explicit_user_file(tmp_path):
    custom_env = tmp_path / "custom.env"
    custom_env.write_text("CONFIDENCE_THRESHOLD=0.75\n", encoding="utf-8")

    settings = load_settings(env={}, host="zcode", user_file=custom_env)
    assert settings.confidence_threshold == 0.75


def test_dsh_host_reads_dsh_env(tmp_path):
    dsh_env = tmp_path / ".dsh" / "jev.env"
    dsh_env.parent.mkdir(parents=True)
    dsh_env.write_text("ALLOW_NETWORK_COMMANDS=true\n", encoding="utf-8")

    settings = load_settings(env={}, host="dsh", workspace_dir=tmp_path)
    assert settings.allow_network_commands is True


def test_dsh_host_default_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    settings = load_settings(env={}, host="dsh")
    expected = tmp_path / ".dsh" / "logs" / "jev_evaluator.log"
    assert settings.log_file == expected


def test_dsh_env_beats_gemini_fallback(tmp_path, monkeypatch):
    """DSH 用自己的配置文件；共享内核的 key 只是兜底，不能反过来盖掉本机配置。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    gemini_env = tmp_path / ".gemini" / "config" / "jev.env"
    gemini_env.parent.mkdir(parents=True)
    gemini_env.write_text("TYPESAFE_API_KEY=fallback-gemini-key\n", encoding="utf-8")

    dsh_env = tmp_path / ".dsh" / "jev.env"
    dsh_env.parent.mkdir(parents=True)
    dsh_env.write_text("TYPESAFE_API_KEY=dsh-specific-key\n", encoding="utf-8")

    settings = load_settings(env={}, host="dsh")
    assert settings.api_key == "dsh-specific-key"

