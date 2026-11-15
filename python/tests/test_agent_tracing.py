"""Consult tracing: off by default, one MLflow trace per turn, fail-open.

Local traces use a file store. mlflow-tracing does not ship a working SQLite
tracking store, and the full MLflow package is not installed.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from consilium.agent.provider import ProviderEvent, ToolCall  # pragma: allowlist secret
from consilium.agent.tracing import (  # pragma: allowlist secret
    MlflowTurnTracer,
    NoopTurnTracer,
    build_tracer,
    sanitize_tool_arguments,
)
from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import DEFAULT_MLFLOW_EXPERIMENT, Settings  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    MockTextEncoder,
    TextEncoders,
    build_text_encoders,
)
from consilium.seed_data import CASES, report_sections  # pragma: allowlist secret

OPEN = "breast-FX-B042C"
SIGNED_PRIOR = "breast-FX-B042A"
SENTINEL_REPORT = "SENTINEL report body qx7 invasive carcinoma"
SENTINEL_HISTORY = "SENTINEL clinical history qx7 61-year-old woman"
SENTINEL_SEX = "SENTINEL sex female qx7"
SENTINEL_AGE = "SENTINEL age ninety-nine qx7"
SENTINEL_TOKEN = "dapi-SENTINEL-TOKEN-qx7"
_EXPERIMENT = DEFAULT_MLFLOW_EXPERIMENT


class ScriptedProvider:
    model_name = "mock"

    def __init__(self, rounds: list[tuple[str, list[ToolCall]]]) -> None:
        self._rounds = list(rounds)

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[Any]:
        del system, messages, tools
        text, calls = self._rounds.pop(0)
        if text:
            yield ProviderEvent(kind="text", text=text)
        yield ProviderEvent(
            kind="end",
            tool_calls=list(calls),
            content=[],
            input_tokens=11,
            output_tokens=7,
            stop_reason="tool_use" if calls else "end_turn",
        )


@pytest.fixture
def seeded(empty_database: str, tmp_path: Path) -> str:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    return empty_database


@pytest.fixture
def encoders() -> TextEncoders:
    return build_text_encoders(backend=MockTextEncoder())


@pytest.fixture(autouse=True)
def _reset_tracing_cache() -> Iterator[None]:
    from consilium.agent import tracing  # pragma: allowlist secret

    tracing._ready = None
    yield
    tracing._ready = None


def _poison() -> dict[str, Any]:
    return {
        "text": SENTINEL_REPORT,
        "clinical_history": SENTINEL_HISTORY,
        "patient_sex": SENTINEL_SEX,
        "patient_age": SENTINEL_AGE,
        "api_key": SENTINEL_TOKEN,
        "body": SENTINEL_REPORT,
        "filters": {
            "specialty": "breast",
            "limit": 4,
            "patient_sex": SENTINEL_SEX,
        },
    }


def _rounds() -> list[tuple[str, list[ToolCall]]]:
    answer = f"See [case:{SIGNED_PRIOR}]. {SENTINEL_REPORT}"
    return [
        ("", [ToolCall(id="c1", name="get_case_context", arguments=_poison())]),
        (
            "",
            [
                ToolCall(
                    id="c2",
                    name="get_report",
                    arguments={"case_id": SIGNED_PRIOR, **_poison()},
                )
            ],
        ),
        (answer, []),
    ]


def _client(seeded: str, encoders: TextEncoders, provider: object, **kwargs: Any) -> TestClient:
    settings = Settings(database_url=seeded, anthropic_api_key=None, **kwargs)
    app = create_app(settings)
    app.state.text_encoders = encoders
    app.state.consult_provider = provider
    return TestClient(app)


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: str | None = None
    data: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            current = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data.append(line.removeprefix("data:").strip())
        elif line == "" and current is not None:
            events.append(json.loads("".join(data)))
            current = None
            data = []
    return events


def _ask(
    client: TestClient,
    content: str = "Who has reported cases like this?",
) -> tuple[str, list[dict[str, Any]]]:
    created = client.post(f"/api/cases/{OPEN}/consult/threads", json={"new": True})
    assert created.status_code == 200, created.text
    thread_id = str(created.json()["id"])
    response = client.post(
        f"/api/consult/threads/{thread_id}/messages",
        json={"content": content},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return thread_id, _parse_sse(response.text)


def _visible(events: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    for event in events:
        kind = event["type"]
        if kind == "text":
            out.append(("text", event["content"]))
        elif kind == "step":
            out.append(("step", event["tool"], event["summary"]))
        elif kind == "citations":
            out.append(("citations", tuple(item["case_id"] for item in event["citations"])))
        elif kind == "ranking":
            out.append(("ranking", event["ranking"]))
        elif kind == "done":
            message = event["message"]
            out.append(("done", message["content"], message["status"]))
        elif kind == "error":
            out.append(("error", event["message"]))
        else:
            out.append((kind,))
    return out


def _forbidden() -> list[str]:
    by_id = {case.id: case for case in CASES}
    phrases = [
        SENTINEL_REPORT,
        SENTINEL_HISTORY,
        SENTINEL_SEX,
        SENTINEL_AGE,
        SENTINEL_TOKEN,
        report_sections(by_id[OPEN])["clinical_history"],
        report_sections(by_id[SIGNED_PRIOR])["clinical_history"],
        report_sections(by_id[SIGNED_PRIOR])["conclusion"],
        report_sections(by_id[SIGNED_PRIOR])["microscopic_description"],
        "Invasive carcinoma of no special type",
        "61-year-old woman",
        "60-year-old woman",
    ]
    return phrases


def _load_traces(uri: str) -> list[Any]:
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    import mlflow

    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(_EXPERIMENT)
    mlflow.flush_trace_async_logging()
    found = mlflow.search_traces(
        return_type="list",
        include_spans=True,
        max_results=20,
    )
    return list(found)


def _trace_blob(traces: list[Any]) -> str:
    payload = []
    for trace in traces:
        payload.append(
            {
                "info": trace.info.to_dict(),
                "spans": [span.to_dict() for span in trace.data.spans],
            }
        )
    return json.dumps(payload, default=str)


def _span_type(span: Any) -> str:
    kind = span.span_type
    value = getattr(kind, "value", kind)
    return str(value)


def _attr(span: Any, key: str) -> Any:
    attributes = span.attributes or {}
    if key in attributes:
        return attributes[key]
    outputs = span.outputs or {}
    if isinstance(outputs, dict) and key in outputs:
        return outputs[key]
    inputs = span.inputs or {}
    if isinstance(inputs, dict) and key in inputs:
        return inputs[key]
    return None


def test_tracing_disabled_makes_no_mlflow_calls(
    seeded: str,
    encoders: TextEncoders,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def forbid() -> None:
        calls.append("mlflow")
        raise AssertionError("mlflow imported while tracing is disabled")

    monkeypatch.setattr(
        "consilium.agent.tracing._import_mlflow",  # pragma: allowlist secret
        forbid,
    )
    settings = Settings(mlflow_tracing_enabled=False, mlflow_tracking_uri="")
    assert isinstance(build_tracer(settings), NoopTurnTracer)
    assert settings.mlflow_experiment_name == _EXPERIMENT
    assert calls == []

    with _client(
        seeded,
        encoders,
        ScriptedProvider(_rounds()),
        mlflow_tracing_enabled=False,
    ) as off:
        _thread_id, disabled = _ask(off)
    with _client(seeded, encoders, ScriptedProvider(_rounds())) as bare:
        _thread_id, default = _ask(bare)

    assert calls == []
    visible = _visible(disabled)
    assert visible == _visible(default)
    assert ("text", f"See [case:{SIGNED_PRIOR}]. {SENTINEL_REPORT}") in visible
    assert ("citations", (SIGNED_PRIOR,)) in visible
    assert visible[-1][0] == "done"
    assert [item for item in visible if item[0] == "step"] == [
        ("step", "get_case_context", "Running get_case_context."),
        ("step", "get_case_context", "Loaded the open case. It is not precedent."),
        ("step", "get_report", "Running get_report."),
        ("step", "get_report", "Loaded one signed-out report."),
    ]


def test_enabled_file_store_traces_one_turn_without_clinical_text(
    seeded: str,
    encoders: TextEncoders,
    tmp_path: Path,
) -> None:
    uri = str(tmp_path / "mlruns")
    settings = dict(
        mlflow_tracing_enabled=True,
        mlflow_tracking_uri=uri,
        mlflow_experiment_name=_EXPERIMENT,
        databricks_host="https://adb.example.cloud.databricks.com/",
        databricks_token=SecretStr(SENTINEL_TOKEN),
    )
    with _client(seeded, encoders, ScriptedProvider(_rounds()), **settings) as client:
        thread_id, enabled = _ask(client)
    with _client(
        seeded,
        encoders,
        ScriptedProvider(_rounds()),
        mlflow_tracing_enabled=False,
    ) as off:
        _ignored, disabled = _ask(off)
    assert _visible(enabled) == _visible(disabled)

    traces = _load_traces(uri)
    assert len(traces) == 1
    spans = list(traces[0].data.spans)
    roots = [span for span in spans if span.parent_id is None]
    models = [span for span in spans if _span_type(span) == "CHAT_MODEL"]
    tools = [span for span in spans if _span_type(span) == "TOOL"]
    models.sort(key=lambda span: int(_attr(span, "step_index")))
    assert len(roots) == 1
    assert len(models) == 3
    assert len(tools) == 2
    assert {span.name for span in tools} == {"get_case_context", "get_report"}

    root = roots[0]
    assert root.name == "consult_turn"
    assert _attr(root, "case_id") == OPEN
    assert _attr(root, "model") == "mock"
    assert _attr(root, "status") == "complete"
    assert int(_attr(root, "input_tokens")) == 33
    assert int(_attr(root, "output_tokens")) == 21
    assert int(_attr(root, "tool_call_count")) == 2
    assert int(_attr(root, "citation_count")) == 1
    assert _attr(root, "thread_id") == thread_id

    for span in spans:
        assert span.end_time_ns is not None and span.start_time_ns is not None
        assert span.end_time_ns >= span.start_time_ns
        assert int(_attr(span, "duration_ms")) >= 0

    assert [_attr(span, "step_index") for span in models] == [0, 1, 2]
    assert [_attr(span, "stop_reason") for span in models] == ["tool_use", "tool_use", "end_turn"]
    assert sum(int(_attr(span, "input_tokens")) for span in models) == 33
    assert sum(int(_attr(span, "output_tokens")) for span in models) == 21

    report_span = next(span for span in tools if span.name == "get_report")
    assert _attr(report_span, "case_id") == SIGNED_PRIOR
    assert _attr(report_span, "specialty") == "breast"
    assert int(_attr(report_span, "limit")) == 4
    assert int(_attr(report_span, "query_chars")) == len(SENTINEL_REPORT)
    assert int(_attr(report_span, "result_count")) == 1
    assert int(_attr(report_span, "result_bytes")) > 0
    assert _attr(report_span, "ok") is True

    blob = _trace_blob(traces)
    for phrase in _forbidden():
        assert phrase not in blob


def test_tracing_failure_does_not_interrupt_the_sse_stream(
    seeded: str,
    encoders: TextEncoders,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import mlflow

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(f"trace backend down {SENTINEL_TOKEN}")

    monkeypatch.setattr(mlflow, "start_span", explode)
    caplog.set_level("WARNING")
    uri = str(tmp_path / "mlruns")
    with _client(
        seeded,
        encoders,
        ScriptedProvider(_rounds()),
        mlflow_tracing_enabled=True,
        mlflow_tracking_uri=uri,
    ) as client:
        _thread_id, failed = _ask(client)
    with _client(
        seeded,
        encoders,
        ScriptedProvider(_rounds()),
        mlflow_tracing_enabled=False,
    ) as off:
        _ignored, disabled = _ask(off)

    assert _visible(failed) == _visible(disabled)
    assert SENTINEL_TOKEN not in caplog.text
    assert any("consult tracing" in record.getMessage() for record in caplog.records)


def test_sanitize_tool_arguments_keeps_ids_and_drops_clinical_text() -> None:
    safe = sanitize_tool_arguments(
        {
            "case_id": SIGNED_PRIOR,
            "text": SENTINEL_REPORT,
            "clinical_history": SENTINEL_HISTORY,
            "patient_sex": SENTINEL_SEX,
            "patient_age": 61,
            "api_key": SENTINEL_TOKEN,
            "case_ids": [SIGNED_PRIOR, SENTINEL_REPORT, SENTINEL_TOKEN],
            "filters": {"specialty": "breast", "limit": "4", "sex": "F"},
            "region": {"slide_id": "slide-9", "x": 1, "y": 2},
        }
    )
    assert safe == {
        "case_id": SIGNED_PRIOR,
        "slide_id": "slide-9",
        "query_chars": len(SENTINEL_REPORT),
        "case_id_count": 1,
        "specialty": "breast",
        "limit": 4,
    }
    dumped = json.dumps(safe)
    for phrase in (SENTINEL_REPORT, SENTINEL_HISTORY, SENTINEL_SEX, SENTINEL_TOKEN, "61"):
        assert phrase not in dumped


def test_databricks_target_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    seen: dict[str, str] = {}

    class FakeMLflow:
        def set_tracking_uri(self, uri: str) -> None:
            seen["uri"] = uri
            seen["host"] = os.environ["DATABRICKS_HOST"]
            seen["token"] = os.environ["DATABRICKS_TOKEN"]

        def set_experiment(self, name: str) -> None:
            seen["experiment"] = name

    monkeypatch.setattr(
        "consilium.agent.tracing._import_mlflow",  # pragma: allowlist secret
        lambda: FakeMLflow(),
    )
    caplog.set_level("WARNING")
    tracer = build_tracer(
        Settings(
            mlflow_tracing_enabled=True,
            databricks_host="https://adb.example.cloud.databricks.com/",
            databricks_token=SecretStr(SENTINEL_TOKEN),
        )
    )
    assert isinstance(tracer, MlflowTurnTracer)
    assert seen == {
        "uri": "databricks",
        "host": "https://adb.example.cloud.databricks.com",
        "token": SENTINEL_TOKEN,
        "experiment": _EXPERIMENT,
    }
    assert SENTINEL_TOKEN not in caplog.text

    skipped = build_tracer(Settings(mlflow_tracing_enabled=True))
    assert isinstance(skipped, NoopTurnTracer)
