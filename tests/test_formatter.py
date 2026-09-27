# tests/test_formatter.py
from __future__ import annotations

import pytest
from jev_eval.formatter import (
    format_fallback_reason,
    format_tier1_reason,
    format_tier2_reason,
)

def test_format_tier2_read_only_allowed():
    res = format_tier2_reason("read_only", 0.99, 0.96, approvable=True, allow_network=False)
    assert res == "🟢【只读观察 · 低风险】查看状态或读取信息 | 置信度 99%"

def test_format_tier2_standard_dev_below_threshold():
    res = format_tier2_reason("standard_dev", 0.93, 0.96, approvable=True, allow_network=False)
    assert res == "🟡【常规开发 · 中风险】修改工作区代码或测试构建 | 置信度 93% < 放行门槛 96%"

def test_format_tier2_standard_dev_allowed():
    res = format_tier2_reason("standard_dev", 0.98, 0.96, approvable=True, allow_network=False)
    assert res == "🟡【常规开发 · 中风险】修改工作区代码或测试构建 | 置信度 98%"

def test_format_tier2_destructive_disallowed_by_policy():
    res = format_tier2_reason("destructive", 0.98, 0.96, approvable=False, allow_network=False)
    assert res == "🔴【高危破坏 · 高风险】强制重置或删除数据 | 依安全策略必须人工确认 (置信度 98%)"

def test_format_tier2_network_outbound_disallowed():
    res = format_tier2_reason("network_outbound", 0.95, 0.96, approvable=False, allow_network=False)
    assert res == "🟠【网络外联 · 需关注】访问外部网络或下载依赖 | 依网络防护策略需人工确认 (置信度 95%)"

def test_format_tier2_network_outbound_allowed():
    res = format_tier2_reason("network_outbound", 0.98, 0.96, approvable=True, allow_network=True)
    assert res == "🟠【网络外联 · 需关注】访问外部网络或下载依赖 | 置信度 98%"

def test_format_tier1_write_policy():
    res = format_tier1_reason("write_policy", "unrecognized extension", target="src/data.bin")
    assert res == "✏️【未知文件 · 需确认】写入非白名单文件类型 (data.bin) | 未知文件类型需人工核验"

def test_format_tier1_path_guard_outside_workspace():
    res = format_tier1_reason("path_guard", "target path outside workspace", target="C:/outside/a.txt")
    assert res == "🚧【越界防护 · 需确认】目标路径位于工作区外部 | 请确认是否允许跨目录操作"

def test_format_tier1_path_guard_outside_workspace_deny():
    res = format_tier1_reason("path_guard", "target path outside workspace", target="C:/outside/a.txt", decision="deny")
    assert res == "🚫【环境隔离 · 越界拦截】写入工作区外部路径 (a.txt) | 禁止修改工作区外部文件"

def test_format_tier1_path_guard_system_dir():
    res = format_tier1_reason("path_guard", "target path in system directory or sensitive credential")
    assert res == "⛔【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 | 已强制拦截"

def test_format_tier1_path_guard_missing_target():
    res = format_tier1_reason("path_guard", "file tool missing target path")
    assert res == "⚠️【参数缺失 · 需核验】文件工具缺少目标路径 | 无法定位写入位置"

def test_format_tier1_blocklist_credentials():
    res = format_tier1_reason("blocklist", "credential/secret file access")
    assert res == "🚫【安全阻断 · 极高风险】检测到凭据/私钥文件访问 (.env/私钥) | 已强制拦截"

def test_format_tier1_blocklist_recursive_delete():
    res = format_tier1_reason("blocklist", "rm recursive force")
    assert res == "🚫【安全阻断 · 极高风险】检测到高危递归强删命令 (rm -rf / del /s) | 已强制拦截"

def test_format_tier1_network_gate():
    res = format_tier1_reason("network_gate", "network command: 'curl -I https://api.github.com'")
    assert res == "🟠【网络外联 · 需关注】命令涉及外部网络请求 | 依网络防护策略需人工确认"

def test_format_tier1_artifact():
    res = format_tier1_reason("artifact", "artifact: host-sanctioned conversation artifact")
    assert res == "📋【宿主工件 · 自动放行】写入宿主专属对话工件或项目记忆"

def test_format_tier1_whitelist():
    res = format_tier1_reason("whitelist", "whitelist: read-only command")
    assert res == "🟢【只读观察 · 自动放行】常规只读安全命令"

def test_format_tier1_safe_source():
    r = format_tier1_reason("safe_source", "safe workspace source file", "src/index.ts")
    assert r == "🟢【代码编写 · 自动放行】修改工作区源码文件 (index.ts)"
    r_empty = format_tier1_reason("safe_source", "safe workspace source file")
    assert r_empty == "🟢【代码编写 · 自动放行】修改工作区源码文件 (源码文件)"

def test_format_tier1_sensitive_file():
    r = format_tier1_reason("sensitive_file", "sensitive config", ".env.local")
    assert r == "⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 (.env.local) | 变更关键配置需人工核验"
    r_empty = format_tier1_reason("sensitive_file", "sensitive config")
    assert r_empty == "⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 (敏感资产) | 变更关键配置需人工核验"

def test_format_fallback_deadline():
    res = format_fallback_reason("Jev evaluation deadline exceeded")
    assert res == "⚠️【审查降级 · 超时保护】Jev 评估响应超时 (8s) | 触发安全底座转人工确认"

def test_format_fallback_missing_key():
    res = format_fallback_reason("missing TYPESAFE_API_KEY")
    assert res == "⚠️【审查降级 · 配置缺失】未检测到 TYPESAFE_API_KEY | 触发安全底座转人工确认"

def test_format_fallback_generic():
    res = format_fallback_reason("something went wrong")
    assert res == "⚠️【审查降级 · 执行异常】评估器异常 (something went wrong) | 触发安全底座转人工确认"
