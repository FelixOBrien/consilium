"""Consult-turn tracing.

Off unless ``MLFLOW_TRACING_ENABLED`` is set. The default path imports nothing
from MLflow and does not call Databricks. When tracing is on, each turn is one
trace: a root span plus a child span per model call and per tool call.

``mlflow.anthropic.autolog`` is intentionally not used. It records prompts and
completions, and those include report text. Spans here carry only ids, counts,
durations and token totals.

A tracing failure is logged as a warning with the exception type and is never
raised into the consult stream.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

from consilium.config import Settings  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_DEFAULT_EXPERIMENT = "/Shared/consilium-consult"  # pragma: allowlist secret
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SECRET_MARKERS = ("token", "secret", "dapi", "bearer", "password", "api_key")
_ID_KEYS = ("case_id", "slide_id", "patch_id")
_TOKEN_KEYS = ("specialty", "mode")
_QUERY_KEYS = ("text", "query", "prompt")

_lock = threading.Lock()
_ready: tuple[str, str] | None = None


def _warn(action: str, exc: Exception) -> None:
    logger.warning("consult tracing %s failed (%s)", action, type(exc).__name__)


def _import_mlflow() -> Any:
    import mlflow

    return mlflow


def _secret(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _safe_id(value: object) -> str | None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or _secret(value):
        return None
    return value


def _safe_token(value: object) -> str | None:
    if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value) or _secret(value):
        return None
    return value


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _copy_safe(source: dict[str, Any], dest: dict[str, Any]) -> None:
    for key in _ID_KEYS:
        parsed = _safe_id(source.get(key))
        if parsed is not None:
            dest[key] = parsed
    for key in _TOKEN_KEYS:
        parsed = _safe_token(source.get(key))
        if parsed is not None:
            dest[key] = parsed
    limit = _safe_int(source.get("limit"))
    if limit is not None:
        dest["limit"] = limit
    for key in _QUERY_KEYS:
        text = source.get(key)
        if isinstance(text, str):
            dest["query_chars"] = int(dest.get("query_chars", 0)) + len(text)


def sanitize_tool_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Ids, a specialty or mode token, a limit, and query length. Nothing else."""
    if not isinstance(arguments, dict):
        return {}
    safe: dict[str, Any] = {}
    _copy_safe(arguments, safe)
    filters = arguments.get("filters")
    if isinstance(filters, dict):
        _copy_safe(filters, safe)
    region = arguments.get("region")
    if isinstance(region, dict):
        slide_id = _safe_id(region.get("slide_id"))
        if slide_id is not None:
            safe.setdefault("slide_id", slide_id)
    case_ids = arguments.get("case_ids")
    if isinstance(case_ids, list):
        safe["case_id_count"] = sum(1 for item in case_ids if _safe_id(item) is not None)
    return safe


class _NoopSpan:
    def end(self, **_kwargs: Any) -> None:
        return None


