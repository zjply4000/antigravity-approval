# Semantic Reason Badges & Risk Indication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw technical Jev decision strings (`conf=0.930 below threshold or disallowed category` and `file mutations are not auto-approved in v1`) with semantic three-part reason badges (e.g. `🟡【常规开发 · 中风险】修改工作区代码或测试构建 | 置信度 93% < 放行门槛 96%`) across Antigravity and ZCode.

**Architecture:** Introduce a pure, zero-dependency `src/jev_eval/formatter.py` module in the shared core (`antigravity-approval`). Integrate this formatter into `decide.py` and `deterministic.py` so that all human-facing `reason` strings are standardized while preserving structured machine fields in audit logs.

**Tech Stack:** Python 3.10+, pytest, standard library (`os`, `pathlib`, `typing`, `math`).

## Global Constraints

- 优先使用utf-8编码读取文件。
- 不要自动提交修改 (Do NOT auto-commit; commits only upon explicit user request).
- Backward compatibility: All structured fields in `jev_evaluator.log` (`category`, `confidence`, `tier`, `decision`, `latency_ms`) must remain untouched.
- Dual host compatibility: Both `antigravity-approval` and `zcode-approval` test suites must pass 100% with 0 regressions.

---

### Task 1: New Module `src/jev_eval/formatter.py` & Comprehensive Unit Tests

**Files:**
- Create: `src/jev_eval/formatter.py`
- Test: `tests/test_formatter.py`

**Interfaces:**
- Produces:
  - `format_tier2_reason(category: str, confidence: float, threshold: float, approvable: bool, allow_network: bool) -> str`
  - `format_tier1_reason(tier: str, raw_reason: str, target: str = "") -> str`
  - `format_fallback_reason(cause: str | None) -> str`

- [ ] **Step 1: Write the failing unit tests for `formatter.py`**

Create `tests/test_formatter.py`:
```python
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
    res = format_tier1_reason("write_policy", "file mutations are not auto-approved in v1", target="src/app.py")
    assert res == "✏️【代码变更 · 需确认】写入项目文件 (app.py) | 变更项目代码需人工核验"

def test_format_tier1_path_guard_outside_workspace():
    res = format_tier1_reason("path_guard", "target path outside workspace", target="C:/outside/a.txt")
    assert res == "🚧【越界防护 · 需确认】目标路径位于工作区外部 | 请确认是否允许跨目录操作"

def test_format_tier1_path_guard_system_dir():
    res = format_tier1_reason("path_guard", "target path in system directory or sensitive credential")
    assert res == "🚫【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 | 已强制拦截"

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

def test_format_fallback_deadline():
    res = format_fallback_reason("Jev evaluation deadline exceeded")
    assert res == "⚠️【审查降级 · 超时保护】Jev 评估响应超时 (8s) | 触发安全底座转人工确认"

def test_format_fallback_missing_key():
    res = format_fallback_reason("missing TYPESAFE_API_KEY")
    assert res == "⚠️【审查降级 · 配置缺失】未检测到 TYPESAFE_API_KEY | 触发安全底座转人工确认"

def test_format_fallback_generic():
    res = format_fallback_reason("something went wrong")
    assert res == "⚠️【审查降级 · 执行异常】评估器异常 (something went wrong) | 触发安全底座转人工确认"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe tests/test_formatter.py`  
Expected: FAIL with `ModuleNotFoundError: No module named 'jev_eval.formatter'`

- [ ] **Step 3: Implement `src/jev_eval/formatter.py`**

