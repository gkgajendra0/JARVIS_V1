"""ChatGPT-plan Codex DevelopmentEngine adapter.

The adapter deliberately treats Codex as engineering intelligence only. Codex receives
an immutable ticket plus tool schemas and returns bounded tool batches or a typed
terminal disposition. Every executable operation remains JARVIS-owned through
DevelopmentToolPort.
"""

from __future__ import annotations

import importlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.chatgpt_plan import ChatGPTPlanSessionManager
from jarvis.provider_circuit import BackgroundProviderCircuit
from jarvis.provider_resilience import (
    ProviderFailureKind,
    classify_provider_failure,
)
from jarvis.work.store import default_work_state_dir

from .contracts import (
    DevelopmentDisposition,
    DevelopmentResultV1,
    DevelopmentTicketV1,
    DevelopmentUsageV1,
)
from .protocol import DevelopmentToolPort, DevelopmentToolSpecV1
from .session_store import DevelopmentSessionStore
from .tools import (
    DevelopmentToolDenied,
    DevelopmentToolExecutionError,
    DevelopmentToolOwnerInputRequired,
    DevelopmentToolResourceBlocked,
)

_CODEX_PROVIDER_ID = "openai_chatgpt_plan"
_CODEX_ENGINE_ID = "codex_plan"
_DEFAULT_ENGINE_VERSION = "0.160.0"
_MAX_ENGINE_TURNS = 24
_MAX_TOOL_CALLS_PER_BATCH = 8
_MAX_TOOL_CALLS_TOTAL = 64
_MAX_EXTERNAL_OBSERVATION_CHARS = 32_000
_MAX_OBSERVATION_STRING_CHARS = 8_000

_BASE_INSTRUCTIONS = """You are the bounded engineering specialist inside JARVIS.

JARVIS, not you, owns the goal, engineering lifecycle, execution authority, repository
truth, secrets, dependencies, promotion, activation, and acceptance. Work only on the
immutable DevelopmentTicket supplied by JARVIS.

You do not have authority to use native shell, filesystem mutation, package management,
Git mutation, web search, browser/computer control, child agents, or production actions.
When repository inspection, edits, tests, dependency resolution, diff inspection, or a
candidate commit is needed, request only the JARVIS development tools listed in the
ticket. Prefer batches of independent reads/searches when that avoids unnecessary model
turns. Do not batch operations whose parameters depend on an earlier result.

After JARVIS returns tool observations, reason from those observations and continue.
Never invent a tool result, test result, commit, dependency approval, or evidence
reference.

Return COMPLETED only after durable JARVIS tool evidence proves a candidate commit exists
and required tests passed after the latest source edit. If the approved architecture is
proved insufficient, return NEEDS_ARCHITECTURE_REVISION with exact supplied evidence
references and a factual reason. If fresh research is needed, return NEEDS_RESEARCH. If
an unapproved dependency is required, return NEEDS_DEPENDENCY. Resource/provider limits
are JARVIS concerns, not a reason to invent progress.

Do not ask the owner to research, run commands, install software, inspect a UI, or debug
the implementation. Return only the requested structured output contract.
"""


@dataclass(frozen=True, slots=True)
class CodexTurnResponse:
    final_response: str
    usage: DevelopmentUsageV1 | None


