# src/jev_eval/deterministic.py
"""Tier 1: deterministic evaluation. Standard library only (spec §6.3)."""
from __future__ import annotations

import os
import re
import shlex

_MASK = "\x00"

def _mask_quoted(text: str, quote_chars: str) -> str:
    """Replace the interior of quoted spans with NULs; the quote characters stay."""
    out = list(text)
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                out[i] = _MASK
        elif ch in quote_chars:
            quote = ch
    return "".join(out)

_FD_REDIRECT_RE = re.compile(r"\d?>&\d?")   # 2>&1, >&2 — FD-to-FD, not a file write
_TIE_RE = re.compile(r">\|")                # >| — noclobber override, not a pipe
_CHAIN_SPLIT_RE = re.compile(r"&&|\|\||\r?\n|[;|&]")

def _mask_for_split(text: str) -> str:
    masked = _mask_quoted(text, "\"'")
    masked = _FD_REDIRECT_RE.sub(lambda m: _MASK * len(m.group()), masked)
    masked = _TIE_RE.sub(_MASK * 2, masked)
    return masked

def split_chain(command: str) -> list[str]:
    """Split on unquoted operators; return non-empty ORIGINAL text segments."""
    if not command:
        return []
    masked = _mask_for_split(command)
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _CHAIN_SPLIT_RE.finditer(masked):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(command)))
    return [command[a:b].strip() for a, b in spans if command[a:b].strip()]

def tokenize(segment: str) -> list[str] | None:
    """Quote-stripped tokens (posix=False keeps backslashes); None if unparsable."""
    try:
        raw = shlex.split(segment, posix=False)
    except ValueError:
        return None
    tokens: list[str] = []
    for tok in raw:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        if tok:
            tokens.append(tok)
    return tokens

_WRITE_CMDLET_RE = re.compile(r"\b(?:out-file|set-content|add-content|tee)\b", re.IGNORECASE)

def has_write_operator(segment: str) -> bool:
    """Unquoted file redirection or write cmdlet. FD redirections (2>&1) don't count."""
    masked = _mask_quoted(segment, "\"'")
    masked = _FD_REDIRECT_RE.sub("", masked)
    return ">" in masked or bool(_WRITE_CMDLET_RE.search(masked)) or bool(
        re.search(r"(?:^|\s)--output=", masked))

_SUBST_RE = re.compile(r"`|\$\(|<\(")

def has_substitution(segment: str) -> bool:
    """$(), backticks, <(. Single-quoted spans suppress expansion; double-quoted don't."""
    return bool(_SUBST_RE.search(_mask_quoted(segment, "'")))

_BLOCKLIST_TESTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\b[^;|&]*-\w*r\w*f", re.IGNORECASE), "rm recursive force"),
    (re.compile(r"\brm\b[^;|&]*-\w*f\w*r", re.IGNORECASE), "rm force recursive"),
    (re.compile(r"\brm\b(?=[^;|&]*\s-\w*r\b)(?=[^;|&]*\s-\w*f\b)", re.IGNORECASE),
     "rm separated recursive force"),
    (re.compile(r"\brm\b[^;|&]*--recursive\b", re.IGNORECASE), "rm --recursive"),
    (re.compile(r"\bmkfs", re.IGNORECASE), "mkfs"),
    (re.compile(r"\bdd\b\s+if=", re.IGNORECASE), "dd raw write"),
    (re.compile(r":\s*\(\s*\)\s*\{"), "fork bomb"),
    (re.compile(r"\bremove-item\b[^;|&]*-recurse\b[^;|&]*-force\b"
                r"|\bremove-item\b[^;|&]*-force\b[^;|&]*-recurse\b", re.IGNORECASE),
     "Remove-Item -Recurse -Force"),
    (re.compile(r"\bformat-volume\b|\bformat\s+[a-z]:", re.IGNORECASE), "disk format"),
    (re.compile(r"\b(?:del|rd|rmdir)\s+/s\b", re.IGNORECASE), "cmd.exe recursive delete"),
    (re.compile(r"\.(?:ssh|aws|gnupg)\b|/etc/(?:passwd|shadow|sudoers)\b"
                r"|\bid_rsa\b|\bid_ed25519\b|\.pem\b|\.env\b", re.IGNORECASE),
     "credential/secret file access"),
    (re.compile(r"\b(?:curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^;|&]*"
                r"\|\s*(?:sh|bash|zsh|ksh|powershell|pwsh|python3?)\b"
                r"|\binvoke-expression\b|\biex\s*\(", re.IGNORECASE),
     "remote code execution pattern"),
]

