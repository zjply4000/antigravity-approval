# Safe Source Code File Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a layered safe-source file evaluation engine in Jev Tier 1 so that workspace source and doc files (`.py`, `.ts`, `.go`, `.md`, etc.) are auto-approved (`allow`), while sensitive files (`.env`, keys, CI/CD, lockfiles) and unknown extensions trigger manual confirmation (`ask`).

**Architecture:** Add `src/jev_eval/file_guard.py` containing sensitive pattern matching and extension whitelist lookup; integrate into `src/jev_eval/deterministic.py` for file tool evaluation; update `src/jev_eval/formatter.py` to produce semantic badges for `safe_source` and `sensitive_file`; align and expand test suites across both repositories.

**Tech Stack:** Python 3.10+, pytest, standard library (`os.path`, `pathlib`, `re`, `fnmatch`).

## Global Constraints

- 优先使用utf-8编码读取文件。
- 不要自动提交修改 (Zero automatic git commits).
- Zero regressions: all 168+ tests across `antigravity-approval` and `zcode-approval` must pass cleanly.
- Absolute paths and case-insensitivity on Windows filesystem.

---

### Task 1: Semantic Reason Badges for Safe Source and Sensitive Files

**Files:**
- Modify: `d:/Projects/Jev/antigravity-approval/src/jev_eval/formatter.py`
- Test: `d:/Projects/Jev/antigravity-approval/tests/test_formatter.py`

**Interfaces:**
- Consumes: `format_tier1_reason(tier: str, raw_reason: str, target: str) -> str`
- Produces: formatted strings for `tier="safe_source"` and `tier="sensitive_file"`:
  - `safe_source`: `🟢【代码编写 · 自动放行】修改工作区源码文件 ({basename})`
  - `sensitive_file`: `⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 ({basename}) | 变更关键配置需人工核验`

- [ ] **Step 1: Write failing unit tests in `tests/test_formatter.py`**

Add tests to `tests/test_formatter.py`:
```python
def test_format_tier1_safe_source():
    r = format_tier1_reason("safe_source", "safe workspace source file", "src/index.ts")
    assert r == "🟢【代码编写 · 自动放行】修改工作区源码文件 (index.ts)"


def test_format_tier1_sensitive_file():
    r = format_tier1_reason("sensitive_file", "sensitive config", ".env.local")
    assert r == "⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 (.env.local) | 变更关键配置需人工核验"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\antigravity-approval\tests\test_formatter.py -k "safe_source or sensitive_file" -v`
Expected: FAIL (KeyError or unhandled tier).

- [ ] **Step 3: Implement badge formatting in `src/jev_eval/formatter.py`**

In `src/jev_eval/formatter.py`, update `format_tier1_reason`:
```python
    if tier == "safe_source":
        bname = os.path.basename(target) if target else "源码文件"
        return f"🟢【代码编写 · 自动放行】修改工作区源码文件 ({bname})"

    if tier == "sensitive_file":
        bname = os.path.basename(target) if target else "敏感资产"
        return f"⚠️【敏感配置 · 需确认】修改敏感资产或关键配置 ({bname}) | 变更关键配置需人工核验"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\antigravity-approval\tests\test_formatter.py -v`
Expected: PASS (all 19 tests in test_formatter.py pass).

---

### Task 2: Core File Guard Implementation (`file_guard.py`) & Engine Integration

**Files:**
- Create: `d:/Projects/Jev/antigravity-approval/src/jev_eval/file_guard.py`
- Modify: `d:/Projects/Jev/antigravity-approval/src/jev_eval/deterministic.py`
- Test: `d:/Projects/Jev/antigravity-approval/tests/test_safe_source.py`

**Interfaces:**
- Produces:
  - `SAFE_SOURCE_EXTENSIONS: frozenset[str]`
  - `is_sensitive_file(target: str, cwd: str = "") -> bool`
  - `is_safe_source_file(target: str, cwd: str = "") -> bool`
  - `evaluate_file_write(target: str, cwd: str, workspace_paths: list[str], extra_roots: list[str] | None, path_policy: str) -> Tier1Outcome`

- [ ] **Step 1: Write comprehensive failing tests in `tests/test_safe_source.py`**

Create `tests/test_safe_source.py` covering:
- Positive extensions (`.py`, `.ts`, `.go`, `.vue`, `.md`, `.sql`, uppercase `.PY`) in workspace -> `allow`, `safe_source`
- Sensitive patterns (`.env`, `.env.production`, `secret.key`, `token_storage.ts`, `.github/workflows/ci.yml`, `package.json`, `pyproject.toml`, `.gitignore`, `.git/config`) -> `ask`, `sensitive_file`
- Unknown extensions (`.dat`, `.bin`, `.exe`, no extension) -> `ask`, `write_policy`
- Integration with `evaluate_file_write` / `evaluate_tool_call`

