# Jev Permission Evaluator for Antigravity — Design Spec (v1)

- **Date:** 2026-09-19
- **Status:** Approved design, pending implementation plan · **Rev 3 (2026-09-19):** runtime review patches — PascalCase arg normalization, quote-stripping tokenizer + quoted-span-masked blocklist, read-only pipeline consumers, strict dual path containment (junction-aware), hard external deadline for the SDK call, explicit flush/exit contract, `multi_replace_file_content` matcher
- **Scope:** v1 = PreToolUse hook evaluator only. No CDP bridge, no file-write auto-approval.

## 1. Problem & Goals

Antigravity interactively prompts the user for every unwhitelisted `run_command`, `write_to_file`, and `replace_file_content` execution. This project installs a `PreToolUse` hook that evaluates each tool call through a tiered pipeline — deterministic rules first, TypeSafe Jev (a calibrated "System One" decision API) for ambiguous commands — and emits a native Antigravity hook decision.

**Success criteria**

1. Whitelisted read-only commands auto-approve with no network call; evaluator-internal processing stays under ~20 ms (total wall clock ~100–200 ms including Python interpreter startup — the startup dominates and is not counted against Tier 1).
2. Ambiguous-but-safe commands auto-approve via Jev within a 1500 ms evaluation budget (worst case ~2.5 s wall clock including interpreter startup, still inside the hook timeout).
3. Commands matching the Tier-1 blocklist and file targets outside the workspace are hard-denied (`deny`); commands Jev classifies `destructive` escalate to the prompt (`ask`).
4. Everything else — low confidence, errors, timeouts, unknown situations — escalates to the interactive prompt (`ask`). No failure mode can produce an unsound `allow`.
5. Every invocation appends one JSONL audit line with the command, decision, and score.

## 2. Non-Goals (v1)

- CDP/Electron GUI-clicking daemon (native `ask`/`force_ask` decisions make it redundant).
- Auto-approval of `write_to_file` / `replace_file_content` (always `ask` unless hard-denied by Tier 1).
- Log analytics, dashboards, per-project policy UIs.
- Support for other agent platforms (Claude Code, Cursor, etc.).

## 3. Verified External Contracts

### 3.1 Antigravity Hooks

From the official docs (antigravity.google/docs/hooks) and community verification (atamel.dev):

- **Config locations:** workspace `.agents/hooks.json` (all flavors); global `~/.gemini/config/hooks.json`.
- **Structure:** named hook → `{enabled, PreToolUse: [{matcher, hooks: [{type: "command", command, timeout}]}]}`. `matcher` is a regex over tool names; `timeout` is in seconds (default 30).
- **Input (stdin JSON):** `toolCall: {name, args}`, `stepIdx`, `conversationId`, `workspacePaths: string[]`, `transcriptPath`, `artifactDirectoryPath`, `modelName`. The event name is **not** in the payload — pass it via argv. Arg keys are **PascalCase** and tool-specific (`run_command`: `CommandLine`, `Cwd`, `WaitMsBeforeAsync`; file tools: `TargetFile`, `AbsolutePath`) — extraction normalizes casing (§6.5).
- **Output (stdout JSON)** — the decision contract is JSON, **not exit codes**:
  - `"allow"` — auto-approve
  - `"deny"` — hard block immediately
  - `"ask"` — prompt user; honors "Always Allow" caches
  - `"force_ask"` — always prompt, ignoring cached permissions
  - (`"deny_unless_prior_grant"` exists but is not used in v1)
  - Optional `reason: string`.
- **Known quirk (Windows):** hook processes are spawned by the Antigravity GUI and do **not** inherit shell-profile environment variables. Configuration therefore loads from files, not just process env (see §6.2).

### 3.2 TypeSafe Jev

From docs.typesafe.ai (API reference, primitives, confidence, Python SDK):

