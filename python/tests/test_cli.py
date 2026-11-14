from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from consilium.cli import main  # pragma: allowlist secret


def test_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "serve" in output
    assert "pipeline" in output
    assert "db" in output
    assert "not for clinical use" in output


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "serve" in output


def test_pipeline_help_does_not_claim_to_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["pipeline"]) == 0
    output = capsys.readouterr().out
    assert "does not download" in output


def test_unknown_command() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code == 2


def test_db_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["db"])
    assert exc.value.code == 2


def test_serve_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run(target: str, **kwargs: object) -> None:
        called["target"] = target
        called["kwargs"] = kwargs

    monkeypatch.setattr("consilium.cli.uvicorn.run", fake_run)  # pragma: allowlist secret
    assert main(["serve", "--host", "0.0.0.0", "--port", "9001", "--reload"]) == 0
    assert called["target"] == "consilium.api.app:app"  # pragma: allowlist secret
    kwargs = called["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9001
    assert kwargs["reload"] is True


def test_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "consilium", "--help"],  # pragma: allowlist secret
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout


def test_console_script_help() -> None:
    script = Path(sys.executable).parent / "consilium"  # pragma: allowlist secret
    result = subprocess.run(
        [script, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
