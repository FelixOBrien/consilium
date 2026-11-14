"""Consult agent: tools, citation allowlist, SQL ranking, streaming and persistence.

The model is scripted. A live Claude turn runs only when ANTHROPIC_API_KEY is
set in the environment at import, and is skipped in the default assertions
below so a missing key still proves the unavailable state.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from pydantic import SecretStr

from consilium.agent.loop import MAX_TOOL_CALLS, consult_turn  # pragma: allowlist secret
from consilium.agent.postcheck import (  # pragma: allowlist secret
    AllowedCase,
    Allowlist,
    CitationSanitizer,
)
from consilium.agent.provider import (  # pragma: allowlist secret
    PUBLIC_UNAVAILABLE,
    ProviderEvent,
    ToolCall,
)
from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.schemas.consult import ConsultMessageCreate  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    MockTextEncoder,
    TextEncoders,
    build_text_encoders,
)
from consilium.search.common import fetchall, fetchone  # pragma: allowlist secret

OPEN = "breast-FX-B042C"
SIGNED_PRIOR = "breast-FX-B042A"
SIGNED_LATER = "breast-FX-B042B"
SIGNED_THORAX = "thorax-FX-T007A"
PATIENT = "pt-0042"
INVENTED = "invented-case"
OTHER_USER = "path-adebayo"
_LIVE_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()


class ScriptedProvider:
    """Yields prepared rounds. Records every request, including the tool list."""

    model_name = "mock"

    def __init__(self, rounds: list[tuple[str, list[ToolCall]]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append({"system": system, "messages": messages, "tools": list(tools)})
        text, calls = self._rounds.pop(0)
        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
            yield ProviderEvent(kind="text", text=text)
        for call in calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
            )
        yield ProviderEvent(
            kind="end",
            tool_calls=list(calls),
            content=content,
            input_tokens=11,
            output_tokens=7,
            stop_reason="tool_use" if calls else "end_turn",
        )


class CapProvider:
    model_name = "mock"

    def __init__(self) -> None:
        self.tool_counts: list[int] = []
        self._n = 0

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        del system, messages
        self.tool_counts.append(len(tools))
        if not tools:
            text = "Answer after the tool cap."
            yield ProviderEvent(kind="text", text=text)
            yield ProviderEvent(
                kind="end",
                content=[{"type": "text", "text": text}],
                input_tokens=4,
                output_tokens=4,
                stop_reason="end_turn",
            )
            return
        self._n += 1
        call = ToolCall(id=f"cap-{self._n}", name="get_case_context", arguments={})
        yield ProviderEvent(
            kind="end",
            tool_calls=[call],
            content=[
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": {},
                }
            ],
            input_tokens=2,
            output_tokens=2,
            stop_reason="tool_use",
        )


class PauseProvider:
    model_name = "mock"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[ProviderEvent]:
        del system, messages, tools
        yield ProviderEvent(kind="text", text="Partial answer")
        self.started.set()
        await self.release.wait()
        yield ProviderEvent(kind="end", input_tokens=1, output_tokens=1, stop_reason="end_turn")


def _tool(name: str, arguments: dict[str, Any], call_id: str) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


@pytest.fixture
def seeded(empty_database: str, tmp_path: Path) -> str:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    return empty_database


@pytest.fixture
def encoders() -> TextEncoders:
    return build_text_encoders(backend=MockTextEncoder())


def _app(
    seeded: str,
    encoders: TextEncoders,
    provider: object | None,
    *,
    api_key: str | None = None,
) -> TestClient:
    settings = Settings(
        database_url=seeded,
        anthropic_api_key=None if api_key is None else SecretStr(api_key),
    )
    app = create_app(settings)
    app.state.text_encoders = encoders
    if provider is not None:
        app.state.consult_provider = provider
    return TestClient(app)


@pytest.fixture
def client(seeded: str, encoders: TextEncoders) -> Iterator[TestClient]:
    with _app(seeded, encoders, provider=None) as test_client:
        yield test_client


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


def _thread(client: TestClient, case_id: str, *, new: bool = True) -> dict[str, Any]:
    response = client.post(f"/api/cases/{case_id}/consult/threads", json={"new": new})
    assert response.status_code == 200, response.text
    return response.json()


def _ask(client: TestClient, thread_id: str, content: str) -> list[dict[str, Any]]:
    response = client.post(
        f"/api/consult/threads/{thread_id}/messages",
        json={"content": content},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(response.text)


def _tool_blob(provider: ScriptedProvider) -> str:
    return json.dumps(provider.calls)


def test_citation_sanitizer_unlinks_unknown_ids() -> None:
    allowed = Allowlist()
    allowed.add(AllowedCase(case_id="breast-FX-B042A", patient_id="pt-0042", same_patient=True))
    sanitizer = CitationSanitizer(allowed)
    streamed = sanitizer.push("See [case:breast-FX-B042A] and [case:inven")
    streamed += sanitizer.push("ted-case] plus [case:breast-FX-B042C].")
    streamed += sanitizer.finish()
    assert "[case:breast-FX-B042A]" in streamed
    assert "[case:invented-case]" not in streamed
    assert "[case:breast-FX-B042C]" not in streamed
    assert "invented-case" in streamed


def test_invented_and_open_cases_never_become_precedent(
    seeded: str,
    encoders: TextEncoders,
) -> None:
    answer = (
        "Prior specimen [case:breast-FX-B042A]. "
        "The open case is [case:breast-FX-B042B] and [case:breast-FX-B042C]. "
        "Invented [case:invented-case]. "
        "Dr A. Okafor reported 99 cases."
    )
    provider = ScriptedProvider(
        [
            ("", [_tool("get_case_context", {}, "c1")]),
            ("", [_tool("get_patient_history", {}, "c2")]),
            ("", [_tool("get_report", {"case_id": SIGNED_LATER}, "c3")]),
            ("", [_tool("get_report", {"case_id": OPEN}, "c4")]),
            ("", [_tool("get_report", {"case_id": SIGNED_PRIOR}, "c5")]),
            (
                "",
                [
                    _tool(
                        "search_reports",
                        {"text": "invasive carcinoma"},
                        "c6",
                    )
                ],
            ),
            (
                "",
                [
                    _tool(
                        "rank_pathologists",
                        {
                            "case_ids": [
                                SIGNED_PRIOR,
                                SIGNED_LATER,
                                OPEN,
                                INVENTED,
                                SIGNED_THORAX,
                            ]
                        },
                        "c7",
                    )
                ],
            ),
            (answer, []),
        ]
    )
    with _app(seeded, encoders, provider) as client:
        created = _thread(client, SIGNED_LATER)
        events = _ask(client, created["id"], "Who should I consult on this case?")
        reloaded = client.get(f"/api/consult/threads/{created['id']}")

    names = [event["type"] for event in events]
    assert names[0] == "step"
    assert "text" in names
    assert names[-3:] == ["citations", "ranking", "done"]
    assert '"input":' not in json.dumps(events)
    assert "input_tokens" not in json.dumps(events)
    assert "thumbnail_url" not in _tool_blob(provider)

    citations = next(event for event in events if event["type"] == "citations")["citations"]
    cited = [item["case_id"] for item in citations]
    assert cited == [SIGNED_PRIOR]
    assert citations[0]["case"]["patient"]["id"] == PATIENT
    assert citations[0]["case"]["status"] == "signed_out"
    done = events[-1]["message"]
    assert "[case:invented-case]" not in done["content"]
    assert f"[case:{SIGNED_LATER}]" not in done["content"]
    assert f"[case:{OPEN}]" not in done["content"]
    assert f"[case:{SIGNED_PRIOR}]" in done["content"]

    blob = _tool_blob(provider)
    history = _result_payload(provider, "get_patient_history")
    prior = next(item for item in history["cases"] if item["case_id"] == SIGNED_PRIOR)
    assert prior["same_patient"] is True
    assert prior["citable"] is True
    open_case = next(item for item in history["cases"] if item["case_id"] == OPEN)
    assert open_case["citable"] is False
    assert open_case["status"] == "open"
    assert "icd10" not in open_case
    assert "conclusion_line" not in open_case
    assert "report_excerpt" not in open_case
    assert SIGNED_LATER not in {item["case_id"] for item in history["cases"]}
    context = _result_payload(provider, "get_case_context")
    assert context["citable"] is False
    assert context["precedent"] is False
    own = _result_payload(provider, "get_report", {"case_id": SIGNED_LATER})
    assert own["error"] == "not_precedent"
    held = _result_payload(provider, "get_report", {"case_id": OPEN})
    assert held["error"] == "not_precedent"
    with connect(seeded) as conn:
        secret = fetchone(
            conn,
            "SELECT gross_description FROM report WHERE case_id = %s",
            (OPEN,),
        )
    assert secret is not None
    canary = str(secret["gross_description"])
    assert canary not in blob
    for passage in _passages(provider):
        assert len(passage) <= 400

    ranking = next(event for event in events if event["type"] == "ranking")["ranking"]
    assert [item["pathologist_id"] for item in ranking] == ["path-adebayo", "path-okafor"]
    for item in ranking:
        assert item["case_count"] == len(item["case_ids"])
    by_id = {item["pathologist_id"]: item for item in ranking}
    assert by_id["path-okafor"]["case_ids"] == [SIGNED_PRIOR]
    assert by_id["path-adebayo"]["case_ids"] == [SIGNED_THORAX]
    assert by_id["path-okafor"]["case_count"] == 1
    rank_payload = _result_payload(provider, "rank_pathologists")
    okafor = next(
        item for item in rank_payload["ranking"] if item["pathologist_id"] == "path-okafor"
    )
    adebayo = next(
        item for item in rank_payload["ranking"] if item["pathologist_id"] == "path-adebayo"
    )
    assert okafor["is_synthetic"] is True
    assert okafor["reported_same_patient"] is True
    assert adebayo["reported_same_patient"] is False
    assert "99" not in json.dumps(ranking)

    assert reloaded.status_code == 200
    stored = reloaded.json()["messages"]
    assert [item["role"] for item in stored] == ["user", "assistant"]
    assert stored[1]["status"] == "complete"
    assert stored[1]["content"] == done["content"]
    assert stored[1]["citations"] == citations
    assert stored[1]["ranking"] == ranking
    assert "input" not in stored[1]["tool_trace"][0]
    assert "input_tokens" not in json.dumps(stored)
    with connect(seeded) as conn:
        row = fetchone(
            conn,
            """
            SELECT input_tokens, output_tokens, tool_trace, status
            FROM consult_message
            WHERE thread_id = %s AND role = 'assistant'
            """,
            (created["id"],),
        )
    assert row is not None
    assert row["status"] == "complete"
    assert row["input_tokens"] == 11 * 8
    assert row["output_tokens"] == 7 * 8
    assert row["tool_trace"][0]["input"] == {}
    assert len(row["tool_trace"]) == 7


def test_tool_call_cap_forces_a_final_answer(seeded: str, encoders: TextEncoders) -> None:
    provider = CapProvider()
    with _app(seeded, encoders, provider) as client:
        created = _thread(client, OPEN)
        events = _ask(client, created["id"], "Keep calling tools.")
    assert provider.tool_counts[-1] == 0
    assert all(count > 0 for count in provider.tool_counts[:-1])
    assert len(provider.tool_counts) == MAX_TOOL_CALLS + 1
    finished = [
        event
        for event in events
        if event["type"] == "step" and not str(event["summary"]).startswith("Running ")
    ]
    assert len(finished) == MAX_TOOL_CALLS
    assert events[-1]["type"] == "done"
    assert events[-1]["message"]["content"] == "Answer after the tool cap."
    assert len(events[-1]["message"]["tool_trace"]) == MAX_TOOL_CALLS


def test_thread_ownership_and_missing_case(client: TestClient) -> None:
    missing = client.post("/api/cases/no-such-case/consult/threads", json={})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    first = _thread(client, OPEN, new=False)
    again = _thread(client, OPEN, new=False)
    assert again["id"] == first["id"]
    fresh = _thread(client, OPEN, new=True)
    assert fresh["id"] != first["id"]
    assert fresh["messages"] == []

    hidden = client.get(
        f"/api/consult/threads/{fresh['id']}",
        headers={"X-User-Id": OTHER_USER},
    )
    assert hidden.status_code == 403
    assert hidden.json()["error"]["code"] == "forbidden"
    denied = client.post(
        f"/api/consult/threads/{fresh['id']}/messages",
        headers={"X-User-Id": OTHER_USER},
        json={"content": "Who should I consult?"},
    )
    assert denied.status_code == 403
    unknown = client.get("/api/consult/threads/00000000-0000-0000-0000-000000000099")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"


def test_missing_api_key_streams_agent_unavailable(seeded: str, encoders: TextEncoders) -> None:
    with _app(seeded, encoders, provider=None, api_key=None) as client:
        created = _thread(client, OPEN)
        response = client.post(
            f"/api/consult/threads/{created['id']}/messages",
            json={"content": "Who should I consult?"},
        )
        assert response.status_code == 200
        events = _parse_sse(response.text)
        assert [event["type"] for event in events] == ["error"]
        assert events[0]["message"] == PUBLIC_UNAVAILABLE
        reloaded = client.get(f"/api/consult/threads/{created['id']}")
        assistant = next(
            item for item in reloaded.json()["messages"] if item["role"] == "assistant"
        )
    assert assistant["role"] == "assistant"
    assert assistant["status"] == "error"
    assert assistant["content"] == PUBLIC_UNAVAILABLE


def test_disconnect_keeps_the_partial_answer(
    seeded: str,
    encoders: TextEncoders,
) -> None:
    with _app(seeded, encoders, provider=None) as client:
        created = _thread(client, OPEN)
    provider = PauseProvider()

    @contextmanager
    def factory() -> Iterator[Connection]:
        conn = connect(seeded)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    async def consume() -> None:
        async for _event in consult_turn(
            db_factory=factory,
            provider=provider,
            encoders=encoders,
            thread_id=UUID(created["id"]),
            actor_id="path-okafor",
            body=ConsultMessageCreate(content="Stop midway."),
        ):
            pass

    async def scenario() -> None:
        task = asyncio.create_task(consume())
        await provider.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    with connect(seeded) as conn:
        rows = fetchall(
            conn,
            """
            SELECT role, content, status
            FROM consult_message
            WHERE thread_id = %s
            ORDER BY created_at, id
            """,
            (created["id"],),
        )
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["status"] == "complete"
    assert rows[1]["content"] == "Partial answer"


@pytest.mark.skipif(not _LIVE_KEY, reason="ANTHROPIC_API_KEY is not set")
def test_live_anthropic_three_questions(seeded: str, encoders: TextEncoders) -> None:
    questions = [
        (
            "Summarise this patient's previous cases",
            OPEN,
        ),
        (
            "Who should I consult on this case?",
            OPEN,
        ),
        (
            "What is the diagnosis?",
            OPEN,
        ),
    ]
    transcripts: list[dict[str, Any]] = []
    with _app(seeded, encoders, provider=None, api_key=_LIVE_KEY) as client:
        for content, case_id in questions:
            created = _thread(client, case_id)
            events = _ask(client, created["id"], content)
            done = next(event for event in events if event["type"] == "done")
            message = done["message"]
            transcripts.append(
                {
                    "question": content,
                    "tools": [step["tool"] for step in message["tool_trace"] or []],
                    "summaries": [step["summary"] for step in message["tool_trace"] or []],
                    "citations": [item["case_id"] for item in message["citations"] or []],
                    "ranking": message["ranking"],
                    "answer": message["content"],
                }
            )
    summary, consult, diagnosis = transcripts
    assert "get_patient_history" in summary["tools"]
    assert SIGNED_PRIOR in summary["citations"] or SIGNED_LATER in summary["citations"]
    assert "search_similar_cases_by_morphology" in consult["tools"]
    assert "search_reports" in consult["tools"]
    assert "rank_pathologists" in consult["tools"]
    assert consult["ranking"]
    for item in consult["ranking"]:
        assert item["case_count"] == len(item["case_ids"])
    assert consult["citations"]
    lowered = diagnosis["answer"].lower()
    assert any(phrase in lowered for phrase in ("cannot", "can't", "unable", "do not diagnose"))
    assert OPEN not in diagnosis["citations"]
    path = Path("/tmp/consult-live-transcripts.json")
    path.write_text(json.dumps(transcripts, indent=2))


def _result_payload(
    provider: ScriptedProvider,
    tool: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for call in reversed(provider.calls):
        for block in _blocks(call["messages"]):
            if block.get("type") != "tool_result":
                continue
            found = _matching_call(call["messages"], str(block.get("tool_use_id")), tool, arguments)
            if found is None:
                continue
            content = block["content"]
            return json.loads(content) if isinstance(content, str) else content
    raise AssertionError(f"no result for {tool}")


def _matching_call(
    messages: list[dict[str, Any]],
    tool_use_id: str,
    tool: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for block in _blocks(messages):
        if block.get("type") == "tool_use" and block.get("id") == tool_use_id:
            if block.get("name") != tool:
                return None
            if arguments is not None and block.get("input") != arguments:
                return None
            return block
    return None


def _blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            blocks.extend(item for item in content if isinstance(item, dict))
    return blocks


def _passages(provider: ScriptedProvider) -> list[str]:
    texts: list[str] = []
    for call in provider.calls:
        for block in _blocks(call["messages"]):
            if block.get("type") != "tool_result" or not isinstance(block.get("content"), str):
                continue
            payload = json.loads(block["content"])
            for hit in payload.get("hits") or []:
                passage = hit.get("passage")
                if passage and passage.get("text"):
                    texts.append(passage["text"])
    return texts