class CodexThreadPort(Protocol):
    @property
    def id(self) -> str: ...

    async def run_user(
        self,
        message: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse: ...

    async def run_external(
        self,
        content: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse: ...


class CodexRuntimePort(Protocol):
    @property
    def version(self) -> str: ...

    async def start_thread(
        self,
        *,
        model: str,
    ) -> CodexThreadPort: ...

    async def resume_thread(
        self,
        thread_id: str,
        *,
        model: str,
    ) -> CodexThreadPort: ...

    async def close(self) -> None: ...


class CodexRuntimeFactory(Protocol):
    def create(
        self,
        *,
        access_token: str,
        codex_home: pathlib.Path,
        cwd: pathlib.Path,
    ) -> CodexRuntimePort: ...


class _OfficialCodexThread:
    def __init__(self, thread: object, module: object) -> None:
        self._thread = thread
        self._module = module

    @property
    def id(self) -> str:
        return str(getattr(self._thread, "id"))

    @staticmethod
    def _usage(result: object) -> DevelopmentUsageV1 | None:
        usage = getattr(result, "usage", None)
        total = getattr(usage, "total", None)
        if total is None:
            return None
        return DevelopmentUsageV1(
            input_tokens=int(getattr(total, "input_tokens", 0) or 0),
            output_tokens=int(getattr(total, "output_tokens", 0) or 0),
            total_tokens=int(getattr(total, "total_tokens", 0) or 0),
        )

    async def _run(
        self,
        value: object,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse:
        result = await getattr(self._thread, "run")(
            value,
            approval_mode=getattr(self._module, "ApprovalMode").deny_all,
            sandbox=getattr(self._module, "Sandbox").read_only,
            output_schema=output_schema,
            source="jarvis_development_engine",
        )
        final = getattr(result, "final_response", None)
        if not isinstance(final, str) or not final.strip():
            raise RuntimeError(
                "Codex turn completed without a structured final response"
            )
        return CodexTurnResponse(
            final_response=final,
            usage=self._usage(result),
        )

    async def run_user(
        self,
        message: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse:
        return await self._run(message, output_schema=output_schema)

    async def run_external(
        self,
        content: str,
        *,
        output_schema: dict[str, Any],
    ) -> CodexTurnResponse:
        external = getattr(self._module, "ExternalMessage")(
            tool_name="jarvis_development",
            namespace="jarvis",
            content=content,
        )
        return await self._run(external, output_schema=output_schema)


class _OfficialCodexRuntime:
    def __init__(
        self,
        *,
        access_token: str,
        codex_home: pathlib.Path,
        cwd: pathlib.Path,
    ) -> None:
        module = importlib.import_module("openai_codex")
        self._module = module
        self._version = str(getattr(module, "__version__", _DEFAULT_ENGINE_VERSION))
        codex_home.mkdir(parents=True, exist_ok=True)
        cwd.mkdir(parents=True, exist_ok=True)

        overrides = (
            'model_provider="openai_chatgpt_plan"',
            'model_providers.openai_chatgpt_plan.name="ChatGPT plan"',
            'model_providers.openai_chatgpt_plan.base_url="https://api.openai.com/v1"',
            'model_providers.openai_chatgpt_plan.env_key="ACCESS_TOKEN"',
            'model_providers.openai_chatgpt_plan.wire_api="responses"',
            "model_providers.openai_chatgpt_plan.requires_openai_auth=false",
            "model_providers.openai_chatgpt_plan.supports_websockets=false",
            'web_search="disabled"',
            "features.apps=false",
            "features.code_mode=false",
            "features.goals=false",
            "features.image_generation=false",
            "features.multi_agent=false",
            "features.multi_agent_v2=false",
            "features.plugins=false",
            "features.request_permissions_tool=false",
            "features.shell_snapshot=false",
            "features.shell_tool=false",
            "features.standalone_web_search=false",
            "features.unified_exec=false",
            "tools.experimental_request_user_input.enabled=false",
            "tools.update_plan.enabled=false",
        )
        config = getattr(module, "CodexConfig")(
            config_overrides=overrides,
            cwd=str(cwd),
            env={
                "ACCESS_TOKEN": access_token,
                "CODEX_HOME": str(codex_home),
            },
            client_name="jarvis",
            client_title="JARVIS",
            client_version="1",
        )
        self._codex = getattr(module, "AsyncCodex")(config)

    @property
    def version(self) -> str:
        return self._version

    async def start_thread(
        self,
        *,
        model: str,
    ) -> CodexThreadPort:
        thread = await self._codex.thread_start(
            approval_mode=self._module.ApprovalMode.deny_all,
            base_instructions=_BASE_INSTRUCTIONS,
            model=model,
            model_provider=_CODEX_PROVIDER_ID,
            sandbox=self._module.Sandbox.read_only,
        )
        return _OfficialCodexThread(thread, self._module)

    async def resume_thread(
        self,
        thread_id: str,
        *,
        model: str,
    ) -> CodexThreadPort:
        thread = await self._codex.thread_resume(
            thread_id,
            approval_mode=self._module.ApprovalMode.deny_all,
            base_instructions=_BASE_INSTRUCTIONS,
            include_turns=False,
            model=model,
            model_provider=_CODEX_PROVIDER_ID,
            sandbox=self._module.Sandbox.read_only,
        )
        return _OfficialCodexThread(thread, self._module)

    async def close(self) -> None:
        await self._codex.close()


class OfficialCodexRuntimeFactory:
    """Lazy official-SDK factory so the optional dependency is not required by base CI."""

    def create(
        self,
        *,
        access_token: str,
        codex_home: pathlib.Path,
        cwd: pathlib.Path,
    ) -> CodexRuntimePort:
        return _OfficialCodexRuntime(
            access_token=access_token,
            codex_home=codex_home,
            cwd=cwd,
        )


def _directive_schema() -> dict[str, Any]:
    dispositions = [item.value for item in DevelopmentDisposition]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["tool_batch", "result"],
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
            },
            "tool_calls": {
                "type": "array",
                "maxItems": _MAX_TOOL_CALLS_PER_BATCH,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "call_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 100,
                        },
                        "tool_name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 100,
                        },
                        "parameters_json": {
                            "type": "string",
                            "minLength": 2,
                            "maxLength": 200_000,
                        },
                    },
                    "required": ["call_id", "tool_name", "parameters_json"],
                },
            },
            "disposition": {
                "enum": [*dispositions, None],
            },
            "reason": {
                "type": ["string", "null"],
                "maxLength": 2000,
            },
            "requested_dependencies": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "evidence_refs": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
            },
            "blocker_code": {
                "type": ["string", "null"],
                "maxLength": 200,
            },
        },
        "required": [
            "kind",
            "summary",
            "tool_calls",
            "disposition",
            "reason",
            "requested_dependencies",
            "evidence_refs",
            "blocker_code",
        ],
    }


