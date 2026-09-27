# src/jev_eval/file_guard.py
"""File screening guard for Jev Tier 1 (safe source whitelist & sensitive files)."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .deterministic import Tier1Outcome

SAFE_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    # Backend
    ".py", ".pyi", ".go", ".rs", ".java", ".kt", ".kts", ".c", ".cpp",
    ".cc", ".cxx", ".h", ".hpp", ".hxx", ".cs", ".php", ".rb", ".swift",
    ".scala", ".lua", ".sh", ".bash", ".zsh", ".ps1",
    # Frontend
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".astro", ".html", ".htm", ".css", ".scss", ".sass", ".less",
    # Docs & Query
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".sql", ".graphql", ".gql",
})

_SENSITIVE_EXTENSIONS: frozenset[str] = frozenset({
    ".pem", ".key", ".pfx", ".p12", ".keystore", ".cert", ".crt", ".der", ".pub", ".env",
})

_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "secret", "credential", "token", "password", "private_key",
    "id_rsa", "id_ed25519",
)

_SENSITIVE_REPO_META: frozenset[str] = frozenset({
    ".gitignore", ".gitattributes", ".gitmodules",
})

_SENSITIVE_DEPENDENCY_FILES: frozenset[str] = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "requirements.txt", "pipfile", "pipfile.lock", "poetry.lock", "pyproject.toml",
    "setup.py", "setup.cfg", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
})

_SENSITIVE_DIR_NAMES: frozenset[str] = frozenset({
    ".git", ".github", ".gitlab", ".circleci", ".buildkite",
})


def is_sensitive_file(target: str, cwd: str = "") -> bool:
    """Check whether target (normalized and expanded) matches sensitive patterns."""
    if not target:
        return False

    p = os.path.expanduser(target)
    if not os.path.isabs(p) and cwd:
        p = os.path.join(cwd, p)

    norm = os.path.normpath(p).replace("\\", "/")
    raw_segments = [seg for seg in norm.split("/") if seg and seg != "."]

    # Filter out Windows drive letters from segments check (e.g. 'c:')
    segments: list[str] = []
    for seg in raw_segments:
        if len(seg) == 2 and seg[1] == ":" and seg[0].isalpha():
            continue
        segments.append(seg.lower())

    if not segments:
        return False

    # Directory path segments check:
    # Any directory component in the path is .git, .github, .gitlab, .circleci, .buildkite
    if any(seg in _SENSITIVE_DIR_NAMES for seg in segments):
        return True

    # Basename case-insensitive check
    basename = segments[-1]

    # Starts with or ends with .env (e.g. .env, .env.local, .env.test, production.env)
    if basename.startswith(".env") or basename.endswith(".env"):
        return True

    # Extensions: .pem, .key, .pfx, .p12, .keystore, .cert, .crt, .der, .pub, .env
    _, ext = os.path.splitext(basename)
    if ext in _SENSITIVE_EXTENSIONS or any(basename.endswith(e) for e in _SENSITIVE_EXTENSIONS):
        return True

    # Basename contains any of: secret, credential, token, password, private_key, id_rsa, etc.
    for kw in _SENSITIVE_KEYWORDS:
        if kw in basename:
            if kw == "token" and ("tokeniz" in basename or "tokenize" in basename):
                continue
            return True

    # Special repo meta files: .gitignore, .gitattributes, .gitmodules
    if basename in _SENSITIVE_REPO_META:
        return True

    # Dependency/build definitions & requirements variants
    if basename in _SENSITIVE_DEPENDENCY_FILES:
        return True
    if basename.startswith("requirements") and (ext in (".txt", ".in") or basename.endswith(".txt") or basename.endswith(".in")):
        return True

    # Container/orchestration: dockerfile, dockerfile-dev, dockerfile.prod, docker-compose*
    if basename == "dockerfile" or basename.startswith("dockerfile.") or basename.startswith("dockerfile-") or basename.startswith("docker-compose"):
        return True

    return False


def is_safe_source_file(target: str, cwd: str = "", _checked_sensitive: bool = False) -> bool:
    """True if target is not sensitive and its extension is in SAFE_SOURCE_EXTENSIONS."""
    if not target:
        return False
    if not _checked_sensitive and is_sensitive_file(target, cwd):
        return False
    norm = target.replace("\\", "/")
    basename = norm.rstrip("/").split("/")[-1]
    _, ext = os.path.splitext(basename)
    return ext.lower() in SAFE_SOURCE_EXTENSIONS


def evaluate_file_write(
    target: str,
    cwd: str,
    workspace_paths: list[str],
    extra_roots: list[str] | None = None,
    path_policy: str = "strict_deny",
) -> Tier1Outcome:
    """Screen file writes: path guard -> artifact -> sensitive file -> safe source -> write policy."""
    from .deterministic import Tier1Outcome, check_file_target, _is_sanctioned_artifact
    from .formatter import format_tier1_reason

    # 1. System directory and outside workspace escapes
    hit = check_file_target(target, cwd, workspace_paths, extra_roots=extra_roots, path_policy=path_policy)
    if hit is not None:
        decision, reason = hit
        return Tier1Outcome(decision, format_tier1_reason("path_guard", reason, target, decision=decision), "path_guard")

    # 2. Host artifacts (e.g. conversation artifacts, memories)
    if _is_sanctioned_artifact(target, cwd, extra_roots):
        return Tier1Outcome(
            "allow",
            format_tier1_reason("artifact", "artifact: host-sanctioned conversation artifact", target, decision="allow"),
            "artifact",
        )

    # 3. Workspace sensitive files
    if is_sensitive_file(target, cwd):
        return Tier1Outcome(
            "ask",
            format_tier1_reason("sensitive_file", "sensitive configuration or project file", target, decision="ask"),
            "sensitive_file",
        )

    # 4. Workspace safe source files (skip redundant sensitive check)
    if is_safe_source_file(target, cwd, _checked_sensitive=True):
        return Tier1Outcome(
            "allow",
            format_tier1_reason("safe_source", "safe workspace source file", target, decision="allow"),
            "safe_source",
        )

    # 5. Fallback
    return Tier1Outcome(
        "ask",
        format_tier1_reason("write_policy", "unrecognized or non-whitelisted file extension", target, decision="ask"),
        "write_policy",
    )