_SHELL_INNER_RES = [
    # cmd /c "inner" (optionally cmd.exe, with other switches before /c)
    re.compile(r"^\s*cmd(?:\.exe)?\s+(?:/[a-z]\s+)*?/c\s+\"(.*)\"\s*$", re.IGNORECASE),
    # powershell / pwsh -Command "inner"
    re.compile(r"^\s*powershell(?:\.exe)?\s+(?:-[a-z]+\s+)*?-c(?:ommand)?\s+\"(.*)\"\s*$",
               re.IGNORECASE),
    re.compile(r"^\s*pwsh(?:\.exe)?\s+(?:-[a-z]+\s+)*?-c(?:ommand)?\s+\"(.*)\"\s*$", re.IGNORECASE),
]

def _shell_inner(segment: str) -> str | None:
    """Inner command text for `cmd /c "…"`, `powershell -Command "…"` wrappers.

    In a shell-invocation segment the quoted content IS the command, not
    prose — quote-masking must not hide it from the blocklist.
    """
    for rx in _SHELL_INNER_RES:
        m = rx.match(segment)
        if m:
            return m.group(1)
    return None

def _blocklist_scan_texts(segment: str) -> list[str]:
    scans = [_mask_quoted(segment, "\"'")]
    if has_substitution(segment):
        scans.append(segment)  # raw: masking would hide $(rm
    inner = _shell_inner(segment)
    if inner is not None:
        scans.append(_mask_quoted(inner, "\"'"))
        if has_substitution(inner):
            scans.append(inner)
    return scans

def blocklist_hit(segment: str) -> str | None:
    """Reason label if the segment matches the blocklist, else None.

    Scans quote-masked text (protects quoted prose). Substitution-bearing
    segments are additionally scanned raw — the tokenizer glues `$(rm` into
    one token that masking would otherwise hide (spec §6.3). Shell-invocation
    wrappers (`cmd /c "…"`, `powershell -Command "…"`) are additionally
    scanned at their inner command, whose quoted content is the command
    itself, not prose.
    """
    for scanned in _blocklist_scan_texts(segment):
        for pattern, label in _BLOCKLIST_TESTS:
            if pattern.search(scanned):
                return label
    return None

_NETWORK_FIRST = frozenset({
    "curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "telnet", "ftp",
    "invoke-webrequest", "iwr", "invoke-restmethod", "irm",
})
_PKG_INSTALL_RE = re.compile(
    r"^(?:npm|pnpm|yarn|bun|pip|pip3|uv|poetry|cargo|dotnet|gem|composer)\s+"
    r"(?:install|i|add|publish)\b", re.IGNORECASE)

def is_network_command(segment: str, tokens: list[str] | None) -> bool:
    if tokens:
        first = tokens[0].lower()
    else:
        parts = segment.split()
        first = parts[0].lower() if parts else ""
    return first in _NETWORK_FIRST or bool(_PKG_INSTALL_RE.match(segment.strip()))

_WHITELIST_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("git", "status"), ("git", "diff"), ("git", "log"), ("git", "show"),
    ("git", "--version"),
    ("ls",), ("dir",), ("pwd",), ("echo",), ("cat",), ("type",), ("get-content",),
    ("select-string",), ("grep",), ("findstr",), ("head",), ("tail",), ("more",), ("out-host",),
    ("python", "--version"), ("python3", "--version"),
    ("node", "--version"), ("npm", "--version"),
)

def is_whitelisted(tokens: list[str]) -> bool:
    if not tokens:
        return False
    lowered = [t.lower() for t in tokens]
    return any(lowered[:len(prefix)] == list(prefix) for prefix in _WHITELIST_PREFIXES)

from typing import NamedTuple

class Tier1Outcome(NamedTuple):
    decision: str  # allow | deny | ask | force_ask
    reason: str
    tier: str      # blocklist | whitelist | path_guard | network_gate | write_policy | artifact | fallback

def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(p)))

def _inside(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip(os.sep) + os.sep) for r in roots)

def _system_dirs() -> list[str]:
    dirs = ["/etc", "/usr", "/bin", os.path.expanduser("~/.ssh")]
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
        val = os.environ.get(var)
        if val:
            dirs.append(val)
    return [_norm(d) for d in dirs]

def _credential_dirs() -> list[str]:
    dirs = [os.path.expanduser("~/.ssh"), os.path.expanduser("~/.gnupg")]
    return [_norm(d) for d in dirs]

class PathCheck(tuple):
    """Result of check_file_target: (decision, reason). Inherits from tuple for compatibility."""
    def __new__(cls, decision: str, reason: str):
        return super().__new__(cls, (decision, reason))

    @property
    def decision(self) -> str:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return item in self[0] or item in self[1]
        return super().__contains__(item)

def _expand_target(target: str, cwd: str) -> str:
    p = os.path.expanduser(target)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return p

