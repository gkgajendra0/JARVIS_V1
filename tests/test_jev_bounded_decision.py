from __future__ import annotations

import pytest

from jarvis.brain_routing.jev import (
    JevAdmissionPolicy,
    JevChoiceQuestion,
    JevDecisionRequest,
    JevProtocolError,
    TypeSafeJevClient,
)


def _request() -> JevDecisionRequest:
    return JevDecisionRequest(
        decision_family="capability_acquisition.strategy",
        state={
            "capability": "media_player.control",
            "existing_match": False,
            "current_evidence": "vendor protocol discovered",
        },
        questions=(
            JevChoiceQuestion(
                name="strategy",
                instructions="Choose the bounded acquisition strategy.",
                choices={
                    "reuse": "Reuse an already admitted capability.",
                    "wrap": "Wrap an existing approved protocol or SDK.",
                    "build": "Build a new implementation.",
                },
            ),
            JevChoiceQuestion(
                name="next_step",
                instructions="Choose the next bounded engineering step.",
                choices={
                    "research": "Gather more evidence.",
                    "architecture": "Proceed to architecture.",
                    "owner": "Ask the owner for uniquely owner-held input.",
                },
            ),
        ),
    )


def test_jev_client_emits_choice_contract_and_preserves_probabilities() -> None:
    captured = {}

    def fake_transport(endpoint, payload, headers, timeout):
        captured.update(
            {
                "endpoint": endpoint,
                "payload": payload,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return {
            "model": "jev-1.13",
            "answers": {
                "strategy": {
                    "type": "choice",
                    "choice": "wrap",
                    "confidence": 0.94,
                    "probabilities": {
                        "reuse": 0.02,
                        "wrap": 0.94,
                        "build": 0.04,
                    },
                },
                "next_step": {
                    "type": "choice",
                    "choice": "architecture",
                    "confidence": 0.91,
                    "probabilities": {
                        "research": 0.06,
                        "architecture": 0.91,
                        "owner": 0.03,
                    },
                },
            },
            "usage": {"input_tokens": 250, "output_tokens": 0},
        }

    client = TypeSafeJevClient(
        api_key="secret",
        model="jev-latest",
        timeout_seconds=7.5,
        transport=fake_transport,
    )

    result = client.decide(_request())

    assert captured["endpoint"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["headers"] == {"Authorization": "Bearer secret"}
    assert captured["timeout"] == 7.5
    assert captured["payload"]["model"] == "jev-latest"
    assert (
        captured["payload"]["questions"]["strategy"]["criteria"]["wrap"]
        == "Wrap an existing approved protocol or SDK."
    )
    assert result.requested_model == "jev-latest"
    assert result.resolved_model == "jev-1.13"
    assert result.answer("strategy").choice == "wrap"
    assert result.answer("strategy").probabilities["wrap"] == pytest.approx(0.94)
    assert result.minimum_confidence == pytest.approx(0.91)
    assert result.input_tokens == 250
    assert result.output_tokens == 0


def test_jev_client_fails_closed_on_unrequested_choice() -> None:
    def fake_transport(endpoint, payload, headers, timeout):
        del endpoint, payload, headers, timeout
        return {
            "model": "jev-test",
            "answers": {
                "strategy": {
                    "type": "choice",
                    "choice": "deploy_now",
                    "confidence": 0.99,
                    "probabilities": {
                        "reuse": 0.01,
                        "wrap": 0.01,
                        "build": 0.98,
                    },
                },
                "next_step": {
                    "type": "choice",
                    "choice": "architecture",
                    "confidence": 0.9,
                    "probabilities": {
                        "research": 0.05,
                        "architecture": 0.9,
                        "owner": 0.05,
                    },
                },
            },
        }

    client = TypeSafeJevClient(api_key="secret", transport=fake_transport)

    with pytest.raises(JevProtocolError, match="unsupported choice"):
        client.decide(_request())


def test_jev_client_requires_exact_question_set_and_probability_contract() -> None:
    def missing_answer(endpoint, payload, headers, timeout):
        del endpoint, payload, headers, timeout
        return {
            "model": "jev-test",
            "answers": {
                "strategy": {
                    "type": "choice",
                    "choice": "wrap",
                    "confidence": 0.9,
                    "probabilities": {
                        "reuse": 0.05,
                        "wrap": 0.9,
                        "build": 0.05,
                    },
                }
            },
        }

    client = TypeSafeJevClient(api_key="secret", transport=missing_answer)
    with pytest.raises(JevProtocolError, match="answer names"):
        client.decide(_request())

    def bad_probabilities(endpoint, payload, headers, timeout):
        del endpoint, payload, headers, timeout
        return {
            "model": "jev-test",
            "answers": {
                "strategy": {
                    "type": "choice",
                    "choice": "wrap",
                    "confidence": 0.9,
                    "probabilities": {"wrap": 1.0},
                },
                "next_step": {
                    "type": "choice",
                    "choice": "architecture",
                    "confidence": 0.9,
                    "probabilities": {
                        "research": 0.05,
                        "architecture": 0.9,
                        "owner": 0.05,
                    },
                },
            },
        }

    client = TypeSafeJevClient(api_key="secret", transport=bad_probabilities)
    with pytest.raises(JevProtocolError, match="probability choices"):
        client.decide(_request())


def test_jev_admission_policy_is_family_and_confidence_bounded() -> None:
    def fake_transport(endpoint, payload, headers, timeout):
        del endpoint, payload, headers, timeout
        return {
            "model": "jev-test",
            "answers": {
                "strategy": {
                    "type": "choice",
                    "choice": "wrap",
                    "confidence": 0.88,
                    "probabilities": {
                        "reuse": 0.05,
                        "wrap": 0.88,
                        "build": 0.07,
                    },
                },
                "next_step": {
                    "type": "choice",
                    "choice": "architecture",
                    "confidence": 0.86,
                    "probabilities": {
                        "research": 0.08,
                        "architecture": 0.86,
                        "owner": 0.06,
                    },
                },
            },
        }

    result = TypeSafeJevClient(
        api_key="secret",
        transport=fake_transport,
    ).decide(_request())

    assert JevAdmissionPolicy(
        admitted_families=frozenset({"capability_acquisition.strategy"}),
        minimum_confidence=0.85,
    ).permits(result)
    assert not JevAdmissionPolicy(
        admitted_families=frozenset({"capability_acquisition.strategy"}),
        minimum_confidence=0.9,
    ).permits(result)
    assert not JevAdmissionPolicy(
        admitted_families=frozenset({"work.retry"}),
        minimum_confidence=0.5,
    ).permits(result)


def test_jev_question_normalizes_choices_and_rejects_duplicates() -> None:
    question = JevChoiceQuestion(
        name="retry",
        instructions="Choose a retry path.",
        choices={" Retry ": "Retry safely.", "Escalate": "Escalate reasoning."},
    )
    assert tuple(question.choices) == ("retry", "escalate")

    with pytest.raises(ValueError, match="duplicate choice"):
        JevChoiceQuestion(
            name="retry",
            instructions="Choose.",
            choices={"Retry": "A", " retry ": "B"},
        )
