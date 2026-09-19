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
    return ">" in masked or bool(_WRITE_CMDLET_RE.search(masked))

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