Create `src/jev_eval/formatter.py`:
```python
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


def format_tier1_reason(tier: str, raw_reason: str, target: str = "") -> str:
    """Format a human-facing reason for Tier 1 deterministic outcomes."""
    if tier == "write_policy":
        base = os.path.basename(target) if target else "代码文件"
        return f"✏️【代码变更 · 需确认】写入项目文件 ({base}) | 变更项目代码需人工核验"

    if tier == "path_guard":
        if "system directory" in raw_reason:
            return "🚫【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 | 已强制拦截"
        if "junction" in raw_reason or "symlink" in raw_reason:
            return "🚧【越界防护 · 需确认】软链接或连接点跳出工作区 | 请确认跨目录安全性"
        return "🚧【越界防护 · 需确认】目标路径位于工作区外部 | 请确认是否允许跨目录操作"

    if tier == "blocklist":
        if "credential" in raw_reason or "secret" in raw_reason:
            return "🚫【安全阻断 · 极高风险】检测到凭据/私钥文件访问 (.env/私钥) | 已强制拦截"
        if "rm" in raw_reason or "delete" in raw_reason:
            return "🚫【安全阻断 · 极高风险】检测到高危递归强删命令 (rm -rf / del /s) | 已强制拦截"
        return f"🚫【安全阻断 · 极高风险】检测到危险操作命令 ({raw_reason}) | 已强制拦截"

    if tier == "network_gate":
        return "🟠【网络外联 · 需关注】命令涉及外部网络请求 | 依网络防护策略需人工确认"

    if tier == "artifact":
        return "📋【宿主工件 · 自动放行】写入宿主专属对话工件或项目记忆"

    if tier == "whitelist":
        return "🟢【只读观察 · 自动放行】常规只读安全命令"

    return raw_reason


def format_fallback_reason(cause: str | None) -> str:
    """Format a human-facing reason when Jev evaluation fails, times out, or has no key."""
    cause_str = (cause or "").strip()
    if not cause_str or "deadline" in cause_str or "timeout" in cause_str:
        return "⚠️【审查降级 · 超时保护】Jev 评估响应超时 (8s) | 触发安全底座转人工确认"
    if "missing" in cause_str and "API_KEY" in cause_str:
        return "⚠️【审查降级 · 配置缺失】未检测到 TYPESAFE_API_KEY | 触发安全底座转人工确认"
    if "empty input" in cause_str or "timeout / empty" in cause_str:
        return "⚠️【审查降级 · 输入异常】读取宿主请求输入超时或为空 | 触发安全底座转人工确认"
    return f"⚠️【审查降级 · 执行异常】评估器异常 ({cause_str}) | 触发安全底座转人工确认"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe tests/test_formatter.py -v`  
Expected: PASS with all tests passing.

---

### Task 2: Core Integration & Existing Test Suite Alignment in `antigravity-approval`

**Files:**
- Modify: `src/jev_eval/decide.py`
- Modify: `src/jev_eval/deterministic.py`
- Test: `tests/test_decide.py`
- Test: `tests/test_deterministic.py`
- Test: `tests/test_e2e.py`

**Interfaces:**
- Consumes: `format_tier1_reason`, `format_tier2_reason`, `format_fallback_reason` from `jev_eval.formatter`
- Produces: Updated `Decision.reason` and `Tier1Outcome.reason`

- [ ] **Step 1: Integrate formatter into `src/jev_eval/decide.py`**

In `src/jev_eval/decide.py`:
- Import `format_fallback_reason`, `format_tier2_reason` from `jev_eval.formatter`.
- In `finalize_tier2`:
  - When `verdict is None`:
    - `reason = format_fallback_reason(cause)`
    - Return `Decision("ask", reason, "fallback")` (or open mode logic).
  - When `verdict is not None`:
    - Compute `approvable = (verdict.category in ("read_only", "standard_dev") or (verdict.category == "network_outbound" and settings.allow_network_commands))`
    - `decision_type = "allow" if (approvable and verdict.confidence >= settings.confidence_threshold) else "ask"`
    - `reason = format_tier2_reason(verdict.category, verdict.confidence, settings.confidence_threshold, approvable, settings.allow_network_commands)`
    - Return `Decision(decision_type, reason, "jev", verdict.category, verdict.confidence, verdict.latency_ms)`

