from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected patch anchor not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/jarvis/memory/release_guard.py",
    '''"""Same-provider structured semantic verifier for bounded memory release."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key

from .assertions import SemanticAssertionRecord


class MemoryReleaseAnswerType(StrEnum):
    CURRENT_VALUE = "current_value"
    CURRENT_VALUE_COMPARISON = "current_value_comparison"
    REASON_EXPLANATION = "reason_explanation"
    PROVENANCE_ACTOR = "provenance_actor"
    REPLACEMENT_SUCCESSOR = "replacement_successor"
    RELATED_RECORD = "related_record"
    HISTORICAL_VALUE = "historical_value"
    EXTERNAL_SOURCE = "external_source"
    BROAD_RECALL = "broad_recall"
    ADVICE_OR_OTHER = "advice_or_other"


_ALLOWED_ANSWER_TYPES = frozenset(
    {
        MemoryReleaseAnswerType.CURRENT_VALUE,
        MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
    }
)


class MemoryReleaseJudgement(BaseModel):
    """Untrusted provider judgement; JARVIS derives the final allow decision."""

    model_config = ConfigDict(extra="forbid")

    answer_type: MemoryReleaseAnswerType
    directly_supported: bool

    @property
    def allows_release(self) -> bool:
        return self.directly_supported and self.answer_type in _ALLOWED_ANSWER_TYPES


class MemoryReleaseGuard(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement: ...


class MemoryReleaseGuardError(RuntimeError):
    """Raised when the configured provider cannot return a validated judgement."""


MEMORY_RELEASE_GUARD_SYSTEM_PROMPT = """You are a conservative semantic verifier for JARVIS personal memory.

You receive exactly one USER question plus exactly one canonical current memory fact that has already passed JARVIS lifecycle, authority, sensitivity, conflict, and exact-facet checks.

Your only job is to classify whether THIS ONE FACT directly and sufficiently answers THIS QUESTION.

Return current_value with directly_supported=true only when the question asks for the current recorded value itself.
Return current_value_comparison with directly_supported=true only when the question asks whether a stated value matches or does not match the current recorded value.

For every other semantic request set directly_supported=false and classify the requested answer type accurately, including:
- why/reason/explanation -> reason_explanation
- who recommended/supplied/selected/originated it -> provenance_actor
- what replaced/succeeded an older value -> replacement_successor
- a linked or separate record -> related_record
- old/previous/former/as-of/past value -> historical_value
- what a web page/email/file/rumor/external source says -> external_source
- multiple memories/list/everything/topic recall -> broad_recall
- advice/recommendation/what should I do/anything else -> advice_or_other

Critical rule: topical relevance is NOT enough. The fact must itself contain the answer requested. Example: current car=Jimny does NOT answer why Jimny was bought, who recommended Jimny, what car came before it, or whether the user should replace it.

Do not answer the user. Do not invent facts. Return only the requested schema.
"""


def _require_text(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def memory_release_guard_input(
    *,
    text: str,
    evidence: SemanticAssertionRecord,
) -> str:
    query = _require_text(text, name="text")
    if not isinstance(evidence, SemanticAssertionRecord):
        raise TypeError("evidence must be a SemanticAssertionRecord")
    payload = {
        "user_query": query,
        "canonical_current_fact": {
            "subject_scope": evidence.subject_scope,
            "subject": evidence.subject,
            "predicate": evidence.predicate,
            "value_type": evidence.value_type.value,
            "value": evidence.value,
            "freshness": evidence.freshness_class.value,
            "verification": evidence.verification_state.value,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class OpenAIMemoryReleaseGuard:
    provider_name = "openai"

    def __init__(self, *, client: Any, model: str) -> None:
        responses = getattr(client, "responses", None)
        if responses is None or not callable(getattr(responses, "parse", None)):
            raise TypeError("client must expose responses.parse")
        self._client = client
        self._model = _require_text(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement:
        guard_input = memory_release_guard_input(text=text, evidence=evidence)
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": MEMORY_RELEASE_GUARD_SYSTEM_PROMPT},
                {"role": "user", "content": guard_input},
            ],
            text_format=MemoryReleaseJudgement,
            store=False,
        )
        judgement = getattr(response, "output_parsed", None)
        if not isinstance(judgement, MemoryReleaseJudgement):
            raise MemoryReleaseGuardError(
                "OpenAI returned no validated memory-release judgement"
            )
        return judgement


class GeminiMemoryReleaseGuard:
    provider_name = "gemini"

    def __init__(self, *, client: Any, model: str) -> None:
        aio = getattr(client, "aio", None)
        interactions = getattr(aio, "interactions", None)
        if interactions is None or not callable(getattr(interactions, "create", None)):
            raise TypeError("client must expose aio.interactions.create")
        self._client = client
        self._model = _require_text(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement:
        guard_input = memory_release_guard_input(text=text, evidence=evidence)
        response = await self._client.aio.interactions.create(
            model=self._model,
            input=guard_input,
            system_instruction=MEMORY_RELEASE_GUARD_SYSTEM_PROMPT,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MemoryReleaseJudgement.model_json_schema(),
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise MemoryReleaseGuardError(
                "Gemini returned no structured memory-release output"
            )
        try:
            return MemoryReleaseJudgement.model_validate_json(output_text)
        except ValidationError as exc:
            raise MemoryReleaseGuardError(
                "Gemini returned an invalid memory-release judgement"
            ) from exc


def build_memory_release_guard(
    *,
    provider: str,
    model: str,
) -> MemoryReleaseGuard:
    """Build the verifier under the already-selected production provider family."""

    normalized_provider = normalize_ai_provider(provider)
    normalized_model = _require_text(model, name="model")
    api_key = require_provider_api_key(
        normalized_provider,
        purpose="semantic memory release verification",
    )

    if normalized_provider == "openai":
        from openai import AsyncOpenAI

        return OpenAIMemoryReleaseGuard(
            client=AsyncOpenAI(api_key=api_key),
            model=normalized_model,
        )

    if normalized_provider == "gemini":
        from google import genai

        return GeminiMemoryReleaseGuard(
            client=genai.Client(api_key=api_key),
            model=normalized_model,
        )

    raise AssertionError(f"Unhandled AI provider: {normalized_provider}")
''',
)

