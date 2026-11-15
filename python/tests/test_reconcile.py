"""Reconcile compares parquet, optional gold, and Postgres."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from consilium.pipeline import __main__ as pipeline_main  # pragma: allowlist secret
from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret
from consilium.pipeline.reconcile import (  # pragma: allowlist secret
    ReconcileResult,
    fetch_gold_counts,
    reconcile,
)


def test_match_and_mismatch(tmp_path: Path) -> None:
    export = _export(tmp_path / "full", 4)
    counts = dict.fromkeys(PIPELINE_TABLES, 4)
    matched = reconcile(
        export,
        gold_counts=counts,
        postgres_counts=counts,
        connect_postgres=False,
    )
    assert matched.failed == 0
    assert "mismatch none" in matched.summary()
    assert "n/a" not in matched.summary()

    drifted = dict(counts)
    drifted["patch"] = 3
    result = reconcile(
        export,
        gold_counts=counts,
        postgres_counts=drifted,
        connect_postgres=False,
    )
    assert result.mismatched == ("patch",)
    assert "mismatch patch" in result.summary()


def test_subset_expects_postgres_to_match_the_subset(tmp_path: Path) -> None:
    export = _export(tmp_path / "full", 4)
    subset = _export(tmp_path / "subset", 2)
    full = dict.fromkeys(PIPELINE_TABLES, 4)
    small = dict.fromkeys(PIPELINE_TABLES, 2)
    ok = reconcile(
        export,
        subset_dir=subset,
        gold_counts=full,
        postgres_counts=small,
        connect_postgres=False,
    )
    assert ok.failed == 0
    assert "subset" in ok.summary().splitlines()[0]

    wrong = reconcile(
        export,
        subset_dir=subset,
        gold_counts=full,
        postgres_counts=full,
        connect_postgres=False,
    )
    assert wrong.failed == len(PIPELINE_TABLES)

    gold_short = dict(full)
    gold_short["slide"] = 1
    gold = reconcile(
        export,
        subset_dir=subset,
        gold_counts=gold_short,
        postgres_counts=small,
        connect_postgres=False,
    )
    assert gold.mismatched == ("slide",)


def test_gold_and_postgres_disagree_once(tmp_path: Path) -> None:
    export = _export(tmp_path / "full", 2)
    counts = dict.fromkeys(PIPELINE_TABLES, 0)
    result = reconcile(export, gold_counts=counts, postgres_counts=counts, connect_postgres=False)
    assert result.mismatched == tuple(PIPELINE_TABLES)
    assert result.summary().count("mismatch path_case") == 1


def test_gold_is_optional(tmp_path: Path) -> None:
    export = _export(tmp_path / "full", 1)
    counts = dict.fromkeys(PIPELINE_TABLES, 1)
    result = reconcile(export, postgres_counts=counts, connect_postgres=False)
    assert result.failed == 0
    assert "n/a" in result.summary()


def test_fetch_gold_counts_reads_the_statement_api() -> None:
    seen: list[str] = []

    class _Execution:
        def execute_statement(
            self,
            *,
            statement: str,
            warehouse_id: str,
            wait_timeout: str,
        ) -> object:
            assert warehouse_id == "warehouse"
            assert wait_timeout == "50s"
            seen.append(statement)
            status = SimpleNamespace(state="SUCCEEDED")
            result = SimpleNamespace(data_array=[["7"]])
            return SimpleNamespace(status=status, result=result)

    counts = fetch_gold_counts(
        SimpleNamespace(statement_execution=_Execution()),
        warehouse_id="warehouse",
        catalog="main",
        schema="consilium",  # pragma: allowlist secret
    )
    assert counts["patch"] == 7
    gold_pathologist = (
        "select count(*) from main.consilium.gold_pathologist"  # pragma: allowlist secret
    )
    assert seen[0] == gold_pathologist
    with pytest.raises(ValueError, match="catalog"):
        fetch_gold_counts(
            SimpleNamespace(statement_execution=_Execution()),
            warehouse_id="warehouse",
            catalog="main;drop",
            schema="consilium",  # pragma: allowlist secret
        )


def test_failed_gold_query_raises() -> None:
    class _Execution:
        def execute_statement(self, **_kwargs: object) -> object:
            return SimpleNamespace(status=SimpleNamespace(state="FAILED"), result=None)

    with pytest.raises(RuntimeError, match="failed"):
        fetch_gold_counts(
            SimpleNamespace(statement_execution=_Execution()),
            warehouse_id="warehouse",
            catalog="main",
            schema="consilium",  # pragma: allowlist secret
        )


def test_cli_returns_nonzero_on_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    counts = {
        table: {"parquet": 1, "gold": None, "postgres": 0, "subset": None}
        for table in PIPELINE_TABLES
    }
    result = ReconcileResult(counts=counts, mismatched=("patch",), subset=False)
    monkeypatch.setattr(pipeline_main, "reconcile", lambda *_args, **_kwargs: result)
    code = pipeline_main.main(["reconcile", "--from", str(tmp_path)])
    assert code == 1
    assert "mismatch patch" in capsys.readouterr().out


def _export(directory: Path, rows: int) -> Path:
    directory.mkdir(parents=True)
    for table in PIPELINE_TABLES:
        column = pa.array([str(index) for index in range(rows)])
        pq.write_table(pa.table({"id": column}), directory / PARQUET_FILES[table])
    return directory
