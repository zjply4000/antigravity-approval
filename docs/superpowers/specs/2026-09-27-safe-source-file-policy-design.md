# Safe Source Code File Policy Design (Jev Tier-1 File Guard Upgrade)

## 1. Executive Summary

In Jev v1, all file modification tools (`write_to_file`, `replace_file_content`, `multi_replace_file_content`, ZCode `Write`, `Edit`, `ApplyPatch`) inside the workspace unconditionally returned `ask` (`write_policy: file mutations are not auto-approved in v1`).
While designed as a conservative guardrail against silent code rewrite, this blanket gating severely disrupts automated coding agent workflows, causing approvals even for routine, benign edits (e.g. `+3 -3` line edits in `stage4c_real_idempotency_resume.py`).

This design upgrades Tier-1 file evaluation from an all-or-nothing gating to a **layered safe-source engine**:
1. High-priority workspace-internal blacklist intercepts sensitive assets (credentials, keys, CI/CD, dependency locks) with `ask`.
2. Strict extension whitelist auto-approves routine source and documentation files (`.py`, `.ts`, `.go`, `.vue`, `.md`, etc.) with `allow`.
3. Unknown or binary extensions safely fall back to `ask`.

---

## 2. Evaluation Pipeline Order

When a file tool (`write_to_file`, `replace_file_content`, `multi_replace_file_content`, `Write`, `Edit`, `ApplyPatch`) is evaluated, the security ordering is:

```
File Tool Call (target path)
   │
   ├── [Step 1: System & Credential Directory Escape]
   │     ├─ Target in system dir or user credential dir (~/.ssh, ~/.aws ...) ──► [DENY] ⛔ 强制阻断 (tier: path_guard)
   │     ├─ Target outside workspace ─────────────────────────────────────────► [ASK / DENY] (按 host path_policy)
   │     └─ Target in host sanctioned artifact / memory root ─────────────────► [ALLOW] 📋 自动放行 (tier: artifact)
   │
   ├── [Step 2: Workspace Sensitive Asset Blacklist (Priority Check)]
   │     └─ Matches sensitive filename, secret pattern, CI/CD, or lockfile ──► [ASK] ⚠️ 人工核验 (tier: sensitive_file)
   │
   ├── [Step 3: Safe Source Extension Whitelist]
   │     └─ File extension in SAFE_SOURCE_EXTENSIONS ─────────────────────────► [ALLOW] 🟢 自动放行 (tier: safe_source)
   │
   └── [Step 4: Unknown / Unrecognized File Fallback]
         └─ File has unknown extension or no extension ───────────────────────► [ASK] ✏️ 人工核验 (tier: write_policy)
```

---

## 3. Blacklist & Whitelist Specifications

### 3.1 Workspace Sensitive Asset Blacklist (`SENSITIVE_FILE_PATTERNS`)

A file target inside the workspace triggers `decision: "ask"` with `tier: "sensitive_file"` if its normalized path matches any of the following:

1. **Credentials & Key files (case-insensitive filename patterns)**:
   - Glob/Prefix: `.env*` (e.g., `.env`, `.env.local`, `.env.production`)
   - Extensions: `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.keystore`, `*.cert`, `*.crt`, `*.der`
   - Keyword in filename: contains `secret`, `credential`, `token`, `password`, `private_key` (e.g. `db_secret.py`, `token_storage.ts`)