write(
    "src/jarvis/memory/provider_verified_query.py",
    '''"""Bounded provider-assisted semantic release after deterministic memory gates."""

from __future__ import annotations

import logging

from .evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
    TrustedMemoryEvidence,
)
from .query_coordinator import MemoryQueryCoordinator
from .release_guard import MemoryReleaseGuard, MemoryReleaseJudgement
from .retrieval import RetrievalEligibility
from .types import Sensitivity

LOGGER = logging.getLogger(__name__)


class ProviderVerifiedMemoryQueryCoordinator:
    """Fail closed unless deterministic core and same-provider verifier both allow."""

    def __init__(
        self,
        *,
        coordinator: MemoryQueryCoordinator,
        release_guard: MemoryReleaseGuard,
    ) -> None:
        if not isinstance(coordinator, MemoryQueryCoordinator):
            raise TypeError("coordinator must be a MemoryQueryCoordinator")
        if not callable(getattr(release_guard, "evaluate", None)):
            raise TypeError("release_guard must implement MemoryReleaseGuard")
        self._coordinator = coordinator
        self._release_guard = release_guard

    @property
    def provider_name(self) -> str:
        return self._release_guard.provider_name

    @property
    def model_name(self) -> str:
        return self._release_guard.model_name

    async def resolve(
        self,
        text: str,
        *,
        eligibility: RetrievalEligibility | None = None,
    ) -> MemoryEvidenceDecision:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        query_text = text.strip()
        if not query_text:
            raise ValueError("text must not be empty")

        policy = eligibility or RetrievalEligibility.cloud_context()
        if not isinstance(policy, RetrievalEligibility):
            raise TypeError("eligibility must be RetrievalEligibility")
        if Sensitivity.LOCAL_ONLY in policy.sensitivities:
            return self._abstain("provider_semantic_recall_requires_cloud_safe_eligibility")

        try:
            core = await self._coordinator.resolve(query_text, eligibility=policy)
        except Exception:
            LOGGER.exception("Memory query core failed; semantic recall is abstaining")
            return self._abstain("memory_query_core_unavailable")

        if not isinstance(core, MemoryEvidenceDecision):
            LOGGER.error("Memory query core returned an invalid decision type")
            return self._abstain("memory_query_core_invalid_decision")
        if core.disposition is MemoryEvidenceDisposition.ABSTAIN:
            return core
        if core.evidence is None:
            LOGGER.error("Memory query core released without evidence")
            return self._abstain("memory_query_core_missing_evidence")

        try:
            judgement = await self._release_guard.evaluate(
                text=query_text,
                evidence=core.evidence.assertion,
            )
        except Exception:
            LOGGER.exception("Provider memory-release verifier failed; abstaining")
            return self._abstain("provider_memory_release_guard_unavailable")

        if not isinstance(judgement, MemoryReleaseJudgement):
            LOGGER.error("Provider memory-release verifier returned an invalid type")
            return self._abstain("provider_memory_release_guard_invalid_decision")
        if not judgement.allows_release:
            return self._abstain(
                f"provider_memory_release_veto_{judgement.answer_type.value}"
            )

        reason = "provider_verified_unique_eligible_current_exact_fact"
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.RELEASE,
            reason_code=reason,
            evidence=TrustedMemoryEvidence(
                assertion=core.evidence.assertion,
                reason_code=reason,
            ),
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryEvidenceDecision:
        return MemoryEvidenceDecision(
            disposition=MemoryEvidenceDisposition.ABSTAIN,
            reason_code=reason_code,
        )
''',
)