- **Endpoint:** `POST {TYPESAFE_BASE_URL}/v1/systemone` (default `https://api.typesafe.ai`), `Authorization: Bearer $TYPESAFE_API_KEY`, model `jev-latest`.
- **Request:** `{"model", "state": <object>, "questions": {"<id>": {"type": "noul"|"choice"|"score", "instructions", "criteria"}}}`.
- **Choice answer:** `{type: "choice", choice, probabilities: {option: p}, confidence}` — `confidence` summarizes how peaked the distribution is; it is the calibrated signal used for gating.
- **Errors:** HTTP 401 (auth), 422 (schema), 429 (rate limit), 529 (overloaded). ~32k-token budget shared by state + questions.
- **Python SDK:** `pip install typesafe-sdk`. Sync client:

  ```python
  from typesafe_sdk import TypeSafeClient, Choice, RetryPolicy
  client = TypeSafeClient(model="jev-latest")
  result = client.system_one(
      state={...},
      questions={"category": Choice(instructions="...", criteria={...})},
  )
  answer = result.choices["category"]   # .choice, .probabilities, .confidence
  ```

  `RetryPolicy(max_retries, backoff_max, timeout)` configures per-call timeout/retries; `TypeSafeAPIError.status` exposes the HTTP status; `TYPESAFE_LOG_LEVEL` controls SDK logging. The sync client is used (hooks are one-shot processes).

## 4. Architecture

```
Antigravity agent loop
        │  stdin: {toolCall, stepIdx, conversationId, workspacePaths, ...}
        ▼
scripts/jev_evaluator.py  (top-level guarantee: always prints one JSON decision object)
        │
        ▼
┌─ Tier 1: deterministic (all tools) ─────────────────────────────┐
│ blocklist hit / path escape        → deny                       │
│ whitelist hit (read-only command)  → allow                      │
│ network / pkg-install, ALLOW_NET=false → force_ask              │
│ write-ops or substitution anywhere → never whitelisted (Tier 2) │
│ anything else                      → fall through               │
└──────────────────────────────────────────────────────────────────┘
        │ fall-through
        ▼
┌─ Tier 2: Jev (run_command only) ────────────────────────────────┐
│ category = Choice{read_only, standard_dev, destructive,        │
│                   network_outbound} over state{tool, command,  │
│                   cwd, workspace_paths}                         │
│ allow  ⇔ category ∈ {read_only, standard_dev}                  │
│          (or network_outbound with ALLOW_NETWORK_COMMANDS=true)│
│          AND confidence ≥ CONFIDENCE_THRESHOLD (0.96)          │
│ else   → ask                                                    │
└──────────────────────────────────────────────────────────────────┘
        │ any error / timeout / missing key / malformed input
        ▼
{"decision": "ask", "reason": "<specific cause>"}   (fail-closed)
```

Exit codes are irrelevant to decisions: the process exits 0 after printing a decision. A top-level `try/except` prints `{"decision": "ask", "reason": "evaluator crash: ..."}` on any unhandled exception, so even a broken build cannot silently bypass or hang the loop (hook `timeout` 10 s is the last-resort backstop).

### 5. Decision Matrix

| # | Situation | Decision |
|---|---|---|
| 1 | Command matches blocklist (any shell) | `deny` + reason |
| 2 | File tool target escapes containment — lexically or via symlink/junction resolution — or lands in a system directory | `deny` + reason (names junction/symlink escape when detected) |
| 3 | Every segment tokenizes to a whitelisted read-only pattern, with no redirections, write operators, or substitution constructs anywhere in the command | `allow` + reason |
| 4 | Network command (curl/ssh-class, or package-manager install/publish form) and `ALLOW_NETWORK_COMMANDS=false` | `force_ask` + reason |
| 5 | `run_command`, Jev: confidence ≥ threshold ∧ (category ∈ {read_only, standard_dev} ∨ (category = network_outbound ∧ ALLOW_NETWORK_COMMANDS=true)) | `allow` + reason incl. category/confidence |
| 6 | `run_command`, Jev: anything else (`destructive`, or `network_outbound` with the flag false — normally unreachable via row 4, or confidence < threshold) | `ask` + reason |
| 7 | `write_to_file` / `replace_file_content` (not denied by row 2) | `ask` + reason |
| 8 | Any error, timeout, missing key, malformed payload, unknown tool | `ask` (or `allow` only if `JEV_FAIL_MODE=open`, §6.2) |