- [ ] **Step 2: Integrate formatter into `src/jev_eval/deterministic.py`**

In `src/jev_eval/deterministic.py`:
- Import `format_tier1_reason` from `jev_eval.formatter`.
- In `evaluate_tool_call`:
  - For file tools (`_FILE_TOOLS`):
    - When `hit is not None`:
      `return Tier1Outcome(hit.decision, format_tier1_reason("path_guard", hit.reason, target), "path_guard")`
    - When `_is_sanctioned_artifact(target, cwd, extra_write_roots)`:
      `return Tier1Outcome("allow", format_tier1_reason("artifact", "artifact: host-sanctioned conversation artifact", target), "artifact")`
    - Otherwise (`write_policy`):
      `return Tier1Outcome("ask", format_tier1_reason("write_policy", "file mutations are not auto-approved in v1", target), "write_policy")`
  - For `run_command`:
    - On blocklist hit:
      `return Tier1Outcome("deny", format_tier1_reason("blocklist", bl, ""), "blocklist")`
    - On network gate hit:
      `return Tier1Outcome("force_ask", format_tier1_reason("network_gate", net_reason, ""), "network_gate")`
    - On whitelist hit:
      `return Tier1Outcome("allow", format_tier1_reason("whitelist", "whitelist: read-only command", ""), "whitelist")`

- [ ] **Step 3: Update existing assertions in `tests/test_decide.py`, `tests/test_deterministic.py`, `tests/test_e2e.py`**

- Update reason substring assertions to match the new semantic prefixes (e.g. `assert "【代码变更 · 需确认】" in out.reason`, `assert "【高危破坏 · 高风险】" in d.reason`).
- Verify that tier names, decision outputs (`allow`, `deny`, `ask`, `force_ask`), and numeric fields remain completely preserved.

- [ ] **Step 4: Run full test suite in `antigravity-approval`**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe -v`  
Expected: All tests pass (105+ tests).

---

### Task 3: Dual-Host Alignment & End-to-End Verification in `zcode-approval`

**Files:**
- Modify: `tests/test_zcode_adapter.py` in `zcode-approval`
- Modify: `tests/test_e2e.py` in `zcode-approval`

**Interfaces:**
- Consumes: Updated `jev_eval` core via editable install `d:\Projects\Jev\antigravity-approval`
- Produces: 100% clean test passes on both hosts

- [ ] **Step 1: Check reason assertions in `zcode-approval` tests**

Inspect `zcode-approval/tests/test_zcode_adapter.py` and `test_e2e.py`:
- In `test_zcode_adapter.py`: check where `permissionDecisionReason` substrings are asserted (e.g. `"outside workspace"`, `"system directory"`, `"artifact"`).
- Update any exact string matches to match the new semantic formats while preserving invariant substring checks:
  - `"outside workspace"` -> still contains `"外部"` or `"越界防护"`
  - `"system directory"` -> still contains `"系统目录"` or `"安全阻断"`
  - `"artifact"` -> matches `"宿主工件"` or `"artifact"` (note: `format_zcode_output` in `zcode_evaluator.py` passes the formatted reason through).

- [ ] **Step 2: Run full test suite in `zcode-approval`**

Run: `d:\Projects\Jev\zcode-approval\.venv\Scripts\pytest.exe -v`  
Expected: All 46+ tests pass cleanly.

- [ ] **Step 3: Live end-to-end verification**

Run a sample evaluation on both hosts using a test command:
- Simulate `standard_dev` (e.g. `git commit -m "..."`) -> verify reason output is `🟡【常规开发 · 中风险】...`.
- Simulate `Write` on `tests/test_demo.py` -> verify reason output is `✏️【代码变更 · 需确认】写入项目文件 (test_demo.py) | 变更项目代码需人工核验`.
- Verify audit log `~/.gemini/logs/jev_evaluator.log` properly logs the new reason alongside structured fields.