replace_once(
    "src/jarvis/config.py",
    "    memory_candidate_extraction_model: str | None = None\n    vision_enabled: bool = False\n",
    "    memory_candidate_extraction_model: str | None = None\n    memory_semantic_recall_model: str | None = None\n    vision_enabled: bool = False\n",
)
replace_once(
    "src/jarvis/config.py",
    '            "memory_candidate_extraction_model",\n        ):\n',
    '            "memory_candidate_extraction_model",\n            "memory_semantic_recall_model",\n        ):\n',
)
replace_once(
    "src/jarvis/config.py",
    "        if self.memory_candidate_extraction_enabled:\n            if not self.memory_enabled:\n                raise ValueError(\n                    \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED requires \"\n                    \"JARVIS_MEMORY_ENABLED\"\n                )\n            if self.memory_candidate_extraction_model is None:\n                raise ValueError(\n                    \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL is required when \"\n                    \"candidate extraction is enabled\"\n                )\n\n",
    "        if self.memory_candidate_extraction_enabled:\n            if not self.memory_enabled:\n                raise ValueError(\n                    \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED requires \"\n                    \"JARVIS_MEMORY_ENABLED\"\n                )\n            if self.memory_candidate_extraction_model is None:\n                raise ValueError(\n                    \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL is required when \"\n                    \"candidate extraction is enabled\"\n                )\n\n        if self.memory_semantic_recall_model is not None and not self.memory_enabled:\n            raise ValueError(\n                \"JARVIS_MEMORY_SEMANTIC_RECALL_MODEL requires JARVIS_MEMORY_ENABLED\"\n            )\n\n",
)
replace_once(
    "src/jarvis/config.py",
    "    @property\n    def realtime_provider(self) -> str:\n",
    "    @property\n    def memory_semantic_recall_enabled(self) -> bool:\n        return self.memory_enabled and self.memory_semantic_recall_model is not None\n\n    @property\n    def realtime_provider(self) -> str:\n",
)
replace_once(
    "src/jarvis/config.py",
    "            memory_candidate_extraction_model=_configured_optional_text(\n                \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL\", machine\n            ),\n            vision_enabled=_configured_bool(\"JARVIS_VISION_ENABLED\", False, machine),\n",
    "            memory_candidate_extraction_model=_configured_optional_text(\n                \"JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL\", machine\n            ),\n            memory_semantic_recall_model=_configured_optional_text(\n                \"JARVIS_MEMORY_SEMANTIC_RECALL_MODEL\", machine\n            ),\n            vision_enabled=_configured_bool(\"JARVIS_VISION_ENABLED\", False, machine),\n",
)

replace_once(
    "src/jarvis/machine_config.py",
    '        "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL",\n        "JARVIS_VISION_ENABLED",\n',
    '        "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL",\n        "JARVIS_MEMORY_SEMANTIC_RECALL_MODEL",\n        "JARVIS_VISION_ENABLED",\n',
)

replace_once(
    ".env.example",
    "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL=\n\n# Wake/audio values.",
    "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL=\n\n# Optional bounded Phase-4.5D semantic recall. Setting this model enables the\n# same-provider structured planner + verifier fallback. It is intentionally\n# probabilistic and fail-closed; leave blank to keep semantic recall disabled.\n# Gemini production recommendation as of Sep 2026: gemini-3.8-flash\nJARVIS_MEMORY_SEMANTIC_RECALL_MODEL=\n\n# Wake/audio values.",
)

replace_once(
    "src/jarvis/memory/runtime.py",
    "from .query import CanonicalMemoryReader\nfrom .service import MemoryService\n",
    "from .query import CanonicalMemoryReader\nfrom .retrieval import SemanticRetrievalService\nfrom .service import MemoryService\n",
)
replace_once(
    "src/jarvis/memory/runtime.py",
    "        self.service = service\n        self._writer = writer\n        self._reader = reader\n",
    "        self.service = service\n        self.retrieval = SemanticRetrievalService(reader)\n        self._writer = writer\n        self._reader = reader\n",
)