Order matters: rows are evaluated 1 → 2 → 3 → 4 → 5/6/7 → 8.

## 6. Components

### 6.1 Layout

```
antigravity-approval/
├── .gitignore                    # excludes .agents/hooks.json, .agents/jev.env, .venv/
├── hooks.template.json           # committed template with {{EVALUATOR_DIR}} placeholder
├── .agents/hooks.json            # rendered by install_hook.py; machine-local, gitignored
├── scripts/
│   ├── jev_evaluator.py          # thin entrypoint: argv, stdin→stdout; stdout reserved for the decision JSON
│   ├── install_hook.py           # renders hooks.template.json → .agents/hooks.json (venv-aware)
│   └── smoke_live.py             # manual one-shot live Jev call (not in CI)
├── src/jev_eval/
│   ├── __init__.py
│   ├── config.py                 # settings loading (env > workspace file > user file > defaults)
│   ├── deterministic.py          # tokenizer, chain splitter, blocklist, whitelist, path guard
│   ├── jev_client.py             # SDK wrapper → Verdict(category, confidence, latency_ms)
│   ├── decide.py                 # pure tiered decision functions
│   └── logging_setup.py          # JSONL audit log with rotation
├── tests/
│   ├── fixtures/                 # recorded Antigravity payload shapes (.json)
│   ├── test_deterministic.py
│   ├── test_decide.py
│   ├── test_jev_client.py        # SDK mocked; no network in tests
│   └── test_e2e.py               # script run as subprocess with piped stdin
├── pyproject.toml                # deps: typesafe-sdk; dev: pytest
└── README.md                     # install, config, tuning, residual-risk statement
```

`scripts/jev_evaluator.py` inserts `src/` into `sys.path` and delegates; all logic lives in the importable `jev_eval` package so units are independently testable.

