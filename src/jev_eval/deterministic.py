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
    masked = _FD_REDIRECT_RE.sub(_MASK * 4, masked)
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