replace_once(
    "src/jarvis/voice/memory_tools.py",
    "from jarvis.conversation import ConversationSession, ConversationTurn\n",
    "from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn\n",
)
replace_once(
    "src/jarvis/voice/memory_tools.py",
    "from jarvis.memory.service import (\n",
    "from jarvis.memory.evidence_gate import MemoryEvidenceDisposition\nfrom jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator\nfrom jarvis.memory.retrieval import RetrievalEligibility\nfrom jarvis.memory.service import (\n",
)
replace_once(
    "src/jarvis/voice/memory_tools.py",
    "    def __init__(\n        self,\n        service: MemoryService,\n        conversation: ConversationSession,\n    ) -> None:\n",
    "    def __init__(\n        self,\n        service: MemoryService,\n        conversation: ConversationSession,\n        *,\n        semantic_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None = None,\n    ) -> None:\n",
)
replace_once(
    "src/jarvis/voice/memory_tools.py",
    "        self._service = service\n        self._conversation = conversation\n\n    @property\n    def tools(self) -> list:\n        return [\n            self.remember_memory,\n            self.correct_memory,\n            self.forget_memory,\n            self.inspect_memory,\n        ]\n",
    "        if semantic_query_coordinator is not None and not callable(\n            getattr(semantic_query_coordinator, \"resolve\", None)\n        ):\n            raise TypeError(\n                \"semantic_query_coordinator must implement resolve when provided\"\n            )\n        self._service = service\n        self._conversation = conversation\n        self._semantic_query_coordinator = semantic_query_coordinator\n\n    @property\n    def tools(self) -> list:\n        tools = [\n            self.remember_memory,\n            self.correct_memory,\n            self.forget_memory,\n            self.inspect_memory,\n        ]\n        if self._semantic_query_coordinator is not None:\n            tools.append(self.recall_memory)\n        return tools\n",
)
replace_once(
    "src/jarvis/voice/memory_tools.py",
    "    async def inspect(self, *, predicate: str) -> dict[str, object]:\n",
    "    def _latest_user_turn(self) -> ConversationTurn:\n        turn = next(\n            (\n                candidate\n                for candidate in reversed(self._conversation.turns)\n                if candidate.role is ConversationRole.USER\n            ),\n            None,\n        )\n        if turn is None:\n            raise MemoryToolGroundingError(\n                \"semantic recall requires a latest accepted user utterance\"\n            )\n        return turn\n\n    async def semantic_recall(self) -> dict[str, object]:\n        coordinator = self._semantic_query_coordinator\n        if coordinator is None:\n            raise MemoryToolGroundingError(\n                \"semantic memory recall is not enabled for this session\"\n            )\n        turn = self._latest_user_turn()\n        decision = await coordinator.resolve(\n            turn.text,\n            eligibility=RetrievalEligibility.cloud_context(),\n        )\n        if decision.disposition is MemoryEvidenceDisposition.ABSTAIN:\n            LOGGER.info(\n                \"Semantic memory recall abstained | turn_id=%s | reason=%s\",\n                turn.turn_id,\n                decision.reason_code,\n            )\n            return {\n                \"ok\": False,\n                \"operation\": \"semantic_recall\",\n                \"reason\": \"No safely releasable current memory matched this question.\",\n            }\n        if decision.evidence is None:\n            raise RuntimeError(\"semantic recall released without trusted evidence\")\n        record = decision.evidence.assertion\n        LOGGER.info(\n            \"Semantic memory recall released | turn_id=%s | predicate=%s | \"\n            \"sensitivity=%s | reason=%s\",\n            turn.turn_id,\n            record.predicate,\n            record.sensitivity.value,\n            decision.reason_code,\n        )\n        return {\n            \"ok\": True,\n            \"operation\": \"semantic_recall\",\n            \"predicate\": record.predicate,\n            \"value\": record.value,\n            \"sensitivity\": record.sensitivity.value,\n            \"freshness\": record.freshness_class.value,\n            \"verification\": record.verification_state.value,\n        }\n\n    async def inspect(self, *, predicate: str) -> dict[str, object]:\n",
)
replace_once(
    "src/jarvis/voice/memory_tools.py",
    "    @function_tool()\n    async def inspect_memory(\n",
    "    @function_tool()\n    async def recall_memory(\n        self,\n        context: RunContext,\n    ) -> dict[str, object]:\n        \"\"\"Recall one current personal fact for the latest USER question.\n\n        Use this only when the latest accepted user utterance asks for a personal fact\n        that may already exist in JARVIS durable memory. Do not provide a predicate or\n        memory key: JARVIS reads the canonical latest USER utterance itself, performs\n        structured semantic planning, exact canonical lookup, cloud-sensitivity\n        filtering, and a second same-provider ALLOW/ABSTAIN verification. If the tool\n        returns ok=false, do not guess or claim a remembered answer.\n        \"\"\"\n        del context\n        return await self._call_tool(self.semantic_recall())\n\n    @function_tool()\n    async def inspect_memory(\n",
)

replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "from jarvis.memory.runtime import MemoryRuntime\n",
    "from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator\nfrom jarvis.memory.runtime import MemoryRuntime\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "        memory_runtime: MemoryRuntime,\n        conversation_getter: Callable[[], ConversationSession | None],\n    ) -> None:\n",
    "        memory_runtime: MemoryRuntime,\n        conversation_getter: Callable[[], ConversationSession | None],\n        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None,\n    ) -> None:\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "        self._memory_runtime = memory_runtime\n        self._conversation_getter = conversation_getter\n",
    "        self._memory_runtime = memory_runtime\n        self._conversation_getter = conversation_getter\n        self._memory_query_coordinator = memory_query_coordinator\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "                MemoryAgentTools(\n                    self._memory_runtime.service,\n                    conversation,\n                ).tools\n",
    "                MemoryAgentTools(\n                    self._memory_runtime.service,\n                    conversation,\n                    semantic_query_coordinator=self._memory_query_coordinator,\n                ).tools\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,\n        memory_runtime: MemoryRuntime | None = None,\n        **kwargs: Any,\n",
    "        speaker_shadow_observer: EnrolledSpeakerShadowObserver | None = None,\n        memory_runtime: MemoryRuntime | None = None,\n        memory_query_coordinator: ProviderVerifiedMemoryQueryCoordinator | None = None,\n        **kwargs: Any,\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "        self._speaker_shadow_observer = speaker_shadow_observer\n        self._memory_runtime = memory_runtime\n        if memory_runtime is not None:\n",
    "        self._speaker_shadow_observer = speaker_shadow_observer\n        self._memory_runtime = memory_runtime\n        if memory_query_coordinator is not None and memory_runtime is None:\n            raise ValueError(\n                \"memory_query_coordinator requires an active memory runtime\"\n            )\n        self._memory_query_coordinator = memory_query_coordinator\n        if memory_runtime is not None:\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "                memory_runtime,\n                lambda: self._memory_conversation,\n            )\n",
    "                memory_runtime,\n                lambda: self._memory_conversation,\n                memory_query_coordinator,\n            )\n",
)
replace_once(
    "src/jarvis/voice/canonical_active_speaker_runtime.py",
    "        LOGGER.info(\n            \"JARVIS explicit persistent memory is active; implicit admission remains disabled\"\n        )\n",
    "        LOGGER.info(\n            \"JARVIS explicit persistent memory is active; implicit admission remains disabled\"\n        )\n        if self._memory_query_coordinator is not None:\n            LOGGER.warning(\n                \"Bounded provider-assisted semantic recall is active | provider=%s | \"\n                \"model=%s | final semantic verification is probabilistic and fail-closed\",\n                self._memory_query_coordinator.provider_name,\n                self._memory_query_coordinator.model_name,\n            )\n",
)

replace_once(
    "src/jarvis/voice/production_runtime.py",
    "from jarvis.memory.extractors import build_memory_candidate_extractor\nfrom jarvis.memory.runtime import build_default_memory_runtime\n",
    "from jarvis.memory.extractors import build_memory_candidate_extractor\nfrom jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator\nfrom jarvis.memory.query_coordinator import MemoryQueryCoordinator\nfrom jarvis.memory.query_interpreters import build_memory_query_interpreter\nfrom jarvis.memory.release_guard import build_memory_release_guard\nfrom jarvis.memory.runtime import build_default_memory_runtime\n",
)
replace_once(
    "src/jarvis/voice/production_runtime.py",
    "    memory_runtime = build_default_memory_runtime() if config.memory_enabled else None\n\n    candidate_extractor = None\n",
    "    memory_runtime = build_default_memory_runtime() if config.memory_enabled else None\n\n    memory_query_coordinator = None\n    if memory_runtime is not None and config.memory_semantic_recall_enabled:\n        assert config.memory_semantic_recall_model is not None\n        query_model = config.memory_semantic_recall_model\n        interpreter = build_memory_query_interpreter(\n            provider=config.ai_provider,\n            model=query_model,\n        )\n        release_guard = build_memory_release_guard(\n            provider=config.ai_provider,\n            model=query_model,\n        )\n        memory_query_coordinator = ProviderVerifiedMemoryQueryCoordinator(\n            coordinator=MemoryQueryCoordinator(\n                interpreter=interpreter,\n                retrieval=memory_runtime.retrieval,\n            ),\n            release_guard=release_guard,\n        )\n        LOGGER.warning(\n            \"Phase-4.5D bounded provider-assisted semantic recall configured: \"\n            \"active_provider=%s model=%s structured_planner=True \"\n            \"structured_release_verifier=True deterministic_core=True \"\n            \"probabilistic_semantic_boundary=True\",\n            config.ai_provider,\n            query_model,\n        )\n\n    candidate_extractor = None\n",
)
replace_once(
    "src/jarvis/voice/production_runtime.py",
    "        memory_runtime=memory_runtime,\n        session_factory=production_session_factory,\n",
    "        memory_runtime=memory_runtime,\n        memory_query_coordinator=memory_query_coordinator,\n        session_factory=production_session_factory,\n",
)

replace_once(
    "src/jarvis/voice/agent.py",
    "A successful memory-tool result is the only basis for claiming that a\nremember/correct/forget operation succeeded. If an exact target is missing or\nambiguous, ask the user to state the memory key explicitly rather than guessing.\n",
    "A successful memory-tool result is the only basis for claiming that a\nremember/correct/forget operation succeeded. If an exact target is missing or\nambiguous, ask the user to state the memory key explicitly rather than guessing.\nIf `recall_memory` is available and the user asks for a personal fact that may already\nexist in durable memory, call it before answering from memory or assumptions. The\nrecall tool takes no memory key from you: JARVIS grounds it against the latest accepted\nUSER utterance and can abstain. If recall returns `ok: false`, do not invent or imply\nthat JARVIS remembers the requested fact. Do not use semantic recall for why/who,\nhistorical, external-source, broad-list, or advice questions unless the tool itself\nreturns a successful releasable fact.\n",
)

