# Design Specification: Semantic Reason Badges & Risk Indication

**Document**: `docs/superpowers/specs/2026-09-27-semantic-reason-badges-design.md`  
**Date**: 2026-09-27  
**Status**: APPROVED  
**Target Systems**: `antigravity-approval` (shared core `jev_eval`) & `zcode-approval`  

---

## 1. Problem Statement & Motivation

In both Antigravity IDE and ZCode CLI, when the security evaluator intercepts a tool call and requests user confirmation (`decision: "ask"`), it provides a `reason` string to explain the verdict.

Historically, this reason string was formatted as raw developer-oriented English text:
- **Jev Tier 2 (Machine Evaluation)**:
  `jev: standard_dev conf=0.930 below threshold or disallowed category`
- **Tier 1 (Source File Modifications)**:
  `file mutations are not auto-approved in v1`
- **Tier 1 (Path Guard)**:
  `target path outside workspace`

### User Pain Points
1. **Unclear Confidence & Thresholds**: `conf=0.930` is cryptic. Users cannot tell whether 0.93 indicates a 93% danger score or 93% standard developer behavior, nor what threshold was required.
2. **Ambiguous Cause**: `below threshold or disallowed category` gives no indication whether the action was blocked because the score fell short (e.g. 93% < 96%) or because the category itself (e.g. `destructive`) is fundamentally barred from automatic approval.
3. **Misleading File Mutation Warning**: `file mutations are not auto-approved in v1` reads like an internal system malfunction rather than a standard, reassuring project source code safety policy.
4. **Lack of Visual Anchors**: Without visual indicators or risk levels, users cannot distinguish between harmless routine edits, network requests, and dangerous destructive commands at a glance.

---

## 2. Design Goals & Scope

### Goals
- **Instant Human Comprehension**: Use semantic emojis and standard risk badges (🟢 低风险 / 🟡 中风险 / 🟠 需关注 / 🔴 高风险 / 🚫 极高风险 / ⚠️ 降级保护) to convey risk level and action category in under 1 second.
- **Precise Attribution**: Clearly differentiate between "confidence below threshold" and "category requires manual confirmation by policy".
- **Structured Three-Part Badge Pattern**:
  `[Emoji + 风险等级 + 操作类型] 动作解释 | 拦截原因及分值`
- **Audit Log Schema Preservation**: Preserve all machine-readable structured JSON fields (`category`, `confidence`, `tier`, `decision`) in `jev_evaluator.log`. The upgrade affects only the human-facing `reason` field.
- **Cross-Host Consistency**: Implement once in the shared core (`jev_eval`), automatically benefiting both Antigravity and ZCode hosts.

### Non-Goals
- Changing the underlying evaluation logic, threshold values (0.96), or timeout limits (8000ms).
- Changing tool execution permissions or bypassing security gates.

---

## 3. Architecture & Module Design

### 3.1 New Module: `src/jev_eval/formatter.py`
A dedicated, pure standard-library module will be introduced in `antigravity-approval/src/jev_eval/formatter.py` with zero external dependencies.

```
antigravity-approval/src/jev_eval/
├── __init__.py
├── config.py
├── decide.py          ── calls ──▶ formatter.py (formats decision.reason)
├── deterministic.py   ── calls ──▶ formatter.py (formats Tier 1 reasons)
├── formatter.py       [NEW]        (pure badge & text rendering)
├── jev_client.py
├── logging_setup.py
└── reader.py
```

### 3.2 Key Formatting Functions

```python
def format_tier2_reason(
    category: str,
    confidence: float,
    threshold: float,
    approvable: bool,
    allow_network: bool,
) -> str:
    """Format a human-facing reason for Tier 2 Jev verdicts."""
    ...

def format_tier1_reason(
    tier: str,
    raw_reason: str,
    target: str = "",
) -> str:
    """Format a human-facing reason for Tier 1 deterministic outcomes."""
    ...

def format_fallback_reason(cause: str) -> str:
    """Format a human-facing reason when Jev evaluation fails or times out."""
    ...
```

---

## 4. Complete Reason Mapping Specification

### 4.1 Tier 2: Jev Remote Classifier Outcomes

| Category | Emoji & Badge | 动作解释 | 场景分支 | 最终 Reason 文本示例 |
| :--- | :--- | :--- | :--- | :--- |
| **`read_only`** | 🟢【只读观察 · 低风险】 | 查看状态或读取信息 | 达标放行 (`allow`) | `🟢【只读观察 · 低风险】查看状态或读取信息 \| 置信度 99%` |
| | | | 欠标确认 (`ask`) | `🟢【只读观察 · 低风险】查看状态或读取信息 \| 置信度 91% < 放行门槛 96%` |
| **`standard_dev`** | 🟡【常规开发 · 中风险】 | 修改工作区代码或测试构建 | 达标放行 (`allow`) | `🟡【常规开发 · 中风险】修改工作区代码或测试构建 \| 置信度 98%` |
| | | | 欠标确认 (`ask`) | `🟡【常规开发 · 中风险】修改工作区代码或测试构建 \| 置信度 93% < 放行门槛 96%` |
| **`network_outbound`** | 🟠【网络外联 · 需关注】 | 访问外部网络或下载依赖 | 禁网策略 (`ask`) | `🟠【网络外联 · 需关注】访问外部网络或下载依赖 \| 依网络防护策略需人工确认 (置信度 95%)` |
| | | | 允许网路但欠标 (`ask`)| `🟠【网络外联 · 需关注】访问外部网络或下载依赖 \| 置信度 92% < 放行门槛 96%` |
| | | | 允许网络且达标 (`allow`)| `🟠【网络外联 · 需关注】访问外部网络或下载依赖 \| 置信度 98%` |
| **`destructive`** | 🔴【高危破坏 · 高风险】 | 强制丢弃改动或删除数据 | 策略禁止放行 (`ask`)| `🔴【高危破坏 · 高风险】强制重置或删除数据 \| 依安全策略必须人工确认 (置信度 98%)` |

