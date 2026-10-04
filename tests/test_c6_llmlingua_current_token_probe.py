from __future__ import annotations

from types import SimpleNamespace

import pytest
from tools.research import c6_llmlingua_current_token_probe as probe
from tools.research.c6_benchmark_corpus import build_c6_benchmark_cases

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.context import WorkContextMode
from jarvis.work.reasoner import (
    _work_full_history_input_payload,
    _work_input_payload,
)


def _pass_report() -> dict[str, object]:
    case = next(
        item
        for item in build_c6_benchmark_cases()
        if item.case_id == "research_ready_for_digest_bound_finalize"
    )
    request = probe.replace(case.request, context_mode=WorkContextMode.SHADOW)
    current_payload = _work_input_payload(request)
    full_payload = _work_full_history_input_payload(request)
    versions = {
        "llmlingua": "test",
        "torch": "test",
        "transformers": "test",
        "accelerate": "test",
        "tiktoken": "test",
        "nltk": "test",
        "numpy": "test",
    }
    return {
        "status": "PASS",
        "llmlingua_fixture_benchmark": {
            "preflight_only": False,
            "all_baselines_stable": True,
            "all_fixture_cases_equivalent": True,
            "all_full_history_payloads_beat_current": True,
            "all_provider_input_tokens_reduced": True,
            "compressor_library_revision": probe.REVIEWED_LLMLINGUA_LIBRARY_REVISION,
            "compressor_model_revision": probe.DEFAULT_LLMLINGUA2_REVISION,
            "compressor_model": "fake-compressor",
            "compression_rate": 0.85,
            "device_map": "cpu",
            "runtime_dependency_versions": versions,
            "model": "gpt-6-astra",
            "cases": [
                {
                    "case_id": "research_ready_for_digest_bound_finalize",
                    "baseline_stable": True,
                    "compressed_evaluated": True,
                    "equivalent": True,
                    "action_equal": True,
                    "parameters_equal": True,
                    "goal_complete_equal": True,
                    "needs_owner_equal": True,
                    "owner_question_equal": True,
                    "beats_current_payload": True,
                    "provider_input_tokens_reduced": True,
                    "current_request_digest": canonical_digest(current_payload),
                    "full_history_request_digest": canonical_digest(full_payload),
                    "compressed_request_digest": canonical_digest(full_payload),
                    "compressed_chars": len(str(full_payload)),
                    "compressed_usage": {"input_tokens": 900},
                    "full_context_first_action": "acq_finalize",
                    "full_context_first_parameters": {
                        "proposed_capability_id": "device.control"
                    },
                }
            ],
        },
    }


def test_current_token_probe_validates_prior_pass_evidence() -> None:
    benchmark, case = probe._validated_prior_evidence(_pass_report())

    assert benchmark["model"] == "gpt-6-astra"
    assert case["case_id"] == "research_ready_for_digest_bound_finalize"


def test_current_token_probe_rejects_incomplete_evidence() -> None:
    report = _pass_report()
    report["status"] = "INCOMPLETE"

    with pytest.raises(ValueError, match="status PASS"):
        probe._validated_prior_evidence(report)


def test_current_token_probe_rebuilds_exact_payload_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _pass_report()
    benchmark, case = probe._validated_prior_evidence(report)
    expected_versions = benchmark["runtime_dependency_versions"]

    class _FakeCompressor:
        def __init__(self, **_kwargs) -> None:
            pass

        def compress_payload(self, payload):
            return SimpleNamespace(payload=payload)

    monkeypatch.setattr(probe, "LLMLingua2WorkPayloadCompressor", _FakeCompressor)
    monkeypatch.setattr(
        probe.c6,
        "_installed_compressor_versions",
        lambda: expected_versions,
    )

    request, current_payload, compressed_payload = probe._rebuild_payloads(
        benchmark,
        case,
    )

    assert len(request.full_history_steps or ()) == 14
    assert len(request.recent_steps) == 12
    assert canonical_digest(current_payload) == case["current_request_digest"]
    assert canonical_digest(compressed_payload) == case["compressed_request_digest"]


def test_current_token_probe_runtime_lineage_accepts_exact_blobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = dict(probe._ACCEPTED_RUNTIME_BLOBS)

    def _fake_git(_repo_root, *args: str) -> str:
        if args[:1] == ("hash-object",):
            requested = str(args[1]).replace("\\", "/")
            for relative_path, blob in expected.items():
                if requested.endswith(relative_path):
                    return blob
            raise AssertionError(f"unexpected hash-object path: {requested}")
        if args == ("rev-parse", "HEAD"):
            return "current-head"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(probe, "_git_output", _fake_git)

    lineage = probe._validated_runtime_lineage()

    assert lineage["accepted_owner_commit"] == probe._ACCEPTED_OWNER_COMMIT
    assert lineage["current_head"] == "current-head"
    assert lineage["runtime_lineage_matches_owner_pass"] is True


def test_current_token_probe_runtime_lineage_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = dict(probe._ACCEPTED_RUNTIME_BLOBS)
    first_path = next(iter(expected))

    def _fake_git(_repo_root, *args: str) -> str:
        if args[:1] == ("hash-object",):
            requested = str(args[1]).replace("\\", "/")
            if requested.endswith(first_path):
                return "drifted"
            for relative_path, blob in expected.items():
                if requested.endswith(relative_path):
                    return blob
            raise AssertionError(f"unexpected hash-object path: {requested}")
        if args == ("rev-parse", "HEAD"):
            return "current-head"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(probe, "_git_output", _fake_git)

    with pytest.raises(ValueError, match="runtime lineage drifted"):
        probe._validated_runtime_lineage()
