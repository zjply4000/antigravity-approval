# tests/test_safe_source.py
from __future__ import annotations

import os
import sys
import pytest

from jev_eval.file_guard import (
    SAFE_SOURCE_EXTENSIONS,
    is_sensitive_file,
    is_safe_source_file,
    evaluate_file_write,
)
from jev_eval.deterministic import evaluate_tool_call


def test_safe_source_extensions_content():
    """Verify SAFE_SOURCE_EXTENSIONS is a frozenset containing expected extensions."""
    assert isinstance(SAFE_SOURCE_EXTENSIONS, frozenset)
    # Check all start with . and are lowercase
    for ext in SAFE_SOURCE_EXTENSIONS:
        assert ext.startswith("."), f"{ext} must start with dot"
        assert ext == ext.lower(), f"{ext} must be lowercase"

    # Backend
    for ext in [
        ".py", ".pyi", ".go", ".rs", ".java", ".kt", ".kts", ".c", ".cpp",
        ".cc", ".cxx", ".h", ".hpp", ".hxx", ".cs", ".php", ".rb", ".swift",
        ".scala", ".lua", ".sh", ".bash", ".zsh", ".ps1"
    ]:
        assert ext in SAFE_SOURCE_EXTENSIONS, f"{ext} missing from backend extensions"

    # Frontend
    for ext in [
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
        ".astro", ".html", ".htm", ".css", ".scss", ".sass", ".less"
    ]:
        assert ext in SAFE_SOURCE_EXTENSIONS, f"{ext} missing from frontend extensions"

    # Docs & Query
    for ext in [
        ".md", ".markdown", ".rst", ".txt", ".adoc", ".sql", ".graphql", ".gql"
    ]:
        assert ext in SAFE_SOURCE_EXTENSIONS, f"{ext} missing from docs/query extensions"

    # Non-whitelisted should NOT be in SAFE_SOURCE_EXTENSIONS
    for ext in [".bin", ".exe", ".dat", ".json", ".yaml", ".yml", ".toml", ".lock"]:
        assert ext not in SAFE_SOURCE_EXTENSIONS, f"{ext} should not be in safe source extensions"


def test_is_sensitive_file_env_variants():
    assert is_sensitive_file(".env")
    assert is_sensitive_file(".env.local")
    assert is_sensitive_file(".env.test")
    assert is_sensitive_file(".env.production")
    assert is_sensitive_file(".env.staging")
    assert is_sensitive_file("src/.env.local")
    assert is_sensitive_file("C:/project/.env")
    assert is_sensitive_file("production.env")
    assert is_sensitive_file("app.env")


def test_is_sensitive_file_crypto_keys():
    for ext in [".pem", ".key", ".pfx", ".p12", ".keystore", ".cert", ".crt", ".der", ".pub"]:
        assert is_sensitive_file(f"server{ext}")
        assert is_sensitive_file(f"certs/ca{ext}")
        assert is_sensitive_file(f"C:/ws/keys/id_rsa{ext}")
    assert is_sensitive_file("id_rsa.pub")
    assert is_sensitive_file("id_ed25519")
    assert is_sensitive_file("id_ed25519.pub")


def test_is_sensitive_file_keywords_in_basename():
    assert is_sensitive_file("token_storage.ts")
    assert is_sensitive_file("my_secret.py")
    assert is_sensitive_file("user_password.go")
    assert is_sensitive_file("aws_credentials.json")
    assert is_sensitive_file("private_key.txt")
    assert is_sensitive_file("SRC/TOKEN_AUTH.TS")


def test_is_sensitive_file_repo_meta():
    assert is_sensitive_file(".gitignore")
    assert is_sensitive_file(".gitattributes")
    assert is_sensitive_file(".gitmodules")
    assert is_sensitive_file("nested/.gitignore")


def test_is_sensitive_file_dependency_build_defs():
    deps = [
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
        "requirements.txt", "pipfile", "pipfile.lock", "poetry.lock", "pyproject.toml",
        "setup.py", "setup.cfg", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
        "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"
    ]
    for dep in deps:
        assert is_sensitive_file(dep), f"{dep} should be sensitive"
        assert is_sensitive_file(dep.upper()), f"{dep.upper()} should be sensitive"
        assert is_sensitive_file(f"subproject/{dep}"), f"subproject/{dep} should be sensitive"
    assert is_sensitive_file("requirements-dev.txt")
    assert is_sensitive_file("requirements_test.txt")
    assert is_sensitive_file("requirements.in")


def test_is_sensitive_file_container_orchestration():
    assert is_sensitive_file("Dockerfile")
    assert is_sensitive_file("dockerfile")
    assert is_sensitive_file("Dockerfile.dev")
    assert is_sensitive_file("Dockerfile-dev")
    assert is_sensitive_file("Dockerfile-production")
    assert is_sensitive_file("docker-compose.yml")
    assert is_sensitive_file("docker-compose.override.yaml")
    assert is_sensitive_file("docker-compose.prod.yml")


def test_is_sensitive_file_directory_segments():
    assert is_sensitive_file(".git/config")
    assert is_sensitive_file("src/.git/HEAD")
    assert is_sensitive_file(".github/workflows/ci.yml")
    assert is_sensitive_file(".gitlab/issue_templates/bug.md")
    assert is_sensitive_file(".circleci/config.yml")
    assert is_sensitive_file(".buildkite/pipeline.yml")
    # Using cwd
    assert is_sensitive_file("workflows/ci.yml", cwd="C:/project/.github")
    assert is_sensitive_file("HEAD", cwd="C:/project/.git")