def _tool_payload(spec: DevelopmentToolSpecV1) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "parameter_schema": dict(spec.parameter_schema),
    }


def _ticket_prompt(
    ticket: DevelopmentTicketV1,
    tools: DevelopmentToolPort,
) -> str:
    payload = {
        "contract": "jarvis.development_ticket.v1",
        "ticket_id": ticket.ticket_id,
        "ticket_digest": ticket.digest,
        "ticket": ticket.canonical_payload(),
        "progress": dict(tools.snapshot()),
        "tools": [_tool_payload(spec) for spec in tools.tool_specs],
        "instructions": {
            "tool_batch": (
                "Request only tools listed above. parameters_json must decode to one "
                "JSON object accepted by that tool schema."
            ),
            "terminal": (
                "Use kind=result only for a typed disposition. Evidence refs must be "
                "copied exactly from the ticket or JARVIS tool observations."
            ),
            "efficiency": (
                "Batch independent reads/searches when safe. Do not repeat unchanged "
                "investigation merely to reconsider the same evidence."
            ),
        },
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _compact_value(value: object) -> object:
    if isinstance(value, str):
        if len(value) <= _MAX_OBSERVATION_STRING_CHARS:
            return value
        return value[:_MAX_OBSERVATION_STRING_CHARS] + "...<truncated>"
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item) for key, item in list(value.items())[:64]
        }
    if isinstance(value, list | tuple):
        return [_compact_value(item) for item in value[:64]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:_MAX_OBSERVATION_STRING_CHARS]


