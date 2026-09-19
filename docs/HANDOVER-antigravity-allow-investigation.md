# Handover — Investigation: Antigravity ignores the hook's `allow` decision

**Purpose of this document:** let a fresh session (or a person) resume the open investigation without re-deriving anything. Everything below is evidence-backed; timestamps are local (UTC+8), 2026-09-19.

**Repo:** `D:\Projects\Jev\antigravity-approval` · branch `main` · HEAD `3176f48` · suite: **76 passed, 0 warnings**

---

## 0. TL;DR

The evaluator hook **works and is proven correct**: Antigravity spawns it, it answers `allow` in ~85 ms, and its audit log records the decision. The remaining problem is **on Antigravity's side of the boundary**: the permission dialog still appears for whitelisted commands despite our `allow`, and all four bisection stubs (including an instant no-stdin stub) behaved identically.

**Most promising untested hypothesis:** `allow` alone may not *grant* execution permission in Antigravity — the granting mechanism may be the `permissionOverrides` field. Probe **F** (prepared, unrun) tests exactly this. If F works, the fix is a small change in `_emit`.

**Immediate next action:** restore the real hook, then run Probe F, then Probe E (see §6).

---

## 1. What the project is

A `PreToolUse` hook for Antigravity that auto-approves safe tool calls and escalates everything rest. Two tiers:

- **Tier 1 (deterministic, stdlib-only):** chain splitting, write-operator/substitution disqualifiers, blocklist (POSIX/PowerShell/cmd.exe, now seeing through `cmd /c "…"` and `powershell -Command "…"` wrappers), network gate, read-only whitelist, dual-containment path guard for file tools.
- **Tier 2 (TypeSafe Jev, live):** lazy-imported SDK, one atomic `Choice` question (`category`), calibrated confidence ≥ 0.96 to auto-approve; hard daemon-thread deadline.

Contract: **one JSON decision on stdout** (`allow`/`deny`/`ask`/`force_ask`), all diagnostics to stderr, exit 0 on every path, failures fail closed to `ask`.

Key entry points:

| Thing | Path |
|---|---|
| Hook entrypoint | `scripts/jev_evaluator.py` |
| Installer (renders hooks.json) | `scripts/install_hook.py` |
| Rendered (machine-local, gitignored) | `.agents/hooks.json` |
| Core | `src/jev_eval/{config,deterministic,jev_client,decide,logging_setup}.py` |
| Spec / plan | `docs/superpowers/specs/2026-09-19-jev-permission-evaluator-design.md`, `docs/superpowers/plans/2026-09-19-jev-permission-evaluator.md` |
| Operator README | `README.md` |

Safe commands (re-run the installer after testing stubs):

```powershell
cd D:\Projects\Jev\antigravity-approval
.venv\Scripts\python.exe -m pytest -q          # expect 76 passed
.venv\Scripts\python.exe scripts\install_hook.py   # restore the real hook
```

---

## 2. The open problem (precise statement)

Asked to run `git status; git log -n 5` (a **whitelisted** command), Antigravity shows its approval dialog and waits for user input — even though `scripts/jev_evaluator.py` ran and emitted `{"decision": "allow", "reason": "whitelist: read-only command"}`.

The hook is not the cause of the dialog. Determine **why Antigravity does not act on the hook's `allow`**, and make whitelisted commands execute without a prompt.

---

## 3. Evidence timeline

| Time | Event | Evidence source | What it proves |
|---|---|---|---|
| 19:02:57 | Hook fired, **spawn failed** (`'"D:/...python.exe"' is not recognized… exit status 1`) | conversation transcript, step ERROR | Antigravity **does** integrate our hook and reports its failures — hook was live from the start |
| 19:27 | Fixed: cmd-safe **unquoted** command (`d544a06`); verified via `cmd.exe` spawn | repo commit + probe log | Spawning works |
| 19:39:04 | Hook answered **allow** (73 ms) → **dialog appeared anyway** | probe log + audit log | First allow-not-honored occurrence |
| 19:41:22–24 | Hook answered **allow** for `git status` then `git log -n 5` → **commands RAN** (transcript shows `GENERIC DONE … The command exited with code 0. Output: On branch main…`) | transcript + audit + probe | The only observed "success" — **possibly grant-driven, not hook-driven** (user had just clicked a dialog at 19:39) |
| 19:44:29 | `cmd /c "if exist build rmdir /s /q build"` → Jev classified **`destructive` 0.930** → `ask` (dialog) | audit log (live Jev call, 1211 ms) | Tier 2 works; `ask` correctly produces a dialog |
| 20:11:21 | `git reset --hard HEAD` → Jev **`destructive` 1.000** → `ask` | audit log (live Jev call, 866 ms) | Calibrated layer working as designed |
| 20:16 / 20:17 / 20:21 | allow → **dialog** (conversations `a03f2f75`, `bfc5f345`, `d90e9210`) | probe + audit; transcripts stop at `PLANNER_RESPONSE` | allow ignored in new conversations |
| 20:39 / 20:51 / 21:05 | allow → **dialog** (all conversation `d90e9210`) | probe + audit | Same |
| during the above | **Crash markers** written | `~/.gemini/antigravity/crashes/crash_*.log` at 20:17, 20:39, 21:08 (0 bytes each) | Executor instability coincides with the failures |
| user test | Stubs **A′/B/C/D all produced dialogs** | user report | Failure is **invariant** to what the hook does |

