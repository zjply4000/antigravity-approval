# Clean re-test — does the Antigravity 2.0 **app** honor a hook `allow`?

**Why this exists:** the earlier "Antigravity 2.5.5 host bug" report
(`docs/BUGREPORT-...md`) is **not supported by verifiable evidence**. Its decisive
claim — a Probe E transcript denial at 21:32:57 — does not exist in any log or
transcript on disk, and `stub_deny.py` never wrote a marker (it had no logging).
Meanwhile the user reports `stub_allow.py` **was honored several times**, then broke
during the ABCD tests and never recovered. That makes this a **regression**, not a
protocol bug.

The two things that changed during the break, and that this procedure controls for:
1. **Executor instability** — the app crashed at 22:13 (`~/.gemini/antigravity/crashes/`);
   the one verifiable allow-not-honored run (21:50) sits next to a "server restart" notice.
   A restart mid-call leaves the transcript stopped at `PLANNER_RESPONSE`, which *looks*
   like "allow ignored."
2. **Config contamination** — another agent rewrote `hooks.json` to the LibreOffice
   interpreter mid-investigation. A wrong interpreter/script means no usable decision.

**Product under test:** `Programs/antigravity/Antigravity.exe` (the 2.0 **app**, state in
`~/.gemini/antigravity`), **not** `Programs/Antigravity IDE`. There is no global
`~/.gemini/config/hooks.json`; the app reads the workspace `.agents/hooks.json`.

**What changed since the bad report:** the stubs now write a provable marker to
`scripts/_stub_probe.log` (timestamp, pid, interpreter, cwd, exact stdout), and
`scripts/set_probe_hook.py` is the only sanctioned way to switch the hook — it always
renders the **venv** interpreter and prints a pre-flight (venv exists, latest crash time,
global-hooks absent).

---

## Ground rules (every probe)

- **Fresh conversation** each time, and a command that has **never been granted**
  (a prior "Always Allow" silently masks whether the hook worked). Use `git diff --stat`.
- **Verify the `command` line** printed by `set_probe_hook.py` before relaunching —
  it must name `.venv\Scripts\python.exe` and the right script.
- **Fully quit and relaunch the app** after switching the hook (hooks.json is read at startup).
- **Note the latest crash time** from the pre-flight. If a new crash appears during the
  probe, the result is **invalid** — discard and rerun once the app is stable.
- A result counts only when **both** agree: the stub marker (we control it) **and** the
  host transcript (`~/.gemini/antigravity/brain/<conv>/.system_generated/logs/transcript.jsonl`).

---

## Probe ALLOW (the core question)

```powershell
cd D:\Projects\Jev\antigravity-approval
.venv\Scripts\python.exe scripts\set_probe_hook.py allow
```
Confirm the printed command line, then quit + relaunch the **app**. In a **new
conversation**, ask: *"Run `git diff --stat`."* Observe whether a permission dialog appears.

Then capture evidence:
```powershell
Get-Content D:\Projects\Jev\antigravity-approval\scripts\_stub_probe.log -Tail 3
```
Find the new conversation's transcript and check whether a `GENERIC` step (execution
result) follows the `PLANNER_RESPONSE`, or whether it stops at `PLANNER_RESPONSE`.

## Probe DENY (establishes whether decisions are read at all)

```powershell
.venv\Scripts\python.exe scripts\set_probe_hook.py deny
```
Quit + relaunch the app. New conversation, ask for **any** command. Capture the marker
and transcript as above.

## Restore the real hook when done

```powershell
.venv\Scripts\python.exe scripts\set_probe_hook.py real
.venv\Scripts\python.exe scripts\install_hook.py   # equivalent; renders jev_evaluator.py
```

---

## Decision matrix

| Probe | Stub marker? | Host behavior | Conclusion |
|---|---|---|---|
| ALLOW | present | command runs, **no dialog** | `allow` **is** honored. The regression was instability/contamination — proceed to test the real evaluator on a whitelist command. |
| ALLOW | present | **no execution**, transcript stops at `PLANNER_RESPONSE`, **no new crash** | `allow` genuinely ignored by a **stable** app → real host-bug candidate. Now the report is evidence-backed. |
| ALLOW | present | no execution **and** a new crash appeared | **Invalid** — executor instability. Rerun when stable. |
| ALLOW | **absent** | dialog / nothing | Hook never fired → config/discovery problem, **not** a decision bug. Re-verify the command line and that the app reads `.agents/hooks.json`. |
| DENY | present | command **hard-blocked** with our reason | Decisions **are** read; compare against the ALLOW row to confirm/refute asymmetry. |
| DENY | present | command **runs anyway** | Host ignores decisions entirely (both directions). |
| DENY | **absent** | — | Hook never fired (same as ALLOW/absent). |

**Only the combination "ALLOW marker present + no execution + no crash + DENY honored"
supports a host-bug report.** Anything else redirects the investigation (config,
instability, or grant contamination).

---

## Evidence to attach to any future report

- `scripts/_stub_probe.log` (proves the stub ran and what it emitted)
- the conversation `transcript.jsonl` (proves what the host did)
- `~/.gemini/antigravity/crashes/` listing with timestamps (proves executor stability)
- the exact `.agents/hooks.json` `command` line used
- app version: **Help → About** in the 2.0 app