def check_file_target(target: str, cwd: str, workspace_paths: list[str],
                      extra_roots: list[str] | None = None,
                      path_policy: str = "strict_deny") -> tuple[str, str] | None:
    """Strict dual containment: lexical abspath AND realpath must be inside a workspace.

    `extra_roots` carries host-sanctioned write locations outside the workspace —
    notably the hook payload's `artifactDirectoryPath`, where Antigravity stores
    per-conversation artifacts (implementation_plan.md, walkthrough.md, …). Without
    it those legitimate writes were hard-denied as "outside workspace".

    Security check order:
    1. System and credential directories -> hard deny
    2. Workspace boundaries -> ask (strategy_c) or deny (strict_deny)
    """
    if not target:
        return PathCheck("deny", "file tool missing target path")
    p = _expand_target(target, cwd)
    lex = _norm(p)
    real = _norm(os.path.realpath(p))

    # STEP 1 (SECURITY ORDERING): System & Credential Check FIRST
    for d in _system_dirs() + _credential_dirs():
        if _inside(lex, [d]) or _inside(real, [d]):
            return PathCheck("deny", "target path in system directory or sensitive credential")

    # STEP 2: Workspace Boundary Check
    roots = [_norm(w) for w in (workspace_paths or [])]
    roots += [_norm(r) for r in (extra_roots or []) if r]
    lex_in, real_in = _inside(lex, roots), _inside(real, roots)
    if not (lex_in and real_in):
        if lex_in != real_in:
            reason = (f"junction/symlink target outside workspace "
                      f"(lex inside={lex_in}, realpath inside={real_in})")
        else:
            reason = "target path outside workspace"
        if path_policy == "strategy_c":
            return PathCheck("ask", reason)
        return PathCheck("deny", reason)
    return None

_ARTIFACT_EXCLUDED_DIR = ".system_generated"
_ARTIFACT_EXCLUDED_SUFFIX = ".metadata.json"

def _is_sanctioned_artifact(target: str, cwd: str, extra_roots: list[str] | None) -> bool:
    """True when the target is a host-sanctioned per-conversation artifact we auto-approve.

    The host supplies `artifactDirectoryPath`; writes there are its own scratch (task
    artifacts, implementation plans), so prompting is pure friction. Host internals
    under it are excluded so an auto-approved path can't rewrite transcripts or
    artifact metadata.
    """
    roots = [_norm(r) for r in (extra_roots or []) if r]
    if not roots:
        return False
    lex = _norm(_expand_target(target, cwd))
    if not _inside(lex, roots):
        return False
    if _ARTIFACT_EXCLUDED_DIR in lex.split(os.sep):
        return False
    return not os.path.basename(lex).endswith(_ARTIFACT_EXCLUDED_SUFFIX)

_FILE_TOOLS = frozenset({"write_to_file", "replace_file_content", "multi_replace_file_content"})

def evaluate_tool_call(tool_name: str, command: str, cwd: str, target: str,
                       workspace_paths: list[str], allow_network: bool,
                       extra_write_roots: list[str] | None = None,
                       path_policy: str = "strict_deny") -> Tier1Outcome | None:
    """Matrix rows 1-4 and 7. None = run_command falls through to Tier 2 (or unknown tool)."""
    if tool_name in _FILE_TOOLS:
        hit = check_file_target(target, cwd, workspace_paths, extra_roots=extra_write_roots,
                                path_policy=path_policy)
        if hit is not None:
            decision, reason = hit
            return Tier1Outcome(decision, reason, "path_guard")
        if _is_sanctioned_artifact(target, cwd, extra_write_roots):
            return Tier1Outcome("allow", "artifact: host-sanctioned conversation artifact",
                                "artifact")
        return Tier1Outcome("ask", "file mutations are not auto-approved in v1", "write_policy")
    if tool_name != "run_command":
        return None
    segments = split_chain(command)
    if not segments:
        return Tier1Outcome("ask", "empty or unparsable command", "fallback")
    subst = [has_substitution(seg) for seg in segments]
    for seg in segments:
        hit = blocklist_hit(seg)
        if hit:
            return Tier1Outcome("deny", f"blocklist: {hit}", "blocklist")
    whitelisted = True
    for seg, is_subst in zip(segments, subst):
        tokens = tokenize(seg)
        if tokens is None or is_subst or has_write_operator(seg) or not is_whitelisted(tokens):
            whitelisted = False
            break
        lowered = [t.lower() for t in tokens]
        if "-o" in lowered or any(t.startswith("--output=") for t in lowered):
            whitelisted = False
            break
    if whitelisted:
        return Tier1Outcome("allow", "whitelist: read-only command", "whitelist")
    if not allow_network:
        for seg, tokens in ((s, tokenize(s)) for s in segments):
            if is_network_command(seg, tokens):
                return Tier1Outcome("force_ask", f"network command: {seg!r}", "network_gate")
    return None
