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

def blocklist_hit(segment: str) -> str | None:
    """Reason label if the segment matches the blocklist, else None.

    Scans quote-masked text (protects quoted prose). Substitution-bearing
    segments are additionally scanned raw — the tokenizer glues `$(rm` into
    one token that masking would otherwise hide (spec §6.3).
    """
    scanned = _mask_quoted(segment, "\"'")
    for pattern, label in _BLOCKLIST_TESTS:
        if pattern.search(scanned):
            return label
    if has_substitution(segment):
        for pattern, label in _BLOCKLIST_TESTS:
            if pattern.search(segment):
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
    tier: str      # blocklist | whitelist | path_guard | network_gate | write_policy | fallback

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

def check_file_target(target: str, cwd: str, workspace_paths: list[str]) -> str | None:
    """Strict dual containment: lexical abspath AND realpath must be inside a workspace."""
    if not target:
        return "file tool missing target path"
    p = os.path.expanduser(target)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    lex = _norm(p)
    real = _norm(os.path.realpath(p))
    roots = [_norm(w) for w in (workspace_paths or [])]
    lex_in, real_in = _inside(lex, roots), _inside(real, roots)
    if not (lex_in and real_in):
        if lex_in != real_in:
            return (f"junction/symlink target outside workspace "
                    f"(lex inside={lex_in}, realpath inside={real_in})")
        return "target path outside workspace"
    for d in _system_dirs():
        if _inside(lex, [d]) or _inside(real, [d]):
            return "target path in system directory"
    return None

_FILE_TOOLS = frozenset({"write_to_file", "replace_file_content", "multi_replace_file_content"})

def evaluate_tool_call(tool_name: str, command: str, cwd: str, target: str,
                       workspace_paths: list[str], allow_network: bool) -> Tier1Outcome | None:
    """Matrix rows 1-4 and 7. None = run_command falls through to Tier 2 (or unknown tool)."""
    if tool_name in _FILE_TOOLS:
        reason = check_file_target(target, cwd, workspace_paths)
        if reason:
            return Tier1Outcome("deny", reason, "path_guard")
        return Tier1Outcome("ask", "file mutations are not auto-approved in v1", "write_policy")
    if tool_name != "run_command":
        return None
    segments = split_chain(command)
    if not segments:
        return Tier1Outcome("ask", "empty or unparsable command", "fallback")
    subst = [has_substitution(seg) for seg in segments]
    for seg, is_subst in zip(segments, subst):
        scans = [_mask_quoted(seg, "\"'")]
        if is_subst:
            scans.append(seg)  # raw text: masking would hide $(rm
        for scanned in scans:
            hit = next((label for pattern, label in _BLOCKLIST_TESTS if pattern.search(scanned)), None)
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