**Sample probe-log line (real hook, healthy):**

```
21:05:43 +  0.085s pid=3764 decision emitted: allow (whitelist: read-only command)
21:05:43 +  0.085s pid=3764 os._exit(0)
```

**Decisive transcript observation:** in *working* runs the transcript continues past the planner response to a `GENERIC` step containing the command output. In *broken* runs it **stops at the `PLANNER_RESPONSE`** — the executor never reaches tool execution.

---

## 4. Established facts & ruled out

**Established**
1. Hook **is** spawned by Antigravity, with CWD `<workspace>\.agents` (so `resolve_workspace_dir` maps config lookups to the parent).
2. Hook emits `allow` in ~85 ms and records it in `~/.gemini/logs/jev_evaluator.log`.
3. Antigravity knows the hook as `jsonhook__jev-evaluator_PreToolUse_0_0` (seen in an earlier step ERROR).
4. Tier 2 is live with a real API key (`~/.gemini/config/jev.env`) — real calibrated calls observed.
5. Antigravity's planner wraps `toolCall.args` values in literal quotes (`CommandLine='"git status; git log -n 5"'`) — extraction strips one layer.

**Ruled out (with reason)**
- **Hook not running / not installed** — probe log proves execution; hooks.json matcher and command verified.
- **Stdin hang (original suspicion)** — fixed with a deadline reader (`d18e78d`); stub B reads no stdin at all and still failed identically.
- **Answer latency** — stub B is instantaneous, stub D delays 300 ms; both failed.
- **Quoting/path bug in the command** — fixed (`d544a06`), verified through `cmd.exe`.
- **Antigravity self-update** — app binaries are all dated Sep 18; nothing was updated mid-session (only wrapper/`bin` files were regenerated).
- **A competing PreToolUse hook** — the only other plugin hooks (`~/.gemini/config/plugins/superpowers`) register `SessionStart` only, in Claude Code format, and fail to parse; they cannot raise PreToolUse prompts. No global `~/.gemini/config/hooks.json` exists.
- **Conversation-specific state** — failures occur across four different conversations.

---

## 5. Hypotheses (ranked)

**H1 — `allow` does not grant permission; `permissionOverrides` does. (leading)**
Antigravity's hook doc pairs decisions with `permissionOverrides` (e.g. `["read_file(/path)", "command(args)"]`) and offers a `deny_unless_prior_grant` decision — implying grants are a distinct mechanism. On this reading, `allow` means "no hook objection" while the ordinary permission system still prompts; only an override *authorizes* the call. **Tests: Probe F.** If true, fix = include `permissionOverrides: ["command(<cmd>)"]` when we emit `allow`.

**H2 — This build does not act on hook decisions for execution.**
…or acts on `deny` but not `allow`. **Tests: Probe E** (a `deny` that, if honored, hard-blocks everything).

**H3 — The 19:41 success was grant-driven; hook `allow` has never been honored.**
Consistent with every data point: the only commands that ever executed were the ones the user had just granted via a dialog. Implication: **all prior "it worked" observations must be discounted**; treat grant state as a confounder in every future test.

**H4 — Executor instability is a contributing (not root) cause.**
Crash markers coincide, and every user message in the affected conversation carries a *"All your subagents and background tasks have been stopped due to server restart"* notice. But the stubs failed **identically**, so this cannot be the whole story — a stable executor should honor an instant `allow`. Keep the hook cheap and fail-closed regardless.

---

## 6. Next actions

### Step 0 — restore real state
```powershell
cd D:\Projects\Jev\antigravity-approval
.venv\Scripts\python.exe scripts\install_hook.py
```
(`.agents/hooks.json` currently points at `stub_allow_delay.py` — see §8.)

### Step 1 — Probe F (run this first; tests H1)
Edit `.agents/hooks.json`, changing only the `command` value to:
```
D:/Projects/Jev/antigravity-approval/.venv/Scripts/python.exe D:/Projects/Jev/antigravity-approval/scripts/stub_allow_override.py
```
Restart Antigravity. In a **new conversation**, ask the agent to run a command that has **never been granted** — use `git diff --stat` (whitelisted; `git status; git log -n 5` is contaminated by earlier grants).