def test_is_sensitive_file_normal_sources_not_sensitive():
    assert not is_sensitive_file("src/main.py")
    assert not is_sensitive_file("src/components/button.tsx")
    assert not is_sensitive_file("docs/guide.md")
    assert not is_sensitive_file("database/schema.sql")
    assert not is_sensitive_file("scripts/build_helper.py")
    assert not is_sensitive_file("styles/theme.css")
    assert not is_sensitive_file("src/crypto/ed25519.py")
    assert not is_sensitive_file("src/nlp/tokenizer.py")
    assert not is_sensitive_file("src/lexer/tokenize.py")


def test_is_safe_source_file():
    # Valid safe sources
    assert is_safe_source_file("src/main.py")
    assert is_safe_source_file("src/main.PY")
    assert is_safe_source_file("src/app.ts")
    assert is_safe_source_file("src/core.go")
    assert is_safe_source_file("src/App.vue")
    assert is_safe_source_file("docs/readme.md")
    assert is_safe_source_file("schema.sql")
    assert is_safe_source_file("src/crypto/ed25519.py")
    assert is_safe_source_file("src/nlp/tokenizer.py")

    # Sensitive files are NOT safe sources even if having safe extension
    assert not is_safe_source_file("setup.py")
    assert not is_safe_source_file("token_storage.ts")
    assert not is_safe_source_file("app_secret.py")
    assert not is_safe_source_file(".github/scripts/deploy.py")
    assert not is_safe_source_file(".gitignore")
    assert not is_safe_source_file("id_rsa.key")

    # Unknown / non-source extensions are NOT safe sources
    assert not is_safe_source_file("data.bin")
    assert not is_safe_source_file("app.exe")
    assert not is_safe_source_file("archive.dat")
    assert not is_safe_source_file("config.json")
    assert not is_safe_source_file("extensionless")


def test_evaluate_file_write_safe_source(tmp_path):
    ws = str(tmp_path / "workspace")
    target = f"{ws}/src/main.py"
    out = evaluate_file_write(target, ws, [ws], extra_roots=None, path_policy="strict_deny")
    assert out.decision == "allow"
    assert out.tier == "safe_source"
    assert "修改工作区源码文件 (main.py)" in out.reason


def test_evaluate_file_write_sensitive_file(tmp_path):
    ws = str(tmp_path / "workspace")
    for fname in [".env", ".env.local", "id_rsa.key", "token_storage.ts", "package.json", "pyproject.toml", ".gitignore"]:
        target = f"{ws}/{fname}"
        out = evaluate_file_write(target, ws, [ws], extra_roots=None, path_policy="strict_deny")
        assert out.decision == "ask", f"{fname} should ask"
        assert out.tier == "sensitive_file", f"{fname} tier should be sensitive_file"
        assert "修改敏感资产或关键配置" in out.reason


def test_evaluate_file_write_write_policy_fallback(tmp_path):
    ws = str(tmp_path / "workspace")
    for fname in ["data.bin", "app.exe", "data.dat", "extensionless"]:
        target = f"{ws}/{fname}"
        out = evaluate_file_write(target, ws, [ws], extra_roots=None, path_policy="strict_deny")
        assert out.decision == "ask", f"{fname} should ask"
        assert out.tier == "write_policy", f"{fname} tier should be write_policy"
        assert "写入非白名单文件类型" in out.reason


def test_evaluate_file_write_path_guard(tmp_path):
    ws = str(tmp_path / "workspace")
    outside = str(tmp_path / "outside" / "main.py")
    system_path = "C:/Windows/System32/test.py" if sys.platform == "win32" else "/etc/test.py"

    # Strict deny outside
    out_deny = evaluate_file_write(outside, ws, [ws], extra_roots=None, path_policy="strict_deny")
    assert out_deny.decision == "deny"
    assert out_deny.tier == "path_guard"

    # Strategy C outside -> ask
    out_ask = evaluate_file_write(outside, ws, [ws], extra_roots=None, path_policy="strategy_c")
    assert out_ask.decision == "ask"
    assert out_ask.tier == "path_guard"

    # System path -> always deny
    out_sys = evaluate_file_write(system_path, ws, [ws], extra_roots=None, path_policy="strategy_c")
    assert out_sys.decision == "deny"
    assert out_sys.tier == "path_guard"


def test_evaluate_file_write_artifact(tmp_path):
    ws = str(tmp_path / "workspace")
    artifact_root = str(tmp_path / "artifacts")
    artifact_file = f"{artifact_root}/plan.md"

    out = evaluate_file_write(artifact_file, ws, [ws], extra_roots=[artifact_root], path_policy="strict_deny")
    assert out.decision == "allow"
    assert out.tier == "artifact"
    assert "写入宿主专属对话工件" in out.reason


def test_engine_integration_file_tools(tmp_path):
    ws = str(tmp_path / "workspace")
    safe_target = f"{ws}/src/index.ts"
    sensitive_target = f"{ws}/package.json"
    unknown_target = f"{ws}/model.bin"

    for tool in ["write_to_file", "replace_file_content", "multi_replace_file_content"]:
        # Safe source
        out_safe = evaluate_tool_call(tool, "", ws, safe_target, [ws], allow_network=False)
        assert out_safe is not None
        assert out_safe.decision == "allow"
        assert out_safe.tier == "safe_source"

        # Sensitive file
        out_sens = evaluate_tool_call(tool, "", ws, sensitive_target, [ws], allow_network=False)
        assert out_sens is not None
        assert out_sens.decision == "ask"
        assert out_sens.tier == "sensitive_file"

        # Unknown / non-whitelisted
        out_unk = evaluate_tool_call(tool, "", ws, unknown_target, [ws], allow_network=False)
        assert out_unk is not None
        assert out_unk.decision == "ask"
        assert out_unk.tier == "write_policy"