> [!NOTE]
> 置信度百分比统一保留整数显示（例如 `0.930` 格式化为 `93%`，`0.960` 格式化为 `96%`），杜绝枯燥浮点数。

---

### 4.2 Tier 1: 确定性防护规则

| Tier 规则类型 | 原生文案 (旧) | 优化后语义文案 (新) |
| :--- | :--- | :--- |
| **`write_policy`** | `file mutations are not auto-approved in v1` | `✏️【代码变更 · 需确认】写入项目文件 ({basename}) \| 变更项目代码需人工核验` |
| **`path_guard` (系统目录)** | `target path in system directory or sensitive credential` | `🚫【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 \| 已强制拦截` |
| **`path_guard` (工作区越界)** | `target path outside workspace` | `🚧【越界防护 · 需确认】目标路径位于工作区外部 \| 请确认是否允许跨目录操作` |
| **`path_guard` (软链跳逸)** | `junction/symlink target outside workspace...` | `🚧【越界防护 · 需确认】软链接或连接点跳出工作区 \| 请确认跨目录安全性` |
| **`blocklist` (凭据泄露)** | `blocklist: credential/secret file access` | `🚫【安全阻断 · 极高风险】检测到凭据/私钥文件访问 (.env/私钥) \| 已强制拦截` |
| **`blocklist` (递归强删)** | `blocklist: rm recursive force` / `cmd.exe recursive delete` | `🚫【安全阻断 · 极高风险】检测到高危递归强删命令 (rm -rf / del /s) \| 已强制拦截` |
| **`blocklist` (其它黑名单)** | `blocklist: <label>` | `🚫【安全阻断 · 极高风险】检测到危险操作命令 (<label>) \| 已强制拦截` |
| **`network_gate`** | `network command: '<cmd>'` | `🟠【网络外联 · 需关注】命令涉及外部网络请求 \| 依网络防护策略需人工确认` |
| **`artifact`** | `artifact: host-sanctioned conversation artifact` | `📋【宿主工件 · 自动放行】写入宿主专属对话工件或项目记忆` |
| **`whitelist`** | `whitelist: read-only command` | `🟢【只读观察 · 自动放行】常规只读安全命令` |

---

### 4.3 Fallback: 异常与超时降级

| 异常场景 | 原生文案 (旧) | 优化后语义文案 (新) |
| :--- | :--- | :--- |
| **响应超时** | `Jev evaluation deadline exceeded` / `deadline` | `⚠️【审查降级 · 超时保护】Jev 评估响应超时 (8s) \| 触发安全底座转人工确认` |
| **缺失秘钥** | `missing TYPESAFE_API_KEY` | `⚠️【审查降级 · 配置缺失】未检测到 TYPESAFE_API_KEY \| 触发安全底座转人工确认` |
| **输入空/超时** | `payload read timeout / empty input` | `⚠️【审查降级 · 输入异常】读取宿主请求输入超时或为空 \| 触发安全底座转人工确认` |
| **进程崩溃** | `evaluator crash: <exc>` | `⚠️【审查降级 · 执行异常】评估器异常 (<exc>) \| 触发安全底座转人工确认` |

---

## 5. Audit Log Compatibility & Data Integrity

Audit log entries in `~/.gemini/logs/jev_evaluator.log` and `~/.zcode/cli/log/jev_evaluator.log` follow this JSON structure:
```json
{
  "ts": "2026-09-27T15:20:00.000Z",
  "conversationId": "3e238906-1e5e-43df-9386-1514778c45df",
  "tool": "run_command",
  "input": "git commit ...",
  "tier": "jev",
  "decision": "ask",
  "reason": "🟡【常规开发 · 中风险】修改工作区代码或测试构建 | 置信度 93% < 放行门槛 96%",
  "category": "standard_dev",
  "confidence": 0.93,
  "latency_ms": 841,
  "fail_mode": "closed"
}
```

- **Structured machine fields** (`tier`, `decision`, `category`, `confidence`, `latency_ms`) remain completely untouched and precision-preserved.
- **Human explanation field** (`reason`) now carries clean, visually distinct semantic text.

---

## 6. Testing Strategy

1. **New Unit Tests**:
   - `tests/test_formatter.py`: Tests 100% of formatting logic across:
     - All 4 Jev categories under threshold-passing, threshold-failing, and disallowed policies.
     - Percentage conversion and rounding.
     - Tier 1 outcomes (`write_policy`, `blocklist`, `path_guard`, `network_gate`, `artifact`, `whitelist`).
     - Fallback scenarios (deadline, missing key, exceptions).
2. **Existing Test Suite Alignment**:
   - Update string assertions in `tests/test_decide.py`, `tests/test_deterministic.py`, `tests/test_e2e.py`.
   - Update assertions in `zcode-approval/tests/test_zcode_adapter.py` and `test_e2e.py`.
3. **Cross-Repository Verification**:
   - All 105+ tests in `antigravity-approval` pass.
   - All 46+ tests in `zcode-approval` pass.
   - Zero test failures, zero regressions.