write(
    "tests/test_memory_provider_release_guard.py",
    '''from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.release_guard import (
    GeminiMemoryReleaseGuard,
    MemoryReleaseAnswerType,
    MemoryReleaseGuardError,
    MemoryReleaseJudgement,
    OpenAIMemoryReleaseGuard,
    memory_release_guard_input,
)
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)


def _record(*, sensitivity: Sensitivity = Sensitivity.STANDARD) -> SemanticAssertionRecord:
    now = datetime.now(UTC)
    return SemanticAssertionRecord(
        assertion_id="a1",
        subject_scope="owner",
        subject="self",
        predicate="current car",
        value_type=ValueType.TEXT,
        value="Jimny",
        normalized_text="current car Jimny",
        source_id="s1",
        valid_from=now,
        valid_to=None,
        system_from=now,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=sensitivity,
        created_at=now,
        updated_at=now,
    )


def test_release_judgement_only_allows_direct_current_shapes() -> None:
    assert MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
        directly_supported=True,
    ).allows_release
    assert MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
        directly_supported=True,
    ).allows_release
    assert not MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.REASON_EXPLANATION,
        directly_supported=True,
    ).allows_release
    assert not MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
        directly_supported=False,
    ).allows_release


def test_guard_input_contains_only_query_and_bounded_fact_fields() -> None:
    payload = json.loads(
        memory_release_guard_input(text="What car do I have?", evidence=_record())
    )
    assert payload["user_query"] == "What car do I have?"
    fact = payload["canonical_current_fact"]
    assert fact["predicate"] == "current car"
    assert fact["value"] == "Jimny"
    assert "source_id" not in fact
    assert "assertion_id" not in fact


class _FakeResponses:
    def __init__(self, judgement):
        self.judgement = judgement
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.judgement)


@pytest.mark.asyncio
async def test_openai_guard_uses_structured_parse_and_store_false() -> None:
    responses = _FakeResponses(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
            directly_supported=True,
        )
    )
    guard = OpenAIMemoryReleaseGuard(
        client=SimpleNamespace(responses=responses),
        model="gpt-test",
    )
    result = await guard.evaluate(text="What car do I have?", evidence=_record())
    assert result.allows_release
    assert responses.kwargs["text_format"] is MemoryReleaseJudgement
    assert responses.kwargs["store"] is False


class _FakeInteractions:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


@pytest.mark.asyncio
async def test_gemini_guard_uses_json_schema_and_store_false() -> None:
    interactions = _FakeInteractions(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
            directly_supported=True,
        ).model_dump_json()
    )
    client = SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    guard = GeminiMemoryReleaseGuard(client=client, model="gemini-test")
    result = await guard.evaluate(text="Is my car Jimny?", evidence=_record())
    assert result.allows_release
    assert interactions.kwargs["response_format"]["mime_type"] == "application/json"
    assert interactions.kwargs["store"] is False


@pytest.mark.asyncio
async def test_gemini_guard_rejects_invalid_structured_output() -> None:
    interactions = _FakeInteractions('{"answer_type":"not-a-role","directly_supported":true}')
    client = SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    guard = GeminiMemoryReleaseGuard(client=client, model="gemini-test")
    with pytest.raises(MemoryReleaseGuardError):
        await guard.evaluate(text="What car do I have?", evidence=_record())
''',
)