- [ ] **Step 2: Run test to verify it fails**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\antigravity-approval\tests\test_safe_source.py -v`
Expected: FAIL (ModuleNotFoundError: no module named `file_guard`).

- [ ] **Step 3: Implement `src/jev_eval/file_guard.py`**

Implement `SAFE_SOURCE_EXTENSIONS`, `is_sensitive_file`, `is_safe_source_file`, and `evaluate_file_write`:
- Case-insensitive checks
- Normalize path separators (`/` vs `\`)
- Check sensitive names first: `.env*`, `*.pem`, `*.key`, `*secret*`, `*credential*`, `*token*`, `*password*`, `.git/`, `.github/`, dependency locks (`package.json`, `pyproject.toml`, etc.)
- Check `SAFE_SOURCE_EXTENSIONS`: `.py`, `.pyi`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.go`, `.rs`, `.java`, `.kt`, `.c`, `.cpp`, `.cc`, `.h`, `.hpp`, `.cs`, `.php`, `.rb`, `.swift`, `.scala`, `.lua`, `.sh`, `.bash`, `.ps1`, `.html`, `.css`, `.scss`, `.less`, `.vue`, `.svelte`, `.md`, `.markdown`, `.rst`, `.txt`, `.sql`
- Fallback unknown extension to `write_policy` with `ask`.

- [ ] **Step 4: Integrate into `src/jev_eval/deterministic.py`**

In `src/jev_eval/deterministic.py`, import `evaluate_file_write` from `.file_guard` and use it inside `evaluate_tool_call` when `tool_name in _FILE_TOOLS`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\antigravity-approval\tests\test_safe_source.py -v`
Expected: PASS.

---

### Task 3: Align Existing Tests & Full Cross-Repository Verification

**Files:**
- Modify: `d:/Projects/Jev/antigravity-approval/tests/test_deterministic.py`
- Modify: `d:/Projects/Jev/antigravity-approval/tests/test_e2e.py`
- Modify: `d:/Projects/Jev/zcode-approval/tests/test_zcode_adapter.py`
- Modify: `d:/Projects/Jev/zcode-approval/tests/test_e2e.py`

**Interfaces:**
- Consumes: `evaluate_tool_call` returning `Tier1Outcome("allow", ..., "safe_source")` for workspace `.py`/`.ts` files.

- [ ] **Step 1: Update `tests/test_deterministic.py` in `antigravity-approval`**

Update `test_file_tool_asks_after_path_guard`:
- Rename/update to test both:
  - Source file (`C:/ws/a.py`) -> `decision == "allow"` and `tier == "safe_source"`
  - Unknown file (`C:/ws/a.bin`) -> `decision == "ask"` and `tier == "write_policy"`
  - Sensitive file (`C:/ws/.env`) -> `decision == "ask"` and `tier == "sensitive_file"`

- [ ] **Step 2: Update `tests/test_e2e.py` in `antigravity-approval`**

In `tests/test_e2e.py`:
- `write_file.json` targets `D:/proj/src/a.py`.
- Update `test_write_tool_asks` to `test_write_tool_allows_safe_source`:
  `assert json.loads(proc.stdout)["decision"] == "allow"`
  `assert json.loads(proc.stdout)["reason"].startswith("🟢【代码编写")`
- Add `test_write_tool_sensitive_file_asks` with a fixture targeting `.env`.

- [ ] **Step 3: Update `tests/test_zcode_adapter.py` in `zcode-approval`**

Add unit test `test_main_write_workspace_source_auto_allowed`:
- Payload writing to `ws / "src" / "index.ts"` returns `permissionDecision == "allow"` and reason contains `"代码编写"`.

- [ ] **Step 4: Run full test suite in `antigravity-approval`**

Run: `d:\Projects\Jev\antigravity-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\antigravity-approval\tests -v`
Expected: PASS (100% of all tests pass).

- [ ] **Step 5: Run full test suite in `zcode-approval`**

Run: `d:\Projects\Jev\zcode-approval\.venv\Scripts\pytest.exe d:\Projects\Jev\zcode-approval\tests -v`
Expected: PASS (100% of all tests pass).

- [ ] **Step 6: Live Subprocess Validation**

Run live subprocess invocation on `stage4c_real_idempotency_resume.py` to confirm stdout emits:
`{"decision": "allow", "reason": "🟢【代码编写 · 自动放行】修改工作区源码文件 (stage4c_real_idempotency_resume.py)"}`.