2. **Repository & Version Control internals**:
   - Path contains `.git/` or `.git\` (e.g. `.git/config`, `.git/hooks/`)
   - Repository meta configs: `.gitignore`, `.gitattributes`, `.gitmodules`
3. **CI/CD & Deployment workflows**:
   - Path contains `.github/`, `.gitlab/`, `.circleci/`, `.buildkite/`
   - Container/orchestration definitions: `Dockerfile`, `docker-compose*.yml`, `docker-compose*.yaml`
4. **Project Dependency & Build Lockfiles**:
   - Node: `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`
   - Python: `requirements.txt`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `pyproject.toml`, `setup.py`, `setup.cfg`
   - Rust: `Cargo.toml`, `Cargo.lock`
   - Go: `go.mod`, `go.sum`
   - Java/Kotlin: `pom.xml`, `build.gradle`, `build.gradle.kts`, `settings.gradle`

### 3.2 Safe Source Extension Whitelist (`SAFE_SOURCE_EXTENSIONS`)

Case-insensitive set of extensions recognized as routine code/documentation:

- **Backend & Systems Languages**:
  `.py`, `.pyi`, `.go`, `.rs`, `.java`, `.kt`, `.kts`, `.c`, `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.hxx`, `.cs`, `.php`, `.rb`, `.swift`, `.scala`, `.lua`, `.sh`, `.bash`, `.zsh`, `.ps1`
- **Frontend & Web Languages**:
  `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.vue`, `.svelte`, `.astro`, `.html`, `.htm`, `.css`, `.scss`, `.sass`, `.less`
- **Documentation & Data Query**:
  `.md`, `.markdown`, `.rst`, `.txt`, `.adoc`, `.sql`, `.graphql`, `.gql`

---

## 4. Semantic Reason Badge Contracts

| Scenario | Tier | Decision | Human-Facing Reason Format (`reason`) |
| :--- | :--- | :--- | :--- |
| **Safe Source Code** | `safe_source` | `allow` | `🟢【代码编写 · 自动放行】修改工作区源码文件 ({basename})` |
| **Sensitive Asset Blacklist** | `sensitive_file` | `ask` | `⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 ({basename}) \| 变更关键配置需人工核验` |
| **Unknown Extension Fallback**| `write_policy` | `ask` | `✏️【未知文件 · 需确认】写入非白名单文件类型 ({basename}) \| 未知文件类型需人工核验` |
| **Host Artifact / Memory** | `artifact` | `allow` | `📋【宿主工件 · 自动放行】写入宿主专属对话工件或项目记忆` |
| **Outside Workspace (ZCode)** | `path_guard` | `ask` | `🚧【越界防护 · 需确认】目标路径位于工作区外部 \| 请确认是否允许跨目录操作` |
| **Outside Workspace (AGY)** | `path_guard` | `deny` | `🚫【环境隔离 · 越界拦截】写入工作区外部路径 ({basename}) \| 禁止修改工作区外部文件` |
| **System / Host Credentials** | `path_guard` | `deny` | `⛔【安全阻断 · 极高风险】禁止写入系统目录或私钥凭据 \| 已强制拦截` |

---

## 5. Implementation Architecture & Data Flow

### 5.1 `src/jev_eval/deterministic.py`
Add pure, zero-allocation helper functions:
- `is_sensitive_file(target: str, cwd: str) -> bool`
- `is_safe_source_file(target: str, cwd: str) -> bool`

Update `evaluate_tool_call`:
```python
    if tool_name in _FILE_TOOLS:
        hit = check_file_target(target, cwd, workspace_paths, extra_roots=extra_write_roots,
                                path_policy=path_policy)
        if hit is not None:
            decision, reason = hit
            return Tier1Outcome(decision, format_tier1_reason("path_guard", reason, target), "path_guard")
        if _is_sanctioned_artifact(target, cwd, extra_write_roots):
            return Tier1Outcome("allow", format_tier1_reason("artifact", "artifact: host-sanctioned conversation artifact", target),
                                "artifact")
        if is_sensitive_file(target, cwd):
            return Tier1Outcome("ask", format_tier1_reason("sensitive_file", "sensitive configuration or project file", target), "sensitive_file")
        if is_safe_source_file(target, cwd):
            return Tier1Outcome("allow", format_tier1_reason("safe_source", "safe workspace source file", target), "safe_source")
        return Tier1Outcome("ask", format_tier1_reason("write_policy", "unrecognized or non-whitelisted file extension", target), "write_policy")
```

### 5.2 `src/jev_eval/formatter.py`
Extend `format_tier1_reason` to format `safe_source` and `sensitive_file` into the respective badges.

---

## 6. Verification and Testing

1. **Unit Tests**:
   - `tests/test_safe_source.py`:
     - Test positive whitelist extensions (`.py`, `.ts`, `.go`, `.md`, `.vue`, etc.) -> `decision: allow`, `tier: safe_source`.
     - Test negative sensitive blacklist (`.env`, `.env.production`, `secret.key.py`, `token_storage.ts`, `.github/workflows/ci.yml`, `package.json`, `.gitignore`, `id_rsa.pub`) -> `decision: ask`, `tier: sensitive_file`.
     - Test unknown/unwhitelisted extensions (`.bin`, `.exe`, `.tar.gz`, extensionless `Makefile`) -> `decision: ask`, `tier: write_policy`.
     - Case insensitivity (`FOO.PY`, `Bar.TS`).
2. **Integration & Regression Tests**:
   - Update existing tests in `antigravity-approval` and `zcode-approval` that previously asserted `write_policy` on source files to assert `safe_source` and `allow`.
   - Full suite run: all 168+ tests in both repositories must pass cleanly.