**Stdout purity:** `sys.stdout` carries exactly one write — the final decision as `json.dumps(...)` (ASCII-escaped, so Windows code pages can't break encoding). At entrypoint startup, all diagnostics are forced to `sys.stderr`: `warnings.filterwarnings` mutes Python warnings, `logging` is rooted to stderr, and SDK loggers inherit that. A chatty dependency (retry logs, deprecation notices) can therefore never corrupt Antigravity's JSON parsing of stdout.

**Exit contract:**

```python
try:
    decision = run_pipeline(...)
    sys.stdout.write(json.dumps(decision))
except Exception as e:
    sys.stdout.write(json.dumps({"decision": "ask", "reason": f"evaluator crash: {e}"}))
finally:
    sys.stdout.flush()
    sys.exit(0)
```

The explicit flush before `sys.exit(0)` avoids buffered output being dropped when the process is spawned through GUI subprocess pipes on Windows.

**Lazy imports:** only `jev_client` touches `typesafe_sdk`, and only inside its evaluate function. `config`, `deterministic`, `decide`, and `logging_setup` are standard-library-only, so Tier 1 paths never pay the SDK's pydantic/HTTP import cost (~100+ ms).

### 6.2 Configuration (`config.py`)

Precedence: process env → workspace `.agents/jev.env` → user `~/.gemini/config/jev.env` → built-in defaults. Files use `KEY=VALUE` lines (no shell interpolation); the API key belongs in the **user file** (never committed; `.agents/jev.env` must be gitignored if used for secrets).

| Key | Default | Meaning |
|---|---|---|
| `TYPESAFE_API_KEY` | — (required for Tier 2) | Bearer token |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | Endpoint override (tests/mocks) |
| `CONFIDENCE_THRESHOLD` | `0.96` | Min Choice confidence to auto-approve |
| `EVAL_TIMEOUT_MS` | `1500` | Jev call budget → `RetryPolicy(timeout=EVAL_TIMEOUT_MS/1000, max_retries=1, backoff_max=0.2)` |
| `ALLOW_NETWORK_COMMANDS` | `false` | `false` → network commands `force_ask` at Tier 1 before Jev. `true` → network commands skip the gate and may be auto-approved when Jev classifies them `network_outbound` with confidence ≥ threshold |
| `JEV_FAIL_MODE` | `closed` | `closed` → errors escalate to `ask`; `open` → errors emit `allow` (sandboxed/CI use only; README warns loudly) |
| `JEV_LOG_FILE` | `~/.gemini/logs/jev_evaluator.log` | Audit log path |

Worst-case Tier 2 wall time: 2 attempts × timeout + backoff ≈ 2.2 s at defaults — inside the hook's 10 s `timeout`.

### 6.3 Deterministic engine (`deterministic.py`)

- **Chain splitting:** after masking quoted spans and redirection forms (`2>&1`, `&>`, `>&`, digit-prefixed `1>`/`2>`), split on unquoted `&&`, `||`, `;`, `|`, **single `&`** (cmd.exe chain / bash background), and raw newlines (`\r?\n`). Every segment must clear on its own — a single unclear segment demotes the whole command.
- **Tokenizer:** platform-aware (`shlex`-style, POSIX mode off, so escape backslashes in Windows paths survive) — then strips **one layer of matched enclosing quotes** from each token. `posix=False` retains quotes, so a quoted binary (`"git" status`) would otherwise fail first-token prefix matching and demote trivial commands to Tier 2.
- **Write operators (disqualify from whitelist → Tier 2):** any unquoted `>`, `>>`, `1>`, `2>`, `&>`, `>|`, or write cmdlets/aliases `Out-File`, `Set-Content`, `Add-Content`, `tee`, plus git's `--output=<file>` (and whitelist disqualification of standalone `-o` after `git log|diff|show`), which write command output to an arbitrary path. `echo`, `cat`, and friends are whitelisted only when the segment carries none of these — `echo "payload" > src/critical.py` is a write, not a read.
- **Substitution constructs (disqualify from whitelist → Tier 2):** unquoted backticks, `$(`, `<(` (process substitution), PowerShell subexpressions. Their contents still undergo blocklist analysis (below) — embedding `rm -rf` inside `$( )` is a deny, not an escape hatch.
- **Blocklist → deny** (case-insensitive, compiled once at import): POSIX (`rm -rf`, `rm -fr`, `mkfs`, `dd if=`, fork bomb `:(){:|:&};:`), PowerShell (`Remove-Item` with `-Recurse`+`-Force`, `format-volume`), cmd.exe (`del /s`, `rd /s`, `rmdir /s`), credential access (`.ssh`, `.aws`, `.gnupg` paths in commands, plus secret files reachable via whitelisted readers: `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`, `id_rsa`, `id_ed25519`, `*.pem`, `.env`), and remote-code-execution patterns (`curl|wget … | sh|bash`, `iex(iwr …)`, `Invoke-Expression` + download combos). Patterns scan each segment's text with **quoted spans masked out** — masking (not token-joining) is what protects quoted prose: `git commit -m "fixed the rm -rf bug"` scans as `git commit -m ◇`, whereas joining stripped tokens back into one string would still contain `rm -rf` and false-deny. Segments flagged as substitution-bearing are **additionally scanned as raw text, quoted content included** — the tokenizer glues `$(rm` into a single token that masking would otherwise hide, and over-blocking inside substitutions is acceptable (they are already disqualified from the whitelist).
- **Network gate → force_ask** (when `ALLOW_NETWORK_COMMANDS=false`): first token of any segment in `curl`, `wget`, `ssh`, `scp`, `sftp`, `nc`, `ncat`, `telnet`, `ftp`, `Invoke-WebRequest`, `iwr`, `Invoke-RestMethod`, `irm` — plus **package-manager install/publish forms** (`npm|pnpm|yarn|bun|pip|pip3|uv|poetry|cargo|dotnet|gem|composer` followed by `install|i|add|publish`), because package installs contact external servers and Jev must never be the only barrier in front of them.
- **Whitelist → allow** (tokenized prefix match; **every segment** must be whitelisted): `git status|diff|log|show`, `ls`, `dir`, `pwd`, `echo`, `cat`, `type`, `Get-Content`, `python --version`, `node --version`, plus **read-only pipeline consumers** — `Select-String`, `grep`, `findstr`, `head`, `tail`, `more`, `Out-Host` — so standard `git log | Out-Host` / `git status | Select-String "modified"` pipes stay in Tier 1 instead of falling through to Jev. `git branch` is deliberately excluded: prefix matching cannot distinguish `git branch` (listing) from `git branch -D <name>` (force-delete), so it falls through to Tier 2. The concrete list ships as a module-level constant in `deterministic.py` and is fully enumerated by unit tests — no command is whitelisted implicitly.
- **Path guard (file tools):** a target is contained only if **both** `os.path.abspath(target)` (lexical, drive/case-normalized) **and** `os.path.realpath(target)` resolve inside some `workspacePaths` entry. Strict dual containment — not either-or — keeps a workspace symlink/junction pointing at `~/.ssh` or another drive a `deny`; when the two resolutions differ, the reason names it ("junction/symlink target outside workspace") so legitimate junction users get a diagnosable message instead of a mystery denial. Also deny system directories (`%SystemRoot%`, `%ProgramFiles%`, `/etc`, `/usr`, `/bin`, `~/.ssh`).

### 6.4 Jev client (`jev_client.py`)

Wraps the SDK behind one function: `evaluate_command(command, cwd, workspace_paths, config) -> Verdict | None`.

- Builds `state = {"tool": "run_command", "command", "cwd", "workspace_paths"}` and one question:
  - id `category`, `Choice`, instructions: *"An agent proposes running this command inside the listed workspace directories. What best describes the command's effect? Judge only what the command itself does; ignore who wrote it."*
  - criteria with explicit definitions to remove boundary ambiguity:
    - `read_only` — observes state; zero side effects, zero network.
    - `standard_dev` — creates or modifies files and build artifacts strictly inside the workspace (build, test, lint, format); no contact with anything outside the machine.
    - `network_outbound` — **any** contact with servers beyond the machine, including package installs (`npm install`, `pip install`, `cargo add`), `git fetch`/`pull`/`push`, `curl`/`wget`, API calls — even when the intent is a routine dev workflow.
    - `destructive` — destroys or irreversibly alters data: deleting files, force-overwriting, and **discarding uncommitted work** (`git reset --hard`, `git checkout -- .`, `git clean`), even when routine for the agent.
- Imports `typesafe_sdk` **lazily, inside the evaluate function** — Tier 1 paths never load the SDK or its pydantic/HTTP dependency tree (see §6.1).
- Enforces a **hard external wall-clock deadline** around the SDK call (`EVAL_TIMEOUT_MS + 500 ms`, via a worker future): SDK/socket timeouts do not bound DNS resolution or pre-handshake connection stalls, so the caller never trusts the SDK's `RetryPolicy` alone — deadline expiry returns `None` → `ask`. Where the SDK surfaces connect/read knobs, they are set explicitly (`connect=1.0 s`, `read=EVAL_TIMEOUT_MS`).
- Normalizes the answer to `Verdict(category, confidence, latency_ms)`; returns `None` for any `TypeSafeAPIError`, timeout, missing key, or malformed answer (missing confidence, unknown category value) — callers then apply the fail-mode.
- Records latency around the `system_one` call for the audit log.

### 6.5 Decision core (`decide.py`)

Pure functions: `decide(tool_name, args, workspace_paths, config, verdict) -> Decision(decision, reason)`. No I/O. All matrix rows (§5) implemented here; `verdict=None` means Tier 2 unavailable → row 8. This is the unit under test for threshold boundaries.

**Arg extraction** normalizes Antigravity's PascalCase keys with lowercase fallback, per tool: `command = args.get("CommandLine") or args.get("command") or ""`, `cwd = args.get("Cwd") or args.get("cwd") or os.getcwd()`, `target = args.get("TargetFile") or args.get("AbsolutePath") or args.get("target_file") or args.get("file_path")`. An unrecognized tool name, or an empty extraction where one is required, routes to `ask` with a diagnostic reason — never guessed.

### 6.6 Logging (`logging_setup.py`)

JSONL, one object per line, `RotatingFileHandler` 5 MB × 3 backups:

```json
{"ts": "2026-09-19T12:00:00.123Z", "conversationId": "...", "tool": "run_command", "input": "npm test", "tier": "jev", "decision": "allow", "reason": "standard_dev conf=0.982", "category": "standard_dev", "confidence": 0.982, "latency_ms": 118, "fail_mode": "closed"}
```

The API key and file **contents** are never logged (paths only). `tier` ∈ `blocklist | whitelist | path_guard | network_gate | write_policy | jev | fallback`.

### 6.7 Hook registration (machine-local, generated)

Hook config embeds machine-specific absolute paths, so it is **generated, not committed**. `hooks.template.json` holds the registration with a `{{EVALUATOR_DIR}}` placeholder; `scripts/install_hook.py` renders it to `.agents/hooks.json`, resolving this machine's venv interpreter (`<dir>/.venv/Scripts/python.exe` on Windows, `.venv/bin/python` otherwise) and failing with guidance if the venv or `typesafe-sdk` is missing. The rendered file is gitignored here and in every consumer workspace; global install = paste the same rendered block into `~/.gemini/config/hooks.json`.

```json
{
  "jev-evaluator": {
    "enabled": true,
    "PreToolUse": [
      {
        "matcher": "run_command|write_to_file|replace_file_content|multi_replace_file_content",
        "hooks": [
          {
            "type": "command",
            "command": "\"{{EVALUATOR_DIR}}/.venv/Scripts/python.exe\" \"{{EVALUATOR_DIR}}/scripts/jev_evaluator.py\" --event PreToolUse",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The explicit venv interpreter is mandatory: a GUI-spawned bare `python` may resolve to the wrong system interpreter without `typesafe-sdk` installed. The matcher includes `multi_replace_file_content` so batched edits still pass the path guard — ungoverned, they would bypass the deny-on-escape check entirely and fall to the unmanaged default prompt. `--event` argv flag because the payload omits the event name; `timeout: 10` seconds is the backstop. If the interpreter itself fails to spawn, Antigravity proceeds with its default interactive prompt — fail-closed by construction; `install_hook.py` validates the interpreter and dependency at install time.

## 7. Error Handling Summary

| Failure | Behavior |
|---|---|
| Malformed/empty stdin JSON | `ask`, tier `fallback` |
| Missing/unknown `toolCall.name` | `ask` |
| `typesafe_sdk` import failure | `ask` (reason names the missing dep) |
| API key absent when Tier 2 needed | `ask`, reason "missing TYPESAFE_API_KEY" (logged once per run, prominently) |
| Jev timeout / 429 / 529 after retry | `ask` (closed mode) |
| Jev 401 / 422 | `ask` + reason with status (config bug, not transient) |
| Malformed Jev answer | `ask` |
| Python interpreter fails to spawn (missing/wrong venv path) | Antigravity default flow proceeds (interactive prompt); `install_hook.py` validates interpreter + dependency at install time |
| Third-party code writes to stdout (warnings, retry logs) | prevented structurally: stdout reserved for the single decision JSON; all diagnostics forced to stderr (§6.1) |
| Any unhandled exception | top-level handler → `ask` |

## 8. Testing Plan

- **Unit (`test_deterministic.py`):** whitelist hits (`git status`, `ls -la`) → allow; **quoted binary** (`"git" status`) → allow (quote-stripped tokens); **pipeline consumers** (`git log | Out-Host`, `git status | Select-String "modified"`) → allow; blocklist per shell (`rm -rf /`, `Remove-Item -Recurse -Force`, `rd /s /q`) → deny; chained `git status && rm -rf /` → deny; **single-`&` chain** `git status & rmdir /s /q build` → deny; **newline-chained** commands split before analysis; `git status && npm test` → demote to Tier 2; network gate → force_ask; **package-manager forms** (`npm install pkg`, `pip install requests`) → force_ask; path guard escapes (`..\..\Windows\System32\...`, `/etc/passwd`) → deny; **junction escape** — target whose lexical path is inside the workspace but whose realpath resolves outside → deny with junction-named reason (test creates a real junction on win32, skipped elsewhere); quoting (`git commit -m "a && rm -rf /"` is one segment, no false split, **no false deny via quoted-span masking**); **redirection disqualification** (`echo hi > src/x.py`, `Get-Content a | Out-File b`, `cat f | tee g`) → Tier 2, not allow; **`2>&1` mask** (`git diff 2>&1` stays whitelisted); **quoted `>` is not a write** (`echo "a > b"` stays whitelisted); **substitutions** (`git log "$(rm -rf /)"` → deny via raw-text scan; ``echo `date` `` → Tier 2).
- **Unit (`test_decide.py`):** threshold boundary 0.9599 → ask / 0.96 → allow; category `destructive`/`network_outbound` from Jev → ask; verdict None in closed mode → ask, in open mode → allow; write tools → ask after path-guard pass; **arg normalization** — PascalCase (`{"CommandLine": "git status", "Cwd": "..."}`) and lowercase (`{"command": "git status"}`) payloads extract identically; missing keys / unknown tool → ask with diagnostic reason.
- **Unit (`test_jev_client.py`):** SDK mocked: happy path, `TypeSafeAPIError(429)` → None, timeout → None, missing confidence → None; latency recorded; SDK imported only at first evaluate call (lazy); **SDK call sleeping past the hard external deadline** → None → ask.
- **E2E (`test_e2e.py`):** run `scripts/jev_evaluator.py` as subprocess; fixtures in `tests/fixtures/` replicate real Antigravity payload shapes (run_command with PascalCase keys, write_to_file, replace_file_content, multi_replace_file_content); cases: benign → allow, destructive → deny, malformed JSON → ask with exit 0; **stdout purity** — stdout parses as exactly one JSON object with diagnostics on stderr; **flush/exit** — exit code 0 on every path, output complete; **lazy import** — a whitelist-only run under `python -X importtime` shows no `typesafe_sdk` import.
- **Manual smoke (not CI):** `scripts/smoke_live.py` — one real Jev call with `npm test`, prints verdict + latency; run once after configuring the key.

## 9. Security Considerations

- The blocklist is defense-in-depth, **not** a security boundary; the README states residual risk plainly: a novel destructive command Jev classifies `standard_dev` with ≥0.96 confidence would auto-approve. Mitigations: threshold tuning (raise toward 0.98 after log review), the blocklist, chain splitting, and `ask` fallback. The audit log is the tuning feedback loop.
- Command text comes from the agent either way — the hook sees exactly what the user would have been shown; no new injection surface is introduced. Jev receives only command text, CWD, and workspace paths.
- The API key lives in `~/.gemini/config/jev.env` (user profile, 0600-equivalent), never in the repo or `hooks.json`.
- `JEV_FAIL_MODE=open` prints a persistent warning line to the log on every `open`-mode allow.

## 10. Traceability to Original Task Checklist

| Original task | Spec coverage |
|---|---|
| Task 1: `scripts/jev_evaluator.py` | §6.1, §6.4, §6.5 (thin entrypoint + package) |
| Task 2: logging | §6.6 |
| Task 3: `.agents/hooks.json` | §6.7 |
| Task 4: unit tests (benign/destructive/ambiguous) | §8 |
| Task 5: fail-open/fail-closed safeguard | §6.2 `JEV_FAIL_MODE`, §7 |

## 11. Future Work (out of v1)

- CDP GUI bridge (only if native `ask` proves unreliable in a specific Antigravity build).
- Optional write auto-approval behind a flag, decided from audit-log evidence.
- Per-project threshold profiles; Jev `Score` question for blast-radius grading (read_only → machine-wide).

## 12. References

- Antigravity Hooks: https://antigravity.google/docs/hooks
- Hook lookup locations & practical quirks: https://atamel.dev/posts/2026/07-16_where_agy_hooks
- TypeSafe Jev API reference: https://docs.typesafe.ai/api.md
- Primitives (Choice/Noul/Score): https://docs.typesafe.ai/primitives.md
- Confidence semantics: https://docs.typesafe.ai/confidence.md
- Python SDK & usage: https://docs.typesafe.ai/sdk/python.md · https://docs.typesafe.ai/sdk/python/usage.md
- Jev overview coverage: https://kingy.ai · https://www.datacamp.com
