# Bug report: `PreToolUse` honors `deny` but ignores `allow`

> **SUPERSEDED 2026-09-20 — do not file as-is.** The *conclusion* (deny honored,
> allow ignored) is correct and is now proven by clean tests, but this document's
> supporting evidence is invalid: its "Probe E transcript denial at 21:32:57" does not
> exist in any log or transcript, and `stub_deny.py` wrote no marker. It also mislabels
> the product as "Antigravity IDE 2.5.5"; the clean reproduction was on the **2.0 app**
> (`Programs/antigravity`). Every "allow worked" observation it discounts was in fact a
> `userSettings/globalPermissionGrants/allow` grant-list artifact. See
> `docs/FINDINGS-antigravity-hook-decisions.md` for the verified evidence and the
> corrected statement (hook can block, cannot auto-approve; the global allow list is
> the only grant mechanism).

## Product and build

- Product: Antigravity IDE for Windows
- IDE file/product version: `2.5.5`
- Language server version: `2.5.5`
- App package version: `1.107.0`
- Distro: `0c7d350c3a9e8639ea238cc996ec4f6dcf1e35cd`
- Date reproduced: 2026-09-19 (UTC+8)

## Summary

A project-level `PreToolUse` command hook is executed and its JSON stdout is
parsed, but positive decisions do not authorize a `run_command` tool call.
Antigravity still opens the normal permission dialog. The same hook boundary
does honor a negative decision immediately and displays the supplied reason.

This is asymmetric behavior in the host, not a hook spawn, stdin, latency, or
JSON-output problem.

## Expected behavior

The hook contract embedded in this build says:

> `"allow"`: Automatically allow the tool execution.

Therefore a hook response of `{"decision":"allow"}` should let the command
execute without showing the permission dialog.

## Actual behavior

| Hook response | Actual result |
|---|---|
| `{"decision":"allow"}` | Permission dialog |
| `{"decision":"allow","permissionOverrides":["command(git diff --stat)"]}` | Permission dialog |
| `{"allowTool":true}` (deprecated compatibility field) | Permission dialog |
| `{"decision":"deny","reason":"stub E: deny test - everything blocked"}` | Immediately blocked; exact reason shown |

The failing `allow` transcript stops after `PLANNER_RESPONSE`; there is no tool
execution/result step. The `deny` transcript contains an `ERROR_MESSAGE` with:

```text
invalid tool call error (invalid_args) tool call denied with reason:
stub E: deny test - everything blocked
```

## Minimal reproduction

Configure a project `.agents/hooks.json` with a `PreToolUse` command hook that
matches `run_command`:

```json
{
  "repro": {
    "enabled": true,
    "PreToolUse": [
      {
        "matcher": "run_command",
        "hooks": [
          {
            "type": "command",
            "command": "C:/path/to/python.exe C:/path/to/stub.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Use this `stub.py`:

```python
import json
print(json.dumps({"decision": "allow", "reason": "minimal allow repro"}), flush=True)
```

Open the project in a fresh Antigravity window and, in a new conversation,
request a command that has no cached grant, for example:

```text
git diff --stat
```

Observed: the permission dialog appears.

Change only the stub response to:

```python
print(json.dumps({"decision": "deny", "reason": "minimal deny repro"}), flush=True)
```

Observed: the call is blocked immediately and `minimal deny repro` is reported.

## Controls already tested

- Hook process execution was independently recorded with PID and timestamps.
- A real evaluator emitted `allow` in about 85 ms; the dialog still appeared.
- An immediate stub that does not read stdin behaved the same way.
- Stubs that drain stdin and that delay 300 ms behaved the same way.
- JSON output is newline-terminated and stdout contains exactly one object.
- Hook command path is unquoted and space-free, avoiding the known `cmd.exe`
  quoting problem.
- Tests used new conversations and previously ungranted commands.
- The target workspace was verified as the workspace containing the hook.
- `permissionOverrides` used the exact documented grammar and command text.
- A `deny` control proves the host reads and acts on stdout.

## Relevant implementation evidence

The installed language-server binary contains:

- the documented `decision` enum (`allow`, `deny`, `ask`, `force_ask`);
- `permissionOverrides` described as temporary permission grants;
- deprecated `allowTool` and `denyReason` fields;
- `migrateDeprecatedFields` and `GetPermissionOverrides` code symbols.

Despite those paths being present, all positive variants fall through to the
ordinary permission dialog while `deny` terminates the tool call.

## Impact

`PreToolUse` hooks can enforce additional restrictions but cannot implement the
documented auto-approval use case. Safe commands still require manual approval,
making policy-based allowlisting ineffective.

## Suggested investigation area

Inspect the boundary between `applyPreToolHooks`/the hook result adapter and the
command permission assessor. The evidence suggests the denial branch is applied
before execution, while the positive branch still enters the ordinary command
permission policy without an effective temporary grant.

