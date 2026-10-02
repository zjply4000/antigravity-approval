# src/jev_eval/formatter.py
"""Semantic three-part reason badge formatting for Jev and Tier 1 security evaluations."""
from __future__ import annotations

import os

_TIER2_SPECS: dict[str, tuple[str, str]] = {
    "read_only": ("🟢【只读观察 · 低风险】", "查看状态或读取信息"),
    "standard_dev": ("🟡【常规开发 · 中风险】", "修改工作区代码或测试构建"),
    "network_outbound": ("🟠【网络外联 · 需关注】", "访问外部网络或下载依赖"),
    "destructive": ("🔴【高危破坏 · 高风险】", "强制重置或删除数据"),
}


def _pct(val: float) -> str:
    return f"{round(val * 100)}%"


def format_tier2_reason(
    category: str,
    confidence: float,
    threshold: float,
    approvable: bool,
    allow_network: bool,
) -> str:
    """Format a human-facing three-part reason for Tier 2 Jev verdicts."""
    badge, action = _TIER2_SPECS.get(category, ("🟡【动态审查 · 需确认】", "执行待核验操作"))
    conf_str = _pct(confidence)
    thresh_str = _pct(threshold)

    if approvable:
        if confidence >= threshold:
            return f"{badge}{action} | 置信度 {conf_str}"
        return f"{badge}{action} | 置信度 {conf_str} < 放行门槛 {thresh_str}"

    if category == "network_outbound" and not allow_network:
        return f"{badge}{action} | 依网络防护策略需人工确认 (置信度 {conf_str})"
    if category == "destructive":
        return f"{badge}{action} | 依安全策略必须人工确认 (置信度 {conf_str})"
    return f"{badge}{action} | 依安全策略需人工确认 (置信度 {conf_str})"


def format_tier1_reason(tier: str, raw_reason: str, target: str = "", decision: str = "") -> str:
    """Format a human-facing reason for Tier 1 deterministic outcomes."""
    if tier == "safe_source":
        bname = (os.path.basename(target) if target else "") or "源码文件"
        return f"🟢【代码编写 · 自动放行】修改工作区源码文件 ({bname})"

    if tier == "sensitive_file":
        bname = (os.path.basename(target) if target else "") or "敏感资产"
        return f"⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 ({bname}) | 变更关键配置需人工核验"

    if tier == "write_policy":
        base = (os.path.basename(target) if target else "") or "未知文件"
        return f"✏️【未知文件 · 需确认】写入非白名单文件类型 ({base}) | 未知文件类型需人工核验"

    if tier == "path_guard":
        if "missing target path" in raw_reason:
            return "⚠️【参数缺失 · 需核验】文件工具缺少目标路径 | 无法定位写入位置"
        if "system directory" in raw_reason or "sensitive credential" in raw_reason:
            return "⛔【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 | 已强制拦截"
        if "junction" in raw_reason or "symlink" in raw_reason:
            return "🚧【越界防护 · 需确认】软链接或连接点跳出工作区 | 请确认跨目录安全性"
        bname = (os.path.basename(target) if target else "") or "外部文件"
        if decision == "deny":
            return f"🚫【环境隔离 · 越界拦截】写入工作区外部路径 ({bname}) | 禁止修改工作区外部文件"
        return "🚧【越界防护 · 需确认】目标路径位于工作区外部 | 请确认是否允许跨目录操作"

    if tier == "blocklist":
        if "credential" in raw_reason or "secret" in raw_reason:
            return "🚫【安全阻断 · 极高风险】检测到凭据/私钥文件访问 (.env/私钥) | 已强制拦截"
        if "rm" in raw_reason or "delete" in raw_reason:
            return "🚫【安全阻断 · 极高风险】检测到高危递归强删命令 (rm -rf / del /s) | 已强制拦截"
        return f"🚫【安全阻断 · 极高风险】检测到危险操作命令 ({raw_reason}) | 已强制拦截"

    if tier == "network_gate":
        return "🟠【网络外联 · 需关注】命令涉及外部网络请求 | 依网络防护策略需人工确认"

    if tier == "git_force_ask":
        return f"🔴【不可逆 Git · 需确认】检测到破坏性 Git 操作 ({raw_reason}) | 需人工确认"

    if tier == "artifact":
        return "📋【宿主工件 · 自动放行】写入宿主专属对话工件或项目记忆"

    if tier == "whitelist":
        return "🟢【只读观察 · 自动放行】常规只读安全命令"

    return raw_reason


def format_fallback_reason(cause: str | None) -> str:
    """Format a human-facing reason when Jev evaluation fails, times out, or has no key."""
    cause_str = (cause or "").strip()
    if not cause_str or "deadline" in cause_str or "timeout" in cause_str and "empty" not in cause_str:
        return "⚠️【审查降级 · 超时保护】Jev 评估响应超时 (8s) | 触发安全底座转人工确认"
    if "missing" in cause_str and "API_KEY" in cause_str:
        return "⚠️【审查降级 · 配置缺失】未检测到 TYPESAFE_API_KEY | 触发安全底座转人工确认"
    if "empty input" in cause_str or "timeout / empty" in cause_str or "empty or unparsable" in cause_str:
        return "⚠️【审查降级 · 输入异常】读取宿主请求输入超时或为空 (empty input / timeout) | 触发安全底座转人工确认"
    if "malformed" in cause_str:
        return f"⚠️【审查降级 · 格式异常】请求输入格式错误 (malformed: {cause_str}) | 触发安全底座转人工确认"
    return f"⚠️【审查降级 · 执行异常】评估器异常 ({cause_str}) | 触发安全底座转人工确认"
