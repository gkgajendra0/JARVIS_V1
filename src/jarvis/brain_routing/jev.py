"""Bounded TypeSafe Jev decision adapter.

This module deliberately owns no JARVIS lifecycle, Authority, verification, or
execution truth.  It converts a finite set of typed Choice questions into one Jev
request and validates the returned probabilistic decisions.  Callers remain
responsible for deterministic eligibility, policy checks, confidence thresholds,
and any resulting state transition.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _probability(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return normalized


@dataclass(frozen=True, slots=True)
class JevChoiceQuestion:
    name: str
    instructions: str
    choices: dict[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, field="name"))
        object.__setattr__(
            self,
            "instructions",
            _required_text(self.instructions, field="instructions"),
        )
        normalized: dict[str, str] = {}
        for raw_key, raw_description in self.choices.items():
            key = _required_text(raw_key, field="choice").casefold()
            description = _required_text(
                raw_description,
                field=f"choice[{key}] description",
            )
            if key in normalized:
                raise ValueError(f"duplicate choice: {key}")
            normalized[key] = description
        if len(normalized) < 2:
            raise ValueError("choice question requires at least two choices")
        object.__setattr__(self, "choices", normalized)


@dataclass(frozen=True, slots=True)
class JevDecisionRequest:
    decision_family: str
    state: str | dict[str, Any] | tuple[Any, ...]
    questions: tuple[JevChoiceQuestion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_family",
            _required_text(
                self.decision_family,
                field="decision_family",
            ).casefold(),
        )
        if not self.questions:
            raise ValueError("questions must not be empty")
        names = [question.name for question in self.questions]
        if len(names) != len(set(names)):
            raise ValueError("question names must be unique")


@dataclass(frozen=True, slots=True)
class JevChoiceDecision:
    question_name: str
    choice: str
    confidence: float
    probabilities: dict[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question_name",
            _required_text(self.question_name, field="question_name"),
        )
        object.__setattr__(
            self,
            "choice",
            _required_text(self.choice, field="choice").casefold(),
        )
        object.__setattr__(
            self,
            "confidence",
            _probability(self.confidence, field="confidence"),
        )
        normalized = {
            _required_text(key, field="probability choice").casefold(): _probability(
                value,
                field=f"probabilities[{key}]",
            )
            for key, value in self.probabilities.items()
        }
        object.__setattr__(self, "probabilities", normalized)


@dataclass(frozen=True, slots=True)
class JevDecisionResult:
    decision_family: str
    requested_model: str
    resolved_model: str
    answers: tuple[JevChoiceDecision, ...]
    input_tokens: int | None = None
    output_tokens: int | None = None

    def answer(self, question_name: str) -> JevChoiceDecision:
        normalized = _required_text(question_name, field="question_name")
        for answer in self.answers:
            if answer.question_name == normalized:
                return answer
        raise KeyError(normalized)

    @property
    def minimum_confidence(self) -> float:
        return min(answer.confidence for answer in self.answers)


class JevProtocolError(ValueError):
    """TypeSafe returned content that violates the bounded decision contract."""


JsonTransport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    dict[str, Any],
]


def _default_json_transport(
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jev HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jev unavailable: {exc.reason}") from exc

    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise JevProtocolError("Jev response must be a JSON object")
    return decoded


class TypeSafeJevClient:
    """Strict Jev client for bounded choices only.

    The API key is supplied directly to the client and is never persisted by this
    adapter.  The caller decides where the secret comes from.
    """

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = DEFAULT_JEV_ENDPOINT,
        model: str = DEFAULT_JEV_MODEL,
        timeout_seconds: float = 20.0,
        transport: JsonTransport = _default_json_transport,
    ) -> None:
        self._api_key = _required_text(api_key, field="api_key")
        self.endpoint = _required_text(endpoint, field="endpoint")
        self.model = _required_text(model, field="model")
        self.timeout_seconds = float(timeout_seconds)
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self._transport = transport

    def decide(self, request: JevDecisionRequest) -> JevDecisionResult:
        if not isinstance(request, JevDecisionRequest):
            raise TypeError("request must be JevDecisionRequest")

        payload = {
            "state": request.state,
            "model": self.model,
            "questions": {
                question.name: {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": dict(question.choices),
                }
                for question in request.questions
            },
        }
        response = self._transport(
            self.endpoint,
            payload,
            {"Authorization": f"Bearer {self._api_key}"},
            self.timeout_seconds,
        )
        raw_answers = response.get("answers")
        if not isinstance(raw_answers, dict):
            raise JevProtocolError("Jev response is missing answers")

        expected_names = {question.name for question in request.questions}
        if set(raw_answers) != expected_names:
            raise JevProtocolError(
                "Jev answer names do not exactly match requested questions"
            )

        decisions: list[JevChoiceDecision] = []
        for question in request.questions:
            raw = raw_answers.get(question.name)
            if not isinstance(raw, dict) or raw.get("type") != "choice":
                raise JevProtocolError(f"{question.name}: expected a Choice answer")
            choice = str(raw.get("choice") or "").strip().casefold()
            if choice not in question.choices:
                raise JevProtocolError(
                    f"{question.name}: unsupported choice {choice!r}"
                )
            confidence = raw.get("confidence")
            if confidence is None:
                raise JevProtocolError(f"{question.name}: confidence is required")
            probabilities_raw = raw.get("probabilities")
            if not isinstance(probabilities_raw, dict):
                raise JevProtocolError(f"{question.name}: probabilities are required")
            probabilities = {
                str(key).strip().casefold(): value
                for key, value in probabilities_raw.items()
            }
            if set(probabilities) != set(question.choices):
                raise JevProtocolError(
                    f"{question.name}: probability choices do not match contract"
                )
            decisions.append(
                JevChoiceDecision(
                    question_name=question.name,
                    choice=choice,
                    confidence=confidence,
                    probabilities=probabilities,
                )
            )

        usage = response.get("usage")
        input_tokens = None
        output_tokens = None
        if isinstance(usage, dict):
            for key in ("input_tokens", "output_tokens"):
                raw = usage.get(key)
                if raw is not None and (
                    isinstance(raw, bool) or not isinstance(raw, int) or raw < 0
                ):
                    raise JevProtocolError(f"invalid usage field: {key}")
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")

        return JevDecisionResult(
            decision_family=request.decision_family,
            requested_model=self.model,
            resolved_model=_required_text(
                response.get("model") or self.model,
                field="resolved_model",
            ),
            answers=tuple(decisions),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


@dataclass(frozen=True, slots=True)
class JevAdmissionPolicy:
    """Fail-closed policy for consuming Jev output after deterministic rules."""

    admitted_families: frozenset[str]
    minimum_confidence: float

    def __post_init__(self) -> None:
        normalized = frozenset(
            _required_text(value, field="admitted_family").casefold()
            for value in self.admitted_families
        )
        if not normalized:
            raise ValueError("admitted_families must not be empty")
        object.__setattr__(self, "admitted_families", normalized)
        object.__setattr__(
            self,
            "minimum_confidence",
            _probability(
                self.minimum_confidence,
                field="minimum_confidence",
            ),
        )

    def permits(self, result: JevDecisionResult) -> bool:
        return (
            result.decision_family in self.admitted_families
            and result.minimum_confidence >= self.minimum_confidence
        )