write(
    "tests/test_memory_provider_verified_query.py",
    '''from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.evidence_gate import (
    MemoryEvidenceDecision,
    MemoryEvidenceDisposition,
    TrustedMemoryEvidence,
)
from jarvis.memory.provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.release_guard import MemoryReleaseAnswerType, MemoryReleaseJudgement
from jarvis.memory.retrieval import RetrievalEligibility
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)


def _record() -> SemanticAssertionRecord:
    now = datetime.now(UTC)
    return SemanticAssertionRecord(
        assertion_id="a1",
        subject_scope="owner",
        subject="self",
        predicate="current car",
        value_type=ValueType.TEXT,
        value="Jimny",
        normalized_text="current car Jimny",
        source_id="s1",
        valid_from=now,
        valid_to=None,
        system_from=now,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=Sensitivity.STANDARD,
        created_at=now,
        updated_at=now,
    )


class _Core(MemoryQueryCoordinator):
    def __init__(self, decision: MemoryEvidenceDecision):
        self.decision = decision
        self.eligibility = None

    async def resolve(self, text, *, eligibility=None):
        self.eligibility = eligibility
        return self.decision


class _Guard:
    provider_name = "gemini"
    model_name = "gemini-test"

    def __init__(self, judgement=None, *, error: Exception | None = None):
        self.judgement = judgement
        self.error = error
        self.calls = []

    async def evaluate(self, *, text, evidence):
        self.calls.append((text, evidence))
        if self.error is not None:
            raise self.error
        return self.judgement


def _released() -> MemoryEvidenceDecision:
    record = _record()
    evidence = TrustedMemoryEvidence(assertion=record, reason_code="core")
    return MemoryEvidenceDecision(
        disposition=MemoryEvidenceDisposition.RELEASE,
        reason_code="core",
        evidence=evidence,
    )


@pytest.mark.asyncio
async def test_provider_verified_query_releases_only_after_second_allow() -> None:
    core = _Core(_released())
    guard = _Guard(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
            directly_supported=True,
        )
    )
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=guard,
    )
    result = await coordinator.resolve("What car do I have?")
    assert result.disposition is MemoryEvidenceDisposition.RELEASE
    assert result.evidence is not None
    assert result.evidence.assertion.value == "Jimny"
    assert core.eligibility == RetrievalEligibility.cloud_context()
    assert len(guard.calls) == 1


@pytest.mark.asyncio
async def test_provider_verified_query_vetoes_reason_question() -> None:
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=_Core(_released()),
        release_guard=_Guard(
            MemoryReleaseJudgement(
                answer_type=MemoryReleaseAnswerType.REASON_EXPLANATION,
                directly_supported=False,
            )
        ),
    )
    result = await coordinator.resolve("Why did I buy Jimny?")
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert result.reason_code == "provider_memory_release_veto_reason_explanation"


@pytest.mark.asyncio
async def test_provider_verified_query_fails_closed_on_verifier_error() -> None:
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=_Core(_released()),
        release_guard=_Guard(error=RuntimeError("provider down")),
    )
    result = await coordinator.resolve("What car do I have?")
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert result.reason_code == "provider_memory_release_guard_unavailable"


@pytest.mark.asyncio
async def test_provider_verified_query_refuses_local_only_eligibility_before_core() -> None:
    core = _Core(_released())
    coordinator = ProviderVerifiedMemoryQueryCoordinator(
        coordinator=core,
        release_guard=_Guard(
            MemoryReleaseJudgement(
                answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
                directly_supported=True,
            )
        ),
    )
    result = await coordinator.resolve(
        "What car do I have?",
        eligibility=RetrievalEligibility.local(),
    )
    assert result.disposition is MemoryEvidenceDisposition.ABSTAIN
    assert result.reason_code == "provider_semantic_recall_requires_cloud_safe_eligibility"
    assert core.eligibility is None
''',
)

write(
    "tests/test_memory_semantic_recall_config.py",
    '''from __future__ import annotations

import pytest

from jarvis.config import JarvisConfig
from jarvis.machine_config import PERSISTABLE_SETTINGS


def test_semantic_recall_is_opt_in_by_model_setting() -> None:
    disabled = JarvisConfig(memory_enabled=True)
    assert not disabled.memory_semantic_recall_enabled

    enabled = JarvisConfig(
        memory_enabled=True,
        memory_semantic_recall_model="gemini-3.8-flash",
    )
    assert enabled.memory_semantic_recall_enabled
    assert enabled.memory_semantic_recall_model == "gemini-3.8-flash"


def test_semantic_recall_model_requires_memory_enabled() -> None:
    with pytest.raises(ValueError, match="JARVIS_MEMORY_SEMANTIC_RECALL_MODEL"):
        JarvisConfig(
            memory_enabled=False,
            memory_semantic_recall_model="gemini-3.8-flash",
        )


def test_semantic_recall_model_is_persistable_non_secret_config() -> None:
    assert "JARVIS_MEMORY_SEMANTIC_RECALL_MODEL" in PERSISTABLE_SETTINGS
''',
)