def _external_payload(
    ticket: DevelopmentTicketV1,
    *,
    results: list[dict[str, Any]],
) -> str:
    payload = {
        "contract": "jarvis.development_tool_observations.v1",
        "ticket_id": ticket.ticket_id,
        "tool_results": _compact_value(results),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    if len(encoded) <= _MAX_EXTERNAL_OBSERVATION_CHARS:
        return encoded
    fallback = {
        "contract": "jarvis.development_tool_observations.v1",
        "ticket_id": ticket.ticket_id,
        "observation_truncated": True,
        "tool_results": [
            {
                "call_id": item.get("call_id"),
                "tool_name": item.get("tool_name"),
                "ok": item.get("ok"),
                "error": _compact_value(item.get("error")),
                "_jarvis": (
                    item.get("observation", {}).get("_jarvis")
                    if isinstance(item.get("observation"), dict)
                    else None
                ),
            }
            for item in results
        ],
    }
    return json.dumps(
        fallback,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _parse_directive(response: CodexTurnResponse) -> dict[str, Any]:
    try:
        payload = json.loads(response.final_response)
    except json.JSONDecodeError as exc:
        raise ValueError("Codex development response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("Codex development response must be an object")
    kind = str(payload.get("kind") or "").strip().casefold()
    if kind not in {"tool_batch", "result"}:
        raise ValueError("Codex development response kind is invalid")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("Codex development response summary is required")
    calls = payload.get("tool_calls")
    if not isinstance(calls, list):
        raise TypeError("Codex tool_calls must be an array")
    if len(calls) > _MAX_TOOL_CALLS_PER_BATCH:
        raise ValueError("Codex tool batch exceeds configured limit")
    payload["kind"] = kind
    payload["summary"] = summary
    return payload


def _provider_result(
    *,
    ticket: DevelopmentTicketV1,
    engine_version: str,
    thread_id: str | None,
    error: BaseException,
) -> DevelopmentResultV1:
    failure = classify_provider_failure(error, provider="chatgpt_plan")
    retryable = {
        ProviderFailureKind.QUOTA_EXHAUSTED,
        ProviderFailureKind.RATE_LIMITED,
        ProviderFailureKind.MODEL_UNAVAILABLE,
        ProviderFailureKind.PROVIDER_SERVER_ERROR,
        ProviderFailureKind.SERVICE_UNAVAILABLE,
        ProviderFailureKind.TIMEOUT,
        ProviderFailureKind.CONNECTION_LOST,
        ProviderFailureKind.LOCAL_RESOURCE_PRESSURE,
    }
    if failure.kind in retryable:
        return DevelopmentResultV1.create(
            ticket=ticket,
            disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
            engine_id=_CODEX_ENGINE_ID,
            engine_version=engine_version,
            summary="Engineering intelligence is temporarily resource-blocked.",
            reason=(
                "The approved ChatGPT-plan/Codex engineering target is temporarily "
                f"unavailable ({failure.kind.value})."
            ),
            thread_id=thread_id,
            blocker_code=failure.kind.value,
        )
    return DevelopmentResultV1.create(
        ticket=ticket,
        disposition=DevelopmentDisposition.FAILED,
        engine_id=_CODEX_ENGINE_ID,
        engine_version=engine_version,
        summary="Engineering intelligence failed closed.",
        reason=(
            "The approved ChatGPT-plan/Codex engineering target returned a "
            f"non-retryable failure ({failure.kind.value})."
        ),
        thread_id=thread_id,
    )


def _merge_usage(
    current: DevelopmentUsageV1 | None,
    next_usage: DevelopmentUsageV1 | None,
) -> DevelopmentUsageV1 | None:
    if next_usage is None:
        return current
    if current is None:
        return next_usage
    return DevelopmentUsageV1(
        input_tokens=current.input_tokens + next_usage.input_tokens,
        output_tokens=current.output_tokens + next_usage.output_tokens,
        total_tokens=current.total_tokens + next_usage.total_tokens,
    )


def _provider_thread_missing(error: BaseException) -> bool:
    """Return True only when provider working memory is definitively unavailable."""

    name = type(error).__name__
    message = " ".join(str(error).split()).casefold()
    if name not in {"InvalidParamsError", "InvalidRequestError"}:
        return False
    return "thread" in message and any(
        marker in message
        for marker in (
            "not found",
            "does not exist",
            "unknown thread",
            "missing thread",
        )
    )


class CodexPlanDevelopmentEngine:
    """Long-turn Codex engineering specialist under the JARVIS control plane."""

    engine_id = _CODEX_ENGINE_ID

    def __init__(
        self,
        *,
        chatgpt_plan: ChatGPTPlanSessionManager,
        model: str,
        sessions: DevelopmentSessionStore,
        runtime_factory: CodexRuntimeFactory | None = None,
        state_dir: pathlib.Path | None = None,
        provider_circuit: BackgroundProviderCircuit | None = None,
        max_turns: int = _MAX_ENGINE_TURNS,
        max_tool_calls: int = _MAX_TOOL_CALLS_TOTAL,
    ) -> None:
        normalized_model = str(model).strip()
        if not normalized_model:
            raise ValueError("Codex development model must not be empty")
        if not isinstance(sessions, DevelopmentSessionStore):
            raise TypeError("sessions must be DevelopmentSessionStore")
        if type(max_turns) is not int or max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
        if type(max_tool_calls) is not int or max_tool_calls < 1:
            raise ValueError("max_tool_calls must be a positive integer")
        self._chatgpt_plan = chatgpt_plan
        self._model = normalized_model
        self._sessions = sessions
        self._runtime_factory = runtime_factory or OfficialCodexRuntimeFactory()
        if provider_circuit is not None and not isinstance(
            provider_circuit,
            BackgroundProviderCircuit,
        ):
            raise TypeError("provider_circuit must be BackgroundProviderCircuit")
        self._provider_circuit = provider_circuit
        self._state_dir = (
            pathlib.Path(
                state_dir or (default_work_state_dir() / "development_engine" / "codex")
            )
            .expanduser()
            .resolve()
        )
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls
        self._observed_version = _DEFAULT_ENGINE_VERSION

    @property
    def engine_version(self) -> str:
        return self._observed_version

    async def _thread(
        self,
        runtime: CodexRuntimePort,
        ticket: DevelopmentTicketV1,
    ) -> CodexThreadPort:
        session = self._sessions.get(ticket.digest)
        if session is not None and session.thread_id:
            try:
                return await runtime.resume_thread(
                    session.thread_id,
                    model=self._model,
                )
            except Exception as exc:
                if not _provider_thread_missing(exc):
                    raise
                # Provider thread history is disposable working memory only when the
                # provider definitively reports that the saved thread no longer exists.
                # Transient quota/network/server failures must remain resource blockers
                # rather than silently creating a second expensive thread.
        thread = await runtime.start_thread(model=self._model)
        self._sessions.bind_thread(
            ticket_digest=ticket.digest,
            thread_id=thread.id,
        )
        return thread

    @staticmethod
    def _validated_evidence(
        ticket: DevelopmentTicketV1,
        requested: object,
        observed: set[str],
    ) -> tuple[str, ...]:
        if not isinstance(requested, list):
            raise TypeError("terminal evidence_refs must be an array")
        allowed = {
            *ticket.research_evidence_refs,
            *ticket.repository_context_refs,
            *observed,
        }
        normalized = tuple(
            sorted({str(item).strip() for item in requested if str(item).strip()})
        )
        unknown = [item for item in normalized if item not in allowed]
        if unknown:
            raise ValueError(
                "Codex returned evidence references outside canonical JARVIS evidence"
            )
        return normalized

    def _terminal_result(
        self,
        *,
        ticket: DevelopmentTicketV1,
        directive: dict[str, Any],
        thread_id: str,
        usage: DevelopmentUsageV1 | None,
        observed_evidence: set[str],
        changed_files: set[str],
        passing_tests: list[str],
        candidate_revision: str | None,
    ) -> DevelopmentResultV1:
        raw = directive.get("disposition")
        try:
            disposition = DevelopmentDisposition(str(raw))
        except ValueError as exc:
            raise ValueError("Codex terminal disposition is invalid") from exc
        summary = str(directive["summary"]).strip()
        reason = (
            None
            if directive.get("reason") is None
            else str(directive["reason"]).strip() or None
        )
        evidence = self._validated_evidence(
            ticket,
            directive.get("evidence_refs"),
            observed_evidence,
        )

        requested_dependencies = directive.get("requested_dependencies")
        if not isinstance(requested_dependencies, list):
            raise TypeError("requested_dependencies must be an array")
        dependencies = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in requested_dependencies
                    if str(item).strip()
                }
            )
        )
        blocker_code = (
            None
            if directive.get("blocker_code") is None
            else str(directive["blocker_code"]).strip() or None
        )

        if disposition is DevelopmentDisposition.COMPLETED:
            if candidate_revision is None or not passing_tests:
                return DevelopmentResultV1.create(
                    ticket=ticket,
                    disposition=DevelopmentDisposition.FAILED,
                    engine_id=self.engine_id,
                    engine_version=self.engine_version,
                    summary="Completion was rejected by JARVIS evidence validation.",
                    reason=(
                        "Codex declared completion without canonical candidate-commit "
                        "and passing-test evidence."
                    ),
                    thread_id=thread_id,
                    evidence_refs=tuple(sorted(observed_evidence)),
                    usage=usage,
                )
            return DevelopmentResultV1.create(
                ticket=ticket,
                disposition=disposition,
                engine_id=self.engine_id,
                engine_version=self.engine_version,
                summary=summary,
                thread_id=thread_id,
                candidate_revision=candidate_revision,
                changed_files=tuple(sorted(changed_files)),
                test_evidence_refs=tuple(sorted(set(passing_tests))),
                evidence_refs=evidence,
                usage=usage,
            )

        if (
            disposition is DevelopmentDisposition.NEEDS_ARCHITECTURE_REVISION
            and not evidence
        ):
            return DevelopmentResultV1.create(
                ticket=ticket,
                disposition=DevelopmentDisposition.FAILED,
                engine_id=self.engine_id,
                engine_version=self.engine_version,
                summary="Architecture revision request failed evidence validation.",
                reason=(
                    "Codex requested architecture revision without exact canonical "
                    "evidence references."
                ),
                thread_id=thread_id,
                usage=usage,
            )

        return DevelopmentResultV1.create(
            ticket=ticket,
            disposition=disposition,
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            summary=summary,
            reason=reason,
            thread_id=thread_id,
            evidence_refs=evidence,
            requested_dependencies=dependencies,
            blocker_code=blocker_code,
            usage=usage,
        )

    async def execute(
        self,
        ticket: DevelopmentTicketV1,
        *,
        tools: DevelopmentToolPort,
    ) -> DevelopmentResultV1:
        if not isinstance(ticket, DevelopmentTicketV1):
            raise TypeError("ticket must be DevelopmentTicketV1")
        if tuple(sorted(tools.tool_names)) != tuple(sorted(ticket.allowed_tools)):
            raise ValueError("development tool surface does not match ticket authority")

        circuit = self._provider_circuit
        if circuit is not None and not circuit.allow_request():
            remaining = max(1, int(circuit.remaining_seconds))
            return DevelopmentResultV1.create(
                ticket=ticket,
                disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
                engine_id=self.engine_id,
                engine_version=self.engine_version,
                summary="Shared ChatGPT-plan capacity is cooling down.",
                reason=(
                    "JARVIS is suppressing another expensive engineering request for "
                    f"approximately {remaining} seconds after provider pressure."
                ),
                blocker_code="provider_circuit_open",
            )

        token = self._chatgpt_plan.access_token()
        codex_home = self._state_dir / "home"
        scratch = self._state_dir / "scratch" / ticket.ticket_id
        runtime: CodexRuntimePort | None = None
        thread: CodexThreadPort | None = None
        last_usage: DevelopmentUsageV1 | None = None
        progress = dict(tools.snapshot())
        recent_progress = progress.get("recent_tool_evidence")
        observed_evidence: set[str] = set()
        if isinstance(recent_progress, list):
            for item in recent_progress:
                if not isinstance(item, dict):
                    continue
                evidence_ref = str(item.get("evidence_ref") or "").strip()
                if evidence_ref:
                    observed_evidence.add(evidence_ref)
        changed_files = {
            str(item).strip()
            for item in progress.get("changed_files", ())
            if str(item).strip()
        }
        passing_tests = [
            str(item).strip()
            for item in progress.get("passing_test_evidence_refs", ())
            if str(item).strip()
        ]
        raw_candidate = str(progress.get("candidate_revision") or "").strip().casefold()
        candidate_revision = (
            raw_candidate
            if len(raw_candidate) == 40
            and all(char in "0123456789abcdef" for char in raw_candidate)
            else None
        )
        total_tool_calls = 0

        try:
            runtime = self._runtime_factory.create(
                access_token=token,
                codex_home=codex_home,
                cwd=scratch,
            )
            self._observed_version = runtime.version
            thread = await self._thread(runtime, ticket)
            response = await thread.run_user(
                _ticket_prompt(ticket, tools),
                output_schema=_directive_schema(),
            )
            if circuit is not None:
                circuit.record_success()

            for _turn_index in range(self._max_turns):
                last_usage = _merge_usage(last_usage, response.usage)
                directive = _parse_directive(response)
                if directive["kind"] == "result":
                    return self._terminal_result(
                        ticket=ticket,
                        directive=directive,
                        thread_id=thread.id,
                        usage=last_usage,
                        observed_evidence=observed_evidence,
                        changed_files=changed_files,
                        passing_tests=passing_tests,
                        candidate_revision=candidate_revision,
                    )

                calls = directive.get("tool_calls")
                if not isinstance(calls, list) or not calls:
                    raise ValueError("Codex tool_batch must contain at least one call")
                total_tool_calls += len(calls)
                if total_tool_calls > self._max_tool_calls:
                    return DevelopmentResultV1.create(
                        ticket=ticket,
                        disposition=DevelopmentDisposition.FAILED,
                        engine_id=self.engine_id,
                        engine_version=self.engine_version,
                        summary="Development tool budget was exhausted.",
                        reason=(
                            "The engineering session exceeded the bounded JARVIS tool "
                            "budget without reaching a valid result."
                        ),
                        thread_id=thread.id,
                        evidence_refs=tuple(sorted(observed_evidence)),
                        usage=last_usage,
                    )

                tool_results: list[dict[str, Any]] = []
                for call in calls:
                    if not isinstance(call, dict):
                        raise TypeError("Codex tool call must be an object")
                    call_id = str(call.get("call_id") or "").strip()
                    tool_name = str(call.get("tool_name") or "").strip().casefold()
                    if not call_id or not tool_name:
                        raise ValueError("Codex tool call identity is invalid")
                    if tool_name not in ticket.allowed_tools:
                        tool_results.append(
                            {
                                "call_id": call_id,
                                "tool_name": tool_name,
                                "ok": False,
                                "error": "tool is outside DevelopmentTicket authority",
                            }
                        )
                        continue
                    try:
                        parameters = json.loads(str(call.get("parameters_json") or ""))
                    except json.JSONDecodeError:
                        tool_results.append(
                            {
                                "call_id": call_id,
                                "tool_name": tool_name,
                                "ok": False,
                                "error": "parameters_json is invalid JSON",
                            }
                        )
                        continue
                    if not isinstance(parameters, dict):
                        tool_results.append(
                            {
                                "call_id": call_id,
                                "tool_name": tool_name,
                                "ok": False,
                                "error": "parameters_json must decode to an object",
                            }
                        )
                        continue

                    try:
                        observation = dict(await tools.invoke(tool_name, parameters))
                    except DevelopmentToolOwnerInputRequired as exc:
                        return DevelopmentResultV1.create(
                            ticket=ticket,
                            disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
                            engine_id=self.engine_id,
                            engine_version=self.engine_version,
                            summary="Development reached a governed owner boundary.",
                            reason=exc.question,
                            thread_id=thread.id,
                            blocker_code="governed_owner_boundary",
                            usage=last_usage,
                        )
                    except DevelopmentToolResourceBlocked as exc:
                        return DevelopmentResultV1.create(
                            ticket=ticket,
                            disposition=DevelopmentDisposition.BLOCKED_RESOURCE,
                            engine_id=self.engine_id,
                            engine_version=self.engine_version,
                            summary="Development is waiting for a local resource.",
                            reason=str(exc),
                            thread_id=thread.id,
                            blocker_code="local_resource_pressure",
                            usage=last_usage,
                        )
                    except (
                        DevelopmentToolDenied,
                        DevelopmentToolExecutionError,
                    ) as exc:
                        tool_results.append(
                            {
                                "call_id": call_id,
                                "tool_name": tool_name,
                                "ok": False,
                                "error": str(exc),
                            }
                        )
                        continue

                    metadata = observation.get("_jarvis")
                    evidence_ref = (
                        str(metadata.get("evidence_ref") or "").strip()
                        if isinstance(metadata, dict)
                        else ""
                    )
                    if evidence_ref:
                        observed_evidence.add(evidence_ref)

                    if tool_name == "write_file":
                        path = str(observation.get("path") or "").strip()
                        if path:
                            changed_files.add(path)
                        candidate_revision = None
                        passing_tests.clear()
                    elif tool_name == "run_tests":
                        if observation.get("passed") is True and evidence_ref:
                            passing_tests.append(evidence_ref)
                    elif tool_name == "commit_candidate":
                        commit = str(observation.get("commit") or "").strip().casefold()
                        if observation.get("committed") is True and len(commit) == 40:
                            candidate_revision = commit

                    tool_results.append(
                        {
                            "call_id": call_id,
                            "tool_name": tool_name,
                            "ok": True,
                            "observation": observation,
                        }
                    )

                response = await thread.run_external(
                    _external_payload(ticket, results=tool_results),
                    output_schema=_directive_schema(),
                )
                if circuit is not None:
                    circuit.record_success()

            return DevelopmentResultV1.create(
                ticket=ticket,
                disposition=DevelopmentDisposition.FAILED,
                engine_id=self.engine_id,
                engine_version=self.engine_version,
                summary="Development turn budget was exhausted.",
                reason=(
                    "The engineering session reached its bounded turn budget without "
                    "a valid terminal disposition."
                ),
                thread_id=thread.id,
                evidence_refs=tuple(sorted(observed_evidence)),
                usage=last_usage,
            )
        except Exception as exc:
            if circuit is not None:
                circuit.record_failure(exc)
            return _provider_result(
                ticket=ticket,
                engine_version=self.engine_version,
                thread_id=None if thread is None else thread.id,
                error=exc,
            )
        finally:
            if runtime is not None:
                try:
                    await runtime.close()
                except Exception:
                    pass
