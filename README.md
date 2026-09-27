# jev-evaluator

An Antigravity `PreToolUse` hook that screens tool calls before they execute. Evaluation is tiered and deterministic-first: a fast local Tier 1 (whitelist, blocklist, network gate, path guard) settles unambiguous commands with no network traffic; ambiguous commands escalate to Tier 2, a single TypeSafe Jev classification call with a hard wall-clock deadline. Every Tier 2 failure — timeout, API error, missing key, malformed answer — fails closed to `ask`, so when the evaluator cannot answer, the command falls back to manual confirmation rather than silent approval.

## File writes and conversation artifacts

File-mutating tools (`write_to_file`, `replace_file_content`, `multi_replace_file_content`) inside the workspace always `ask` — v1 never auto-approves file mutations. A target outside every workspace is `deny` (path guard), **except** the host-sanctioned per-conversation artifact directory the payload supplies as `artifactDirectoryPath` (`~/.gemini/antigravity/brain/<conversationId>/…`), where Antigravity stores its own task artifacts and implementation plans: writes there are auto-approved (`allow`, tier `artifact`). The auto-approve is deliberately narrow — targets under `.system_generated/` and any `*.metadata.json` fall back to `ask`, so the agent cannot rewrite transcripts or artifact metadata through an auto-approved path.

## Known Antigravity host limitation

On the Antigravity 2.0 app, a hook `allow` does **not** suppress the permission dialog for `run_command`; only the host's own `userSettings/globalPermissionGrants/allow` list does. `deny` *is* honored. So on current builds this hook's practical value is a **deny-only guardrail** plus artifact auto-approval; whitelisted commands still prompt unless you add them to that global list. Evidence and reproduction: `docs/FINDINGS-antigravity-hook-decisions.md`.

Caveat: the ignore-`allow` behavior was proven for `run_command` only. Whether the host also ignores `allow` for file tools (and thus still prompts for artifact writes) is **unverified** on this build; the artifact `allow` is correct per the documented contract and takes effect on any host that honors `allow`.

## Residual risk

> The blocklist is defense-in-depth, not a security boundary. A novel destructive command that Jev classifies `standard_dev` with confidence ≥ 0.96 would be auto-approved. Mitigations: the threshold, the blocklist, chain splitting, and the audit log review loop. Raise `CONFIDENCE_THRESHOLD` toward 0.98 after reviewing logs.

## Install

From the repository root, on Windows (Git Bash or PowerShell):

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe scripts/install_hook.py
```

The installer renders `hooks.template.json` to `.agents/hooks.json` with this machine's venv interpreter and prints a block for global use (see [Global install](#global-install)). If it reports that `typesafe-sdk` is not importable, install it into the venv first:

```bash
.venv/Scripts/python.exe -m pip install typesafe-sdk
```

Then configure your TypeSafe API key. Put `TYPESAFE_API_KEY=...` in `~/.gemini/config/jev.env` (create the file if it does not exist). **Never commit the key** — it lives in your user config directory, outside the repository.

Verify the setup with the live smoke script (one real Jev call; manual use only):

```bash
.venv/Scripts/python.exe scripts/smoke_live.py
```

A successful run prints a line like `category=standard_dev confidence=0.9xx latency_ms=~100`. If the key is missing you get `TYPESAFE_API_KEY is not configured (env or ~/.gemini/config/jev.env).` and exit code 1. Finally, **restart Antigravity** so it picks up the new hook configuration.

## Configuration

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

**Windows note:** hook processes are spawned by the Antigravity GUI and do **not** inherit shell-profile environment variables (anything set in `.bashrc`, PowerShell profiles, or similar). Configuration therefore loads from files, not just process env — put your key and any overrides in `~/.gemini/config/jev.env`.

## Global install

`.agents/hooks.json` only covers this one workspace. To evaluate commands in every Antigravity session, paste the block the installer printed after `--- global install: paste the block below into ~/.gemini/config/hooks.json ---` into `~/.gemini/config/hooks.json`. It looks like this (the interpreter and evaluator paths are machine-specific — use your installer's output, not this sample):

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
            "command": "\"<path/to/antigravity-approval>/.venv/Scripts/python.exe\" \"<path/to/antigravity-approval>/scripts/jev_evaluator.py\" --event PreToolUse",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Restart Antigravity after editing `hooks.json`.

## Tuning

Every decision is appended to the audit log at `~/.gemini/logs/jev_evaluator.log` (JSONL, one object per line, rotated at 5 MB × 3 backups). Review it to see which tier decides what, and how:

```bash
grep -o '"tier": "[^"]*"' ~/.gemini/logs/jev_evaluator.log | sort | uniq -c
grep -o '"decision": "[^"]*"' ~/.gemini/logs/jev_evaluator.log | sort | uniq -c
```

Adjustments, made in `~/.gemini/config/jev.env` (or via process env), take effect on the next hook invocation:

- **`CONFIDENCE_THRESHOLD`** — raise it (e.g. `0.98`) to auto-approve only near-certain verdicts; lower it to send fewer borderline commands to `ask`. Start at the default `0.96` and tighten after reviewing the log.
- **`ALLOW_NETWORK_COMMANDS`** — leave `false` to force every network command (including package installs) through `ask` before Jev is ever consulted. Set `true` only if you accept Jev auto-approving `network_outbound` commands at or above the confidence threshold.

**`JEV_FAIL_MODE=open` warning:** the default `closed` escalates Tier 2 errors to `ask`. Setting `JEV_FAIL_MODE=open` instead emits `allow` whenever the Jev call errors or times out — an outage then becomes silent approval. Use it only in sandboxes or CI where nothing valuable can be destroyed; never on a machine with real work or credentials.

## Uninstall

Remove the `jev-evaluator` block from `~/.gemini/config/hooks.json` (global) and/or delete `.agents/hooks.json` (per-workspace), then restart Antigravity. Optionally also delete the venv (`.venv/`) and your `~/.gemini/config/jev.env` to remove the key from disk.
