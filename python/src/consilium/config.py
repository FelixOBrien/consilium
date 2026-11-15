from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_serializer, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql://localhost:5432/consilium"  # pragma: allowlist secret
DEFAULT_SLIDE_CACHE_MAX_GB = 8.0
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_MLFLOW_EXPERIMENT = "/Shared/consilium-consult"  # pragma: allowlist secret


class StorageBackend(StrEnum):
    LOCAL = "local"
    UC_VOLUME = "uc_volume"


class SearchBackend(StrEnum):
    PGVECTOR = "pgvector"
    LAKEBASE = "lakebase"


class LlmProvider(StrEnum):
    ANTHROPIC = "anthropic"
    DATABRICKS = "databricks"


@lru_cache(maxsize=1)
def python_root() -> Path:
    """Directory that contains this project's `pyproject.toml`."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        package = parent / "src" / "consilium"  # pragma: allowlist secret
        if (parent / "pyproject.toml").is_file() and package.is_dir():
            return parent
    return Path.cwd()


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Checkout root when this package sits in `python/`, otherwise the Python root."""
    root = python_root()
    parent = root.parent
    if (parent / "docs" / "architecture.md").is_file():
        return parent
    return root


def default_storage_root() -> Path:
    return repo_root() / "data"


def default_slide_cache_dir() -> Path:
    return default_storage_root() / "cache" / "slides"


def _env_files() -> tuple[str, ...]:
    candidates = (repo_root() / ".env", python_root() / ".env")
    return tuple(str(path) for path in candidates if path.is_file())


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


class Settings(BaseSettings):
    """Environment configuration. Secrets stay in the environment, never in code."""

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str = DEFAULT_DATABASE_URL
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_root: Path = Field(default_factory=default_storage_root)
    slide_cache_dir: Path = Field(default_factory=default_slide_cache_dir)
    slide_cache_max_gb: float = Field(default=DEFAULT_SLIDE_CACHE_MAX_GB, gt=0)
    search_backend: SearchBackend = SearchBackend.PGVECTOR
    llm_provider: LlmProvider = LlmProvider.ANTHROPIC
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    hf_token: SecretStr | None = Field(default=None, repr=False)
    databricks_host: str | None = None
    databricks_token: SecretStr | None = Field(default=None, repr=False)
    mlflow_tracing_enabled: bool = False
    mlflow_experiment_name: str = DEFAULT_MLFLOW_EXPERIMENT
    mlflow_tracking_uri: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def blank_database_url(cls, value: object) -> object:
        if _blank(value):
            return DEFAULT_DATABASE_URL
        return value

    @field_validator("storage_backend", mode="before")
    @classmethod
    def blank_storage_backend(cls, value: object) -> object:
        if _blank(value):
            return StorageBackend.LOCAL
        return value

    @field_validator("storage_root", mode="before")
    @classmethod
    def blank_storage_root(cls, value: object) -> object:
        if _blank(value):
            return default_storage_root()
        return value

    @field_validator("slide_cache_dir", mode="before")
    @classmethod
    def blank_slide_cache_dir(cls, value: object) -> object:
        if _blank(value):
            return default_slide_cache_dir()
        return value

    @field_validator("slide_cache_max_gb", mode="before")
    @classmethod
    def blank_slide_cache_max_gb(cls, value: object) -> object:
        if _blank(value):
            return DEFAULT_SLIDE_CACHE_MAX_GB
        return value

    @field_validator("search_backend", mode="before")
    @classmethod
    def blank_search_backend(cls, value: object) -> object:
        if _blank(value):
            return SearchBackend.PGVECTOR
        return value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def blank_llm_provider(cls, value: object) -> object:
        if _blank(value):
            return LlmProvider.ANTHROPIC
        return value

    @field_validator("anthropic_model", mode="before")
    @classmethod
    def blank_anthropic_model(cls, value: object) -> object:
        if _blank(value):
            return DEFAULT_ANTHROPIC_MODEL
        return value

    @field_validator("mlflow_tracing_enabled", mode="before")
    @classmethod
    def blank_mlflow_tracing_enabled(cls, value: object) -> object:
        if _blank(value):
            return False
        return value

    @field_validator("mlflow_experiment_name", mode="before")
    @classmethod
    def blank_mlflow_experiment_name(cls, value: object) -> object:
        if _blank(value):
            return DEFAULT_MLFLOW_EXPERIMENT
        return value

    @field_validator(
        "anthropic_api_key",
        "hf_token",
        "databricks_host",
        "databricks_token",
        "mlflow_tracking_uri",
        mode="before",
    )
    @classmethod
    def blank_optional(cls, value: object) -> object:
        if _blank(value):
            return None
        return value

    @field_serializer(
        "anthropic_api_key",
        "hf_token",
        "databricks_token",
        when_used="always",
    )
    def serialize_secret(self, value: SecretStr | None) -> str | None:
        if value is None:
            return None
        return "**********"


def get_settings() -> Settings:
    return Settings()
