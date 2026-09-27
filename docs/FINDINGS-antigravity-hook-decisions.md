# Findings — what Antigravity's PreToolUse hook decisions actually do (2.0 app)

**Status: CONCLUSIVE, evidence-backed.** Supersedes the reasoning in
`docs/BUGREPORT-antigravity-pretooluse-allow-ignored.md` and the "host bug" /
"chain policy" theories. Product under test: `Programs/antigravity/Antigravity.exe`
(the 2.0 **app**, state `~/.gemini/antigravity`), tested 2026-09-20 with provable
stub markers (`scripts/_stub_probe.log`) + host transcripts.

## The four verified facts

| # | Input | Host behavior | Evidence |
|---|---|---|---|
| 1 | hook `{"decision":"deny"}` | **Hard-blocked**, no dialog, our exact reason shown | marker 08:33:22 + transcript `e297e7d3` ("tool call denied by pre-tool hook: stub deny: unconditional block") |
| 2 | hook `{"decision":"allow"}` | **Dialog** (not honored) | command `git diff --stat` after removing it from the global allow list; stub marker confirms `allow` emitted |
| 3 | hook `{"decision":"allow"}` + `permissionOverrides:["command(git diff --stat)"]` | **Dialog** (not honored) | marker 08:26:04 (override stub fired, emitted the override) + dialog |
| 3b | hook `allow` installed at **global** scope (`~/.gemini/config/hooks.json`), workspace hook removed | **Dialog** (not honored) | marker 11:43:27 with `cwd=C:\Users\zjply\.gemini\config` (global hook) + transcript `d530c951` stops at `PLANNER_RESPONSE`. Rules out hook *scope* as the cause. |
| 4 | command present in `userSettings/globalPermissionGrants/allow` | **No dialog** (auto-approved) | `git diff --stat` ran while listed; prompted the moment it was removed |

## Conclusion

**The hook can BLOCK but cannot AUTO-APPROVE on this build.**
`deny` is read and acted on. Every positive decision (`allow`, `allow`+`permissionOverrides`)
is ignored and falls through to the permission dialog. The **only** mechanism that
suppresses the dialog is Antigravity's own static list
`~/.gemini/config/config.json → userSettings/globalPermissionGrants/allow`
(exact command strings, e.g. `command(git status)`).

This is an **asymmetric host behavior**: the documented contract says `"allow"`
"Automatically allows the tool execution" (antigravity.google/docs/hooks), but it does not.
Ruled out as causes: payload shape (matches docs), `permissionOverrides` (optional per
docs, tested anyway), hook **scope** (workspace *and* global both ignored), stdin/latency,
and command shape (the earlier single-vs-chain differential was a grant-list artifact).
`deny` from workspace scope *is* honored, proving the host reads hook stdout.
Whether the allow-ignore is a bug or an undocumented "hook may veto but not grant" design,
the operational result is the same: **the jev-evaluator's auto-approve tier cannot work
through the hook on this build.**

## Two wrong turns, corrected (so they aren't repeated)

1. **The original bug report's Probe E evidence did not exist.** It claimed a
   transcript denial at 21:32:57; no such record exists in any log/transcript, and
   `stub_deny.py` wrote no marker (it had no logging). The report's *conclusion*
   (deny honored / allow ignored) happens to be correct, but it is now proven by the
   clean tests above, not by that report.
2. **A "single vs chained command" theory was a grant-list artifact.** Singles
   (`git status`, `git log -n 5`) appeared to auto-approve only because they were in
   `globalPermissionGrants/allow`; the chain `git status; git log -n 5` prompted only
   because that exact string was *not* in the list. The list itself contains chains,
   so there is no "chains are blocked" policy. **Grants are the confounder — always
   check `globalPermissionGrants/allow` membership before trusting any "it worked."**

## Implications for this project

- **Shipping value today = deny-only guardrail.** The hook reliably blocks dangerous
  commands (blocklist / Jev `destructive` → `deny`). Keep and rely on that.
- **Auto-approve via the hook is not achievable on this build.** Options:
  (a) accept that safe commands prompt (or are manually added to the global allow list);
  (b) file the allow-not-honored behavior with Google using the evidence above;
  (c) treat `globalPermissionGrants/allow` as the grant mechanism (exact-match, static,
      requires mutating host config — fragile; not recommended for dynamic evaluation).
- **Test hygiene:** use `scripts/set_probe_hook.py` to switch targets (always renders the
  venv interpreter); stubs now write provable markers; verify
  `globalPermissionGrants/allow` membership and recent `~/.gemini/antigravity/crashes`
  before trusting any result.

## Repo changes made while closing this out (2026-09-20)

- **False-deny fix:** the path guard previously hard-denied writes to the host's
  per-conversation artifact directory (`artifactDirectoryPath`, outside the workspace).
  It now accepts that directory as a sanctioned write root.
- **Artifact auto-approve:** writes inside `artifactDirectoryPath` are `allow`
  (tier `artifact`), excluding `.system_generated/**` and `*.metadata.json` (those stay
  `ask`); all other file writes remain `ask`. Note this `allow` is only dialog-suppressing
  on hosts that honor `allow` — unverified for file tools on the current 2.0 app (see
  README caveat).