write(
    "docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md",
    '''# Step 4 Phase 4.5D — Provider-Assisted Semantic Recall Fallback

## Status

**OWNER-AUTHORIZED BOUNDED COMPROMISE — IMPLEMENTATION ACTIVE**

Date: 2026-09-08

This work does not reverse the research conclusion that the strict independent 4.5D semantic release boundary remains unresolved. The owner explicitly chose a pragmatic fallback: use the already-selected production cloud provider (Gemini or OpenAI) for a structured semantic verification step because a probabilistic guarded recall path is more useful than having no semantic recall at all.

Step 5 remains not started while this bounded Step-4 fallback is integrated.

## Research basis

Current official APIs support the required structured classification surface:

- Gemini Interactions structured outputs accept JSON Schema and are documented for structured classification and agentic workflows.
- OpenAI Structured Outputs / Responses structured parsing can enforce a supplied schema.
- Schema conformance does not make semantic classification deterministic. This fallback therefore remains probabilistic by design.

For Gemini, `gemini-3.8-flash` is the current stable GA Flash model as of September 2026 and supports structured outputs. The implementation deliberately does not hard-code a provider-specific model; `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL` is an explicit same-provider model setting.

## Bounded architecture

```text
latest accepted USER utterance
        |
        v
same-provider structured MemoryQueryProposal
        |
        v
JARVIS deterministic grounding + query policy
        |
        v
cloud-safe eligible facet catalog + exact current facet lookup
        |
        v
exactly one canonical current assertion
        |
        v
same-provider structured semantic release verifier
        |
        +-- current value / current comparison + directly supported --> RELEASE
        |
        `-- why/who/history/replacement/related/external/broad/advice/uncertain --> ABSTAIN
        |
        v
zero-argument `recall_memory` tool result to realtime model
```

## Authority rules retained

- `JARVIS_AI_PROVIDER` remains the one production cloud-provider switch.
- The semantic-recall model must belong to that active provider family.
- The realtime model never supplies a memory predicate/key to semantic recall.
- The tool reads the latest canonical accepted USER utterance from `ConversationSession`.
- `RetrievalEligibility.cloud_context()` excludes `local_only` and `secret_prohibited` memory before any candidate value is sent to the provider.
- Provider query interpretation is untrusted input.
- JARVIS grounding/policy must select an existing eligible canonical facet.
- Exact lookup must return one and only one current assertion.
- The second provider judgement is also untrusted; JARVIS derives release only from the frozen allow shapes.
- Any provider exception, malformed structured result, ambiguity, conflict, stale exact facet, or semantic veto becomes ABSTAIN.
- No model may create, correct, supersede, forget, resurrect, or otherwise establish canonical memory truth through this path.

## Frozen allowed semantic shapes

The second verifier may permit release only when it classifies the question as:

1. `current_value` and the exact fact directly contains the requested answer; or
2. `current_value_comparison` and the exact fact directly contains the value needed for the comparison.

All other answer types veto release:

- reason/explanation;
- provenance/actor;
- replacement/successor;
- related record;
- historical value;
- external source;
- broad recall;
- advice/other.

## Explicit trade-off

This fallback is intentionally weaker than the originally desired independent deterministic/learned safety boundary. The same provider family participates in both semantic planning and final semantic verification, so correlated model mistakes remain possible. Structured output constrains shape, not semantic truth.

The product therefore treats this as **bounded useful recall**, not a proof-quality semantic authorization mechanism. If a future mature multilingual verifier meets the original strict acceptance boundary, it may replace the provider verifier without redesigning canonical storage, lifecycle, query policy, or the recall tool surface.
''',
)

replace_once(
    "docs/CURRENT_PLAN.md",
    "**No implementation step is active. Step 5 is awaiting explicit owner authorization.**",
    "**Step 4 Phase 4.5D bounded provider-assisted semantic recall fallback is active. Step 5 remains not started.**",
)
replace_once(
    "docs/CURRENT_PLAN.md",
    "**STEP 3 COMPLETE + MERGED — STEP 4 BOUNDED CLOSURE COMPLETE THROUGH 4.5C — PHASE 4.5D DEFERRED / UNRESOLVED — PHASE 4.5E AND REMAINING UNSTARTED STEP-4 EXTENSIONS DEFERRED — STEP 5 PLANNED / NOT STARTED**",
    "**STEP 3 COMPLETE + MERGED — STEP 4 FOUNDATION THROUGH 4.5C ACCEPTED — STRICT INDEPENDENT 4.5D GUARD REMAINS DEFERRED / UNRESOLVED — OWNER-AUTHORIZED PROVIDER-ASSISTED 4.5D FALLBACK ACTIVE — STEP 5 PLANNED / NOT STARTED**",
)
replace_once(
    "docs/CURRENT_PLAN.md",
    "## Step-5 boundary\n",
    "## Reopened bounded 4.5D fallback\n\nThe owner authorized a pragmatic provider-assisted recall path on 2026-09-08. The strict independent semantic guard remains unresolved; this does not rewrite the failed research evidence. The bounded fallback uses the active `JARVIS_AI_PROVIDER` for both structured query interpretation and a second structured semantic `ALLOW/ABSTAIN` verification around JARVIS-owned exact canonical lookup. It is opt-in through `JARVIS_MEMORY_SEMANTIC_RECALL_MODEL`, fail-closed on all provider/validation errors, and never releases `local_only` or secret-prohibited memory to the cloud provider. See `docs/research/STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`.\n\nStep 5 remains explicitly not started until this fallback is integrated and the owner separately authorizes Step 5.\n\n---\n\n## Step-5 boundary\n",
)

with Path("docs/research/STEP_4_PHASE_4_5D_DEFERRED_CLOSURE.md").open("a", encoding="utf-8") as handle:
    handle.write(
        "\n---\n\n## Owner-authorized bounded reopening — 2026-09-08\n\n"
        "The strict independent semantic release boundary documented above remains deferred and unresolved. The owner subsequently authorized a pragmatic same-provider structured semantic recall fallback rather than leaving semantic recall entirely unavailable. This does not promote any retired 4.5D model or relax canonical lifecycle/security rules. The fallback is tracked separately in `STEP_4_PHASE_4_5D_PROVIDER_ASSISTED_FALLBACK.md`; Step 5 remains not started until separately authorized.\n"
    )

# Remove this one-shot patch script from the final working tree.
Path("tools/research/_apply_step45d_provider_fallback_patch.py").unlink()
