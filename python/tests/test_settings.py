from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from consilium.config import (  # pragma: allowlist secret
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_DATABASE_URL,
    DEFAULT_SLIDE_CACHE_MAX_GB,
    LlmProvider,
    SearchBackend,
    Settings,
    StorageBackend,
    get_settings,
    repo_root,
)


def test_local_defaults() -> None:
    settings = Settings()
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.storage_backend is StorageBackend.LOCAL
    assert settings.storage_root == repo_root() / "data"
    assert settings.slide_cache_dir == repo_root() / "data" / "cache" / "slides"
    assert settings.slide_cache_max_gb == DEFAULT_SLIDE_CACHE_MAX_GB
    assert settings.search_backend is SearchBackend.PGVECTOR
    assert settings.llm_provider is LlmProvider.ANTHROPIC
    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == DEFAULT_ANTHROPIC_MODEL
    assert settings.hf_token is None
    assert settings.databricks_host is None
    assert settings.databricks_token is None
    assert (settings.storage_root.parent / "docs" / "architecture.md").is_file()


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql://db.example/consilium"  # pragma: allowlist secret
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "uc_volume")
    monkeypatch.setenv("STORAGE_ROOT", "/Volumes/cohort")
    monkeypatch.setenv("SLIDE_CACHE_DIR", "/tmp/slide-cache")
    monkeypatch.setenv("SLIDE_CACHE_MAX_GB", "4.5")
    monkeypatch.setenv("SEARCH_BACKEND", "lakebase")
    monkeypatch.setenv("LLM_PROVIDER", "databricks")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("HF_TOKEN", "test-hf-token")
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "test-databricks-token")

    settings = get_settings()
    assert settings.database_url == database_url
    assert settings.storage_backend is StorageBackend.UC_VOLUME
    assert settings.storage_root == Path("/Volumes/cohort")
    assert settings.slide_cache_dir == Path("/tmp/slide-cache")
    assert settings.slide_cache_max_gb == 4.5
    assert settings.search_backend is SearchBackend.LAKEBASE
    assert settings.llm_provider is LlmProvider.DATABRICKS
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "test-anthropic-key"
    assert settings.anthropic_model == "claude-test"
    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "test-hf-token"
    assert settings.databricks_host == "https://example.cloud.databricks.com"
    assert settings.databricks_token is not None
    assert settings.databricks_token.get_secret_value() == "test-databricks-token"


def test_blank_values_keep_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=",
                "STORAGE_BACKEND=",
                "STORAGE_ROOT=",
                "SLIDE_CACHE_DIR=",
                "SLIDE_CACHE_MAX_GB=",
                "SEARCH_BACKEND=",
                "LLM_PROVIDER=",
                "ANTHROPIC_API_KEY=",
                "ANTHROPIC_MODEL=",
                "HF_TOKEN=",
                "DATABRICKS_HOST=",
                "DATABRICKS_TOKEN=",
                "",
            ]
        )
    )
    settings = Settings(_env_file=env_file)
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.storage_backend is StorageBackend.LOCAL
    assert settings.storage_root == repo_root() / "data"
    assert settings.search_backend is SearchBackend.PGVECTOR
    assert settings.llm_provider is LlmProvider.ANTHROPIC
    assert settings.anthropic_model == DEFAULT_ANTHROPIC_MODEL
    assert settings.anthropic_api_key is None
    assert settings.hf_token is None
    assert settings.databricks_host is None
    assert settings.databricks_token is None


def test_env_file_overrides_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("STORAGE_BACKEND=uc_volume\nSLIDE_CACHE_MAX_GB=3\n")
    settings = Settings(_env_file=env_file)
    assert settings.storage_backend is StorageBackend.UC_VOLUME
    assert settings.slide_cache_max_gb == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STORAGE_BACKEND", "s3"),
        ("SEARCH_BACKEND", "mongo"),
        ("LLM_PROVIDER", "openai"),
        ("SLIDE_CACHE_MAX_GB", "0"),
        ("SLIDE_CACHE_MAX_GB", "-1"),
    ],
)
def test_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


def test_secrets_are_masked() -> None:
    settings = Settings(
        anthropic_api_key=SecretStr("test-anthropic-key"),
        hf_token=SecretStr("test-hf-token"),
        databricks_token=SecretStr("test-databricks-token"),
    )
    rendered = repr(settings)
    dumped = json.dumps(settings.model_dump(mode="json"))
    for secret in ("test-anthropic-key", "test-hf-token", "test-databricks-token"):
        assert secret not in rendered
        assert secret not in dumped
    assert settings.model_dump(mode="json")["anthropic_api_key"] == "**********"


def test_env_example_lists_every_setting_without_values() -> None:
    text = (repo_root() / ".env.example").read_text()
    for name in Settings.model_fields:
        assert f"{name.upper()}=" in text
    secret_names = ("ANTHROPIC_API_KEY", "HF_TOKEN", "DATABRICKS_TOKEN", "DATABRICKS_HOST")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        key, _, value = stripped.partition("=")
        assert value == ""
        if key in secret_names:
            assert value == ""
