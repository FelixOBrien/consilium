from __future__ import annotations

import tomllib

from consilium.config import python_root  # pragma: allowlist secret


def _project() -> dict[str, object]:
    return tomllib.loads((python_root() / "pyproject.toml").read_text())


def test_project_is_consilium_for_py311() -> None:  # pragma: allowlist secret
    project = _project()["project"]
    assert isinstance(project, dict)
    assert project["name"] == "consilium"  # pragma: allowlist secret
    assert project["requires-python"] == ">=3.11"
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["consilium"] == "consilium.cli:main"  # pragma: allowlist secret


def test_default_install_is_the_api_and_gpu_deps_are_grouped() -> None:
    data = _project()
    project = data["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    joined = " ".join(dependencies)
    for needle in (
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic-settings",
        "psycopg",
        "pgvector",
        "anthropic",
    ):
        assert needle in joined
    for heavy in ("torch", "timm", "transformers", "openslide", "trident"):
        assert heavy not in joined

    groups = data["dependency-groups"]
    assert isinstance(groups, dict)
    dev = " ".join(groups["dev"])
    assert "ruff" in dev
    assert "pytest" in dev
    pipeline = " ".join(groups["pipeline"]).lower()
    assert "torch" in pipeline
    assert "timm" in pipeline
    assert "transformers" in pipeline
    # PyPI "trident" is an unrelated package. Do not lock it under this name.
    assert "trident" not in pipeline
    tiles = " ".join(groups["tiles"])
    assert "openslide-python" in tiles
    assert "openslide-bin" in tiles

    tool = data["tool"]
    assert isinstance(tool, dict)
    uv = tool["uv"]
    ruff = tool["ruff"]
    assert isinstance(uv, dict)
    assert isinstance(ruff, dict)
    assert uv["default-groups"] == ["dev"]
    assert ruff["target-version"] == "py311"


def test_scaffold_directories_exist() -> None:
    root = python_root()
    assert (root / "src" / "consilium" / "api").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "db").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "search").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "embed").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "tiles").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "agent").is_dir()  # pragma: allowlist secret
    assert (root / "src" / "consilium" / "pipeline").is_dir()  # pragma: allowlist secret
    assert (root / "sql" / "migrations").is_dir()
    assert (root / "databricks").is_dir()
    assert not (root / "main.py").exists()
    assert not (root / "metadata.json").exists()
    assert not (root / "Untitled.ipynb").exists()


def test_sources_avoid_pep695_aliases() -> None:
    src = python_root() / "src"
    for path in src.rglob("*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            assert not stripped.startswith("type "), path