class _LiveSpan:
    def __init__(self, name: str, span_type: str, attributes: dict[str, Any]) -> None:
        self._cm: Any = None
        self._span: Any = None
        self._closed = False
        self._started = time.perf_counter()
        try:
            mlflow = _import_mlflow()
            from mlflow.entities import SpanType

            kind = getattr(SpanType, span_type, span_type)
            self._cm = mlflow.start_span(name=name, span_type=kind, attributes=attributes)
            self._span = self._cm.__enter__()
        except Exception as exc:
            _warn("open", exc)
            self._cm = None
            self._span = None

    def close(
        self,
        attributes: dict[str, Any],
        *,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        duration_ms = max(0, int((time.perf_counter() - self._started) * 1000))
        fields = {key: value for key, value in attributes.items() if _attribute_ok(value)}
        fields["duration_ms"] = duration_ms
        try:
            if self._span is not None:
                if inputs is not None:
                    self._span.set_inputs(inputs)
                if outputs is not None:
                    self._span.set_outputs(outputs)
                self._span.set_attributes(fields)
        except Exception as exc:
            _warn("update", exc)
        try:
            if self._cm is not None:
                self._cm.__exit__(None, None, None)
        except Exception as exc:
            _warn("close", exc)
        finally:
            self._cm = None
            self._span = None


def _attribute_ok(value: object) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    if isinstance(value, str):
        return _safe_token(value) is not None or _safe_id(value) is not None
    return False


class NoopTurnTracer:
    """Tracing off. Does not import MLflow."""

    case_id: str | None = None

    def start_turn(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        model: str | None = None,
    ) -> None:
        del thread_id, model
        self.case_id = case_id

    def start_model_span(self, *, model: str | None = None, step_index: int = 0) -> _NoopSpan:
        del model, step_index
        return _NoopSpan()

    def start_tool_span(self, *, tool: str, arguments: dict[str, Any] | None = None) -> _NoopSpan:
        del tool, arguments
        return _NoopSpan()

    def end_turn(
        self,
        *,
        status: str,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_call_count: int = 0,
        citation_count: int = 0,
    ) -> None:
        del status, model, input_tokens, output_tokens, tool_call_count, citation_count
        return None


class _ModelSpan:
    def __init__(self, model: str | None, step_index: int) -> None:
        attributes: dict[str, Any] = {"step_index": step_index}
        parsed = _safe_token(model)
        if parsed is not None:
            attributes["model"] = parsed
        self._model = parsed
        self._step_index = step_index
        self._live = _LiveSpan("chat", "CHAT_MODEL", attributes)

    def end(self, **kwargs: Any) -> None:
        outputs: dict[str, Any] = {"step_index": self._step_index}
        if self._model is not None:
            outputs["model"] = self._model
        for key in ("input_tokens", "output_tokens"):
            parsed = _safe_int(kwargs.get(key))
            if parsed is not None:
                outputs[key] = parsed
        stop = _safe_token(kwargs.get("stop_reason"))
        if stop is not None:
            outputs["stop_reason"] = stop
        self._live.close(outputs, outputs=outputs)


class _ToolSpan:
    def __init__(self, tool: str, arguments: dict[str, Any] | None) -> None:
        name = tool if _TOOL_RE.fullmatch(tool) and not _secret(tool) else "tool"
        self._inputs = sanitize_tool_arguments(arguments)
        self._inputs["tool_name"] = name
        self._live = _LiveSpan(name, "TOOL", {"tool_name": name})

    def end(self, **kwargs: Any) -> None:
        outputs: dict[str, Any] = {}
        result_count = _safe_int(kwargs.get("result_count"))
        result_bytes = _safe_int(kwargs.get("result_bytes"))
        if result_count is not None:
            outputs["result_count"] = result_count
        if result_bytes is not None:
            outputs["result_bytes"] = result_bytes
        ok = kwargs.get("ok")
        if isinstance(ok, bool):
            outputs["ok"] = ok
        self._live.close(outputs, inputs=dict(self._inputs), outputs=outputs)


class MlflowTurnTracer(NoopTurnTracer):
    """One MLflow trace per consult turn. Fail-open on backend errors."""

    def __init__(self) -> None:
        self._root: _LiveSpan | None = None
        self._thread_id: str | None = None
        self._model: str | None = None

    def start_turn(
        self,
        *,
        case_id: str,
        thread_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.case_id = case_id
        self._thread_id = _safe_id(thread_id)
        self._model = _safe_token(model)
        attributes: dict[str, Any] = {}
        parsed_case = _safe_id(case_id)
        if parsed_case is not None:
            attributes["case_id"] = parsed_case
        if self._thread_id is not None:
            attributes["thread_id"] = self._thread_id
        if self._model is not None:
            attributes["model"] = self._model
        self._root = _LiveSpan("consult_turn", "AGENT", attributes)

    def start_model_span(self, *, model: str | None = None, step_index: int = 0) -> _ModelSpan:
        chosen = model if model is not None else self._model
        return _ModelSpan(chosen, step_index)

    def start_tool_span(
        self,
        *,
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> _ToolSpan:
        return _ToolSpan(tool, arguments)

    def end_turn(
        self,
        *,
        status: str,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_call_count: int = 0,
        citation_count: int = 0,
    ) -> None:
        if self._root is None:
            return
        root = self._root
        self._root = None
        outputs: dict[str, Any] = {}
        parsed_case = _safe_id(self.case_id)
        if parsed_case is not None:
            outputs["case_id"] = parsed_case
        if self._thread_id is not None:
            outputs["thread_id"] = self._thread_id
        parsed_model = _safe_token(model) or self._model
        if parsed_model is not None:
            outputs["model"] = parsed_model
        parsed_status = _safe_token(status)
        if parsed_status is not None:
            outputs["status"] = parsed_status
        for key, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("tool_call_count", tool_call_count),
            ("citation_count", citation_count),
        ):
            parsed = _safe_int(value)
            if parsed is not None:
                outputs[key] = parsed
        root.close(outputs, outputs=outputs)


def _file_store(uri: str) -> bool:
    if uri.startswith(("databricks", "http://", "https://", "sqlite:", "postgresql:", "mysql:")):
        return False
    return True


def _databricks_target(settings: Settings) -> tuple[str, str] | None:
    host = (settings.databricks_host or "").strip().rstrip("/")
    secret = settings.databricks_token
    token = secret.get_secret_value().strip() if secret is not None else ""
    if not host or not token:
        return None
    return host, token


def _tracking_uri(settings: Settings) -> str | None:
    raw = (settings.mlflow_tracking_uri or "").strip()
    if raw == "" or raw == "databricks" or raw.startswith("databricks:"):
        if _databricks_target(settings) is None:
            return None
        return "databricks"
    return raw


def _configure(uri: str, experiment: str, settings: Settings) -> None:
    global _ready
    key = (uri, experiment)
    with _lock:
        if _ready == key:
            return
        if uri == "databricks":
            target = _databricks_target(settings)
            if target is None:
                raise RuntimeError("databricks credentials missing")
            host, token = target
            os.environ["DATABRICKS_HOST"] = host
            os.environ["DATABRICKS_TOKEN"] = token
        elif _file_store(uri):
            os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        mlflow = _import_mlflow()
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experiment)
        _ready = key


def build_tracer(settings: Settings) -> NoopTurnTracer:
    """Noop when tracing is off or Databricks credentials are missing."""
    if not settings.mlflow_tracing_enabled:
        return NoopTurnTracer()
    uri = _tracking_uri(settings)
    if uri is None:
        logger.warning("consult tracing skipped (databricks credentials missing)")
        return NoopTurnTracer()
    experiment = settings.mlflow_experiment_name.strip() or _DEFAULT_EXPERIMENT
    try:
        _configure(uri, experiment, settings)
    except Exception as exc:
        _warn("configure", exc)
        return NoopTurnTracer()
    return MlflowTurnTracer()


# The loop imported this name when the tracer was only an in-memory no-op.
TurnTracer = NoopTurnTracer
