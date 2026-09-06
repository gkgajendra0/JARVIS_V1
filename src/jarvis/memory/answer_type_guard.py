"""Provider-independent local semantic veto for exact memory value release."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
MODEL_REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
MAX_LENGTH = 256


class MemoryAnswerType(StrEnum):
    CURRENT_VALUE = "current_value"
    CURRENT_VALUE_COMPARISON = "current_value_comparison"
    REASON_EXPLANATION = "reason_explanation"
    PROVENANCE_ACTOR = "provenance_actor"
    REPLACEMENT_SUCCESSOR = "replacement_successor"
    RELATED_RECORD = "related_record"
    OTHER_OR_ADVICE = "other_or_advice"


ANSWER_TYPE_DESCRIPTIONS: dict[MemoryAnswerType, str] = {
    MemoryAnswerType.CURRENT_VALUE: "the current recorded value of a known property",
    MemoryAnswerType.CURRENT_VALUE_COMPARISON: (
        "whether a supplied value matches the current recorded value of a known property"
    ),
    MemoryAnswerType.REASON_EXPLANATION: (
        "the reason why a recorded value was chosen or used"
    ),
    MemoryAnswerType.PROVENANCE_ACTOR: (
        "who recommended, supplied, selected, or originated a recorded value"
    ),
    MemoryAnswerType.REPLACEMENT_SUCCESSOR: (
        "the value that replaced a rejected, previous, or superseded value"
    ),
    MemoryAnswerType.RELATED_RECORD: (
        "a separate related record or linked object rather than the recorded property value itself"
    ),
    MemoryAnswerType.OTHER_OR_ADVICE: (
        "advice, another preference, or information not represented by the recorded property value itself"
    ),
}
ANSWER_TYPES = tuple(MemoryAnswerType)
ALLOW_TYPES = frozenset(
    {
        MemoryAnswerType.CURRENT_VALUE,
        MemoryAnswerType.CURRENT_VALUE_COMPARISON,
    }
)
HYPOTHESIS_TEMPLATE = "This question asks for {description}."


@dataclass(frozen=True, slots=True)
class MemoryAnswerTypeDecision:
    """Veto-only semantic classification result; never memory release authority."""

    answer_type: MemoryAnswerType
    allow: bool
    top_probability: float
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.answer_type, MemoryAnswerType):
            raise TypeError("answer_type must be a MemoryAnswerType")
        if not isinstance(self.allow, bool):
            raise TypeError("allow must be a bool")
        if self.allow != (self.answer_type in ALLOW_TYPES):
            raise ValueError("allow must match the frozen answer-type allow policy")
        if not isinstance(self.top_probability, float):
            raise TypeError("top_probability must be a float")
        if not 0.0 <= self.top_probability <= 1.0:
            raise ValueError("top_probability must be between 0 and 1")
        if not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string")
        reason = self.reason_code.strip()
        if not reason:
            raise ValueError("reason_code must not be empty")
        object.__setattr__(self, "reason_code", reason)


class MemoryAnswerTypeGuard(Protocol):
    """Local/provider-independent veto contract used by the guarded coordinator."""

    @property
    def model_name(self) -> str: ...

    async def evaluate(self, text: str) -> MemoryAnswerTypeDecision: ...


class LocalZeroShotMemoryAnswerTypeGuard:
    """Pinned multilingual zero-shot classifier with a frozen argmax-only policy."""

    def __init__(
        self,
        *,
        device: str = "cuda",
        model_id: str = MODEL_ID,
        revision: str = MODEL_REVISION,
    ) -> None:
        normalized_device = device.strip().lower()
        if normalized_device not in {"cuda", "cpu"}:
            raise ValueError("device must be 'cuda' or 'cpu'")
        self._device = normalized_device
        self._model_id = model_id.strip()
        self._revision = revision.strip()
        if not self._model_id or not self._revision:
            raise ValueError("model_id and revision must not be empty")
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._inference_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_id

    @property
    def revision(self) -> str:
        return self._revision

    async def evaluate(self, text: str) -> MemoryAnswerTypeDecision:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        query = text.strip()
        if not query:
            raise ValueError("text must not be empty")
        return await asyncio.to_thread(self._evaluate_sync, query)

    def _evaluate_sync(self, query: str) -> MemoryAnswerTypeDecision:
        with self._inference_lock:
            self._ensure_loaded()
            torch = self._torch
            tokenizer = self._tokenizer
            model = self._model
            if torch is None or tokenizer is None or model is None:
                raise RuntimeError("answer-type guard model failed to initialize")

            hypotheses = [
                HYPOTHESIS_TEMPLATE.format(
                    description=ANSWER_TYPE_DESCRIPTIONS[answer_type]
                )
                for answer_type in ANSWER_TYPES
            ]
            encoded = tokenizer(
                [query] * len(ANSWER_TYPES),
                hypotheses,
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            target = torch.device(self._device)
            encoded = {name: value.to(target) for name, value in encoded.items()}
            with torch.inference_mode():
                logits = model(**encoded).logits.float().cpu()
            if tuple(logits.shape) != (len(ANSWER_TYPES), 3):
                raise RuntimeError(
                    "pinned answer-type model returned an unexpected logits shape"
                )

            entailment_logits = logits[:, 0]
            probabilities = torch.softmax(entailment_logits, dim=0)
            best_index = int(probabilities.argmax().item())
            answer_type = ANSWER_TYPES[best_index]
            top_probability = float(probabilities[best_index].item())
            allow = answer_type in ALLOW_TYPES
            return MemoryAnswerTypeDecision(
                answer_type=answer_type,
                allow=allow,
                top_probability=top_probability,
                reason_code=(
                    "answer_type_allows_exact_value_release"
                    if allow
                    else "answer_type_vetoes_exact_value_release"
                ),
            )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self._device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA answer-type guard was requested but torch.cuda.is_available() is false"
            )

        tokenizer = AutoTokenizer.from_pretrained(
            self._model_id,
            revision=self._revision,
            trust_remote_code=False,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self._model_id,
            revision=self._revision,
            trust_remote_code=False,
            use_safetensors=True,
        )
        label2id = {
            str(key).casefold(): int(value) for key, value in model.config.label2id.items()
        }
        expected_labels = {"entailment": 0, "neutral": 1, "contradiction": 2}
        if label2id != expected_labels:
            raise RuntimeError(f"unexpected pinned NLI label mapping: {label2id!r}")

        target = torch.device(self._device)
        model = model.to(device=target, dtype=torch.float32)
        model.eval()
        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