- **Executes with no dialog → H1 confirmed.** Fix `_emit` in `scripts/jev_evaluator.py` to attach `permissionOverrides: ["command(<extracted command>)"]` whenever the decision is `allow`; add tests in `tests/test_e2e.py` asserting the field is present and names the command.
- **Dialog → go to Step 2.**

### Step 2 — Probe E (tests H2)
Set `command` to point at `scripts/stub_deny.py`. Restart, ask for any command.

- **Everything hard-blocked, clearly denied →** Antigravity reads our stdout; **only `allow` is broken**. Report as a bug (asymmetry: `deny` honored, `allow` ignored).
- **Dialog appears as usual →** hook decisions are not acted on at all in this build. Report as a bug.

### Step 3 — if both probes fail
Prepare a bug report for Google containing: the probe log, the audit log, the crash markers, the conversation transcripts (broken vs working), and the ABCD/E/F results. Antigravity version: check **Help → About**. Evidence paths are in §7.

### Step 4 — when it works
1. Re-test the dangerous prompts: `cmd /c "if exist build rmdir /s /q build"` → must `deny` (blocklist); `git reset --hard HEAD` → must `ask` (Jev `destructive`).
2. Close out the probe: delete `scripts/_hook_probe.log` to disable instrumentation (it is opt-in, see §8).
3. Optional: add a `README` note about grants contaminating tests.

---

## 7. Where the evidence lives

| What | Path | Notes |
|---|---|---|
| Hook lifecycle trace | `scripts/_hook_probe.log` | Only written by `jev_evaluator.py`; **opt-in** (file must pre-exist) |
| Decision audit log (JSONL) | `~/.gemini/logs/jev_evaluator.log` | One line per run: input, tier, decision, reason, category, confidence, latency |
| Conversation transcript | `~/.gemini/antigravity/brain/<conversationId>/.system_generated/logs/transcript.jsonl` | `PLANNER_RESPONSE` = what the agent proposed; `GENERIC` = execution result; step `ERROR` = hook failure |
| Antigravity backend log | `~/.gemini/antigravity/log/cli-*.log` | Model polling only — **silent about hooks**; hook parse warnings do appear (`hooks.go:…`) |
| Crash markers | `~/.gemini/antigravity/crashes/crash_*.log` | 0-byte files; timestamps correlate with failures |
| API key (user-level) | `~/.gemini/config/jev.env` | `TYPESAFE_API_KEY=…`; never commit |
| Busy/known conversations | `d57199a7-…` (19:39–19:44), `a03f2f75-…`, `bfc5f345-…`, `d90e9210-…` (20:21–21:05) | `d90e9210` is the multi-failure one |

Useful greps:
```powershell
Get-Content D:\Projects\Jev\antigravity-approval\scripts\_hook_probe.log -Tail 12
Get-Content $env:USERPROFILE\.gemini\logs\jev_evaluator.log -Tail 5
Get-ChildItem $env:USERPROFILE\.gemini\antigravity\crashes | Sort LastWriteTime -Desc | Select -First 5
```

---

## 8. Current machine state (left as-is for the next session)

- `main` @ `3176f48`; **76 tests pass**.
- **`.agents/hooks.json` points at `stub_allow_delay.py`** (from the ABCD test run) — **restore with `scripts/install_hook.py`.**
- Uncommitted: `.gitignore` (+`_hook_probe.log`), and untracked `output.log` (UTF-16 "test" — a stray redirect artifact; safe to delete).
- `scripts/_hook_probe.log` exists → instrumentation **active**. Delete the file to disable (the probe is inert without it).
- `~/.gemini/config/jev.env` holds a working API key; there is **no** global `~/.gemini/config/hooks.json`.
- Test artifacts in repo: `scripts/stub_allow.py` (B), `stub_allow_readstdin.py` (C), `stub_allow_delay.py` (D), `stub_deny.py` (E), `stub_allow_override.py` (F). All committed; delete when the investigation closes.

## 9. Things to be skeptical about

- **Grants are a confounder.** Any dialog the user answered with an "always allow" option creates standing permission that silently masks whether the hook worked. Always test with a fresh command in a fresh conversation.
- **A running hook process is not proof of a working hook.** The probe log proves execution; only the transcript (`GENERIC` step after `PLANNER_RESPONSE`) proves the effect.
- **Two separate bugs may be interleaved**: the `allow`-not-honored problem, and executor instability (restarts/crashes). The stubs failed identically, which argues the first is independent of the second — but re-verify once the executor is stable.
