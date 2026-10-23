"""Explicit controlled Live charging contract; model limits alone are insufficient.

The public model card establishes native capacity. It does not certify auxiliary
ASR/listening charges. Those need an independently reviewed, model-bound contract
before production admission. Synthetic tests supply their own explicit proof;
they do not register a production billing contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.model_routing.pricing import PaidExposure


class LiveContractUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LiveAuxiliaryBounds:
    model_id: str
    max_listening_tokens: int
    max_input_transcript_tokens: int
    max_output_transcript_tokens: int
    transcript_usage_mode: str
    source: str
    version: int

    def __post_init__(self):
        for field in (
            "max_listening_tokens",
            "max_input_transcript_tokens",
            "max_output_transcript_tokens",
            "version",
        ):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise LiveContractUnavailable(
                    "Positive reviewed auxiliary bound/version required"
                )
        if not isinstance(self.source, str) or not self.source.strip():
            raise LiveContractUnavailable("Reviewed auxiliary source required")
        if self.transcript_usage_mode != "response_text":
            raise LiveContractUnavailable(
                "Auxiliary transcription usage is unqualified"
            )


@dataclass(frozen=True, slots=True)
class LiveModelContract:
    model_id: str
    auxiliary_bounds: LiveAuxiliaryBounds
    source: str = "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live"
    version: int = 1
    input_token_limit: int = 131072
    output_token_limit: int = 65536
    max_activity_seconds: int = 30
    max_physical_seconds: int = 60

    def __post_init__(self):
        if (
            self.model_id != "gemini-3.8-live"
            or not isinstance(self.auxiliary_bounds, LiveAuxiliaryBounds)
            or self.auxiliary_bounds.model_id != self.model_id
        ):
            raise LiveContractUnavailable("Unknown exact Live model/auxiliary binding")
        if (self.input_token_limit, self.output_token_limit) != (131072, 65536):
            raise LiveContractUnavailable("Unreviewed native Live capacity")
        if (
            type(self.max_activity_seconds) is not int
            or not 0 < self.max_activity_seconds <= 30
        ):
            raise LiveContractUnavailable("Bounded activity required")
        if (
            type(self.max_physical_seconds) is not int
            or not self.max_activity_seconds <= self.max_physical_seconds <= 60
        ):
            raise LiveContractUnavailable("Bounded physical lifetime required")
        if (
            type(self.version) is not int
            or self.version != 1
            or self.source
            != "https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live"
        ):
            raise LiveContractUnavailable("Unknown native Live contract provenance")

    def exposure(self, scope_id: str) -> PaidExposure:
        """Reserve each modality's full capacity; ASR/listening are additive."""
        aux = self.auxiliary_bounds
        return PaidExposure(
            usage_bounds={
                "input_tokens": self.input_token_limit,
                "input_audio_tokens": self.input_token_limit + aux.max_listening_tokens,
                "output_tokens": self.output_token_limit
                + aux.max_input_transcript_tokens
                + aux.max_output_transcript_tokens,
                "output_audio_tokens": self.output_token_limit,
            },
            scope_kind="voice",
            scope_id=scope_id,
            max_seconds=self.max_physical_seconds,
        )


def reviewed_live_contract(
    model_id: str, *, auxiliary_bounds: LiveAuxiliaryBounds | None = None
) -> LiveModelContract:
    if model_id != "gemini-3.8-live":
        raise LiveContractUnavailable("Exact controlled Live model is unsupported")
    if auxiliary_bounds is None:
        raise LiveContractUnavailable(
            "Live auxiliary billing bound/accounting is unverified"
        )
    return LiveModelContract(model_id=model_id, auxiliary_bounds=auxiliary_bounds)


def _get(raw: Any, field: str):
    return raw.get(field) if isinstance(raw, dict) else getattr(raw, field, None)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _modalities(raw):
    if not isinstance(raw, list | tuple):
        return None
    result = {"TEXT": 0, "AUDIO": 0}
    seen = set()
    for detail in raw:
        modality = _get(detail, "modality")
        modality = getattr(modality, "value", modality)
        count = _count(_get(detail, "token_count"))
        if modality not in result or modality in seen or count is None:
            return None
        seen.add(modality)
        result[modality] = count
    return result


def normalize_live_usage(
    raw, *, contract: LiveModelContract
) -> tuple[dict[str, int], bool]:
    """Normalize one generation snapshot, never guess missing/ambiguous usage.

    Idempotence/delta identity belongs to the admission owner. Cached input is
    charged at its full rate; thought tokens are explicit text output. Auxiliary
    ASR is included only under the caller's reviewed response-text accounting
    contract, never inferred from an ordinary SDK schema or model name.
    """
    if not isinstance(contract, LiveModelContract):
        raise LiveContractUnavailable("Reviewed Live contract required")
    prompt = _count(_get(raw, "prompt_token_count"))
    response = _count(_get(raw, "response_token_count"))
    thoughts = _count(_get(raw, "thoughts_token_count"))
    total = _count(_get(raw, "total_token_count"))
    cached = _count(_get(raw, "cached_content_token_count"))
    tools = _count(_get(raw, "tool_use_prompt_token_count"))
    inputs = _modalities(_get(raw, "prompt_tokens_details"))
    outputs = _modalities(_get(raw, "response_tokens_details"))
    usage = {}
    if inputs is not None:
        usage.update(input_tokens=inputs["TEXT"], input_audio_tokens=inputs["AUDIO"])
    if outputs is not None:
        usage["output_audio_tokens"] = outputs["AUDIO"]
        if thoughts is not None:
            usage["output_tokens"] = outputs["TEXT"] + thoughts
    complete = (
        all(v is not None for v in (prompt, response, thoughts, total, cached, tools))
        and inputs is not None
        and outputs is not None
        and sum(inputs.values()) == prompt
        and sum(outputs.values()) == response
        and prompt + response + thoughts == total
        and cached <= prompt
        and tools == 0
    )
    return usage, complete
