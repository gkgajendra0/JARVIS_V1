import copy
import importlib.util
import json
from pathlib import Path

import pytest

TOOL = Path(__file__).parents[1] / "tools/project_memory_log_report.py"
RID = "00000000-0000-4000-8000-000000000001"
RID2 = "00000000-0000-4000-8000-000000000002"
THREAD = "00000000-0000-4000-8000-000000000010"
USER_EVENT = "00000000-0000-4000-8000-000000000011"
ASSISTANT_EVENT = "00000000-0000-4000-8000-000000000012"


def analyzer():
    spec = importlib.util.spec_from_file_location("memory_log_report", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AcceptanceLog()


def completed():
    return {
        "request_id": RID,
        "context_revision": "a" * 64,
        "user_receipt": {
            "event_id": USER_EVENT,
            "thread_id": THREAD,
            "sequence": 1,
            "revision": 1,
            "status": "committed",
        },
        "assistant_receipt": {
            "event_id": ASSISTANT_EVENT,
            "thread_id": THREAD,
            "sequence": 4,
            "revision": 4,
            "status": "committed",
        },
        "usage": [
            {
                "operation": "reply-0",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
                "observed": True,
                "latency_ms": 200.0,
            },
            {
                "operation": "reply-1",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 30,
                    "total_tokens": 230,
                },
                "observed": True,
                "latency_ms": 400.0,
            },
        ],
    }


def test_repeated_log_prefix_is_counted_once_and_usage_is_not_double_summed():
    log = analyzer()
    row = completed()
    log.feed(json.dumps(row))
    log.feed("Jarvis> PRIVATE_USER_TEXT")
    log.feed(json.dumps(row, sort_keys=True))
    report = log.summary()
    assert (
        report["completed_requests"] == 1 and report["duplicate_completed_records"] == 1
    )
    assert report["reported_provider_steps"] == 2
    assert report["known_token_totals"] == {
        "input_tokens": 300,
        "output_tokens": 50,
        "total_tokens": 350,
    }
    assert report["provider_latency_ms"] == {"samples": 2, "p50": 200.0, "p95": 400.0}
    assert report["answer_quality"] == "not_evaluated"
    assert "PRIVATE_USER_TEXT" not in json.dumps(report)


def test_failed_usage_remains_unknown_and_raw_error_is_excluded():
    log = analyzer()
    line = (
        "NOT COMPLETED: "
        + json.dumps(
            {
                "request_id": RID2,
                "stage": "tool_personal",
                "project_id": "PRIVATE_PROJECT",
                "thread_id": THREAD,
            }
        )
        + "; error=PermissionError. PRIVATE_API_KEY"
    )
    log.feed(line)
    log.feed(line)
    report = log.summary()
    assert report["failed_requests"] == 1 and report["duplicate_failure_records"] == 1
    assert report["failed_requests_usage_unknown"] == 1
    assert report["known_token_totals"] == {}
    assert report["failure_counts"] == [
        {"stage": "tool_personal", "error": "PermissionError", "count": 1}
    ]
    assert "PRIVATE_" not in json.dumps(report)


def test_conflicting_same_request_is_reported_and_excluded_from_usage_totals():
    log = analyzer()
    a = completed()
    b = copy.deepcopy(a)
    b["usage"][0]["usage"]["input_tokens"] = 999
    log.feed(json.dumps(a))
    log.feed(json.dumps(b))
    report = log.summary()
    assert report["conflicting_request_ids"] == [RID]
    assert report["known_token_totals"] == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["assistant_receipt"].update(thread_id=RID2),
        lambda r: r["assistant_receipt"].update(status="pending"),
        lambda r: r["assistant_receipt"].update(sequence=1),
        lambda r: r["assistant_receipt"].update(event_id=USER_EVENT),
    ],
)
def test_invalid_receipt_pair_cannot_be_counted_as_completed(mutate):
    log = analyzer()
    row = completed()
    mutate(row)
    log.feed(json.dumps(row))
    report = log.summary()
    assert report["completed_requests"] == 0 and report["invalid_metadata_records"] == 1


def test_unknown_usage_and_missing_metrics_are_not_fabricated_as_zero():
    log = analyzer()
    row = completed()
    row["usage"][0].update(observed=False, usage={})
    row["usage"][1]["usage"] = {"input_tokens": 200}
    log.feed(json.dumps(row))
    report = log.summary()
    assert report["usage_unobserved_steps"] == 1
    assert report["known_token_totals"] == {"input_tokens": 200}
    assert report["token_metric_samples"] == {"input_tokens": 1}


def test_inspection_private_sources_and_unknown_fields_never_enter_report():
    log = analyzer()
    log.feed(json.dumps({"selection": {}, "sources": [{"text": "PRIVATE_TRANSCRIPT"}]}))
    log.feed("PRIVATE_ASSISTANT_ANSWER")
    row = completed()
    row["api_key"] = "PRIVATE_API_KEY"
    row["usage"][0]["usage"]["PRIVATE_METRIC"] = 123
    log.feed(json.dumps(row))
    assert "PRIVATE_" not in json.dumps(log.summary())


def test_failure_before_request_creation_is_visible_as_uncorrelated_evidence():
    log = analyzer()
    log.feed(
        'NOT COMPLETED: {"request_id": null, "stage": "authorizing"}; error=PermissionError. PRIVATE_DETAIL'
    )
    report = log.summary()
    assert report["failed_requests"] == 0
    assert report["uncorrelated_failure_lines"] == 1
    assert report["uncorrelated_failure_counts"] == [
        {"stage": "authorizing", "error": "PermissionError", "lines": 1}
    ]
    assert "PRIVATE_" not in json.dumps(report)


@pytest.mark.parametrize("bad_count", [-1, True, 1.5, "123", None])
def test_invalid_token_counts_do_not_enter_known_totals(bad_count):
    log = analyzer()
    row = completed()
    row["usage"][0]["usage"]["input_tokens"] = bad_count
    log.feed(json.dumps(row))
    report = log.summary()
    assert report["known_token_totals"]["input_tokens"] == 200
    assert report["invalid_usage_steps"] == 1


def test_missing_usage_is_explicit_and_zero_latency_is_a_valid_sample():
    log = analyzer()
    row = completed()
    row.pop("usage")
    log.feed(json.dumps(row))
    report = log.summary()
    assert report["requests_missing_usage"] == 1 and report["known_token_totals"] == {}
    assert report["provider_latency_ms"] == {"samples": 0, "p50": None, "p95": None}
    other = analyzer()
    row["usage"] = [
        {"operation": "reply-0", "usage": {}, "observed": False, "latency_ms": 0}
    ]
    other.feed(json.dumps(row))
    assert other.summary()["provider_latency_ms"] == {
        "samples": 1,
        "p50": 0.0,
        "p95": 0.0,
    }


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-be"])
def test_cli_reads_windows_logs_without_application_or_provider_access(
    tmp_path, encoding
):
    import subprocess
    import sys

    path = tmp_path / "owner-console.log"
    text = json.dumps(completed()) + "\r\nPRIVATE_ANSWER\r\n"
    path.write_bytes(
        (b"\xfe\xff" if encoding == "utf-16-be" else b"") + text.encode(encoding)
    )
    result = subprocess.run(
        [sys.executable, str(TOOL), str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0 and not result.stderr
    report = json.loads(result.stdout)
    assert report["completed_requests"] == 1 and report["reported_provider_steps"] == 2
    assert "PRIVATE_" not in result.stdout


def test_cli_never_overwrites_existing_report_or_input(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "owner.log"
    original = json.dumps(completed()).encode()
    path.write_bytes(original)
    result = subprocess.run(
        [sys.executable, str(TOOL), str(path), "--output", str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and path.read_bytes() == original
    assert not result.stdout


def test_malformed_metadata_and_nonfinite_counts_are_visible_without_echoing_content():
    log = analyzer()
    row = completed()
    row["usage"][0]["usage"]["input_tokens"] = float("nan")
    log.feed(json.dumps(row))
    log.feed("NOT COMPLETED: {PRIVATE_BROKEN_JSON}")
    report = log.summary()
    assert report["invalid_metadata_records"] == 2
    assert "PRIVATE_" not in json.dumps(report)


def test_event_identity_reuse_across_requests_is_flagged():
    log = analyzer()
    a = completed()
    b = copy.deepcopy(a)
    b["request_id"] = RID2
    log.feed(json.dumps(a))
    log.feed(json.dumps(b))
    assert len(log.summary()["event_id_conflicts"]) == 2


def test_cli_flags_uncorrelated_failure_and_does_not_claim_a_pass(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "early-failure.log"
    path.write_text(
        'NOT COMPLETED: {"request_id": null, "stage": "authorizing"}; error=PermissionError.\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(TOOL), str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 2 and report["uncorrelated_failure_lines"] == 1
    assert (
        report["answer_quality"] == "not_evaluated" and not report["billing_complete"]
    )


def test_cli_empty_or_narrative_only_log_is_not_usable_request_evidence(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "no-metadata.log"
    path.write_text("PRIVATE_CONVERSATION_ONLY\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(TOOL), str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 2 and report["completed_requests"] == 0
    assert (
        report["answer_quality"] == "not_evaluated" and "PRIVATE_" not in result.stdout
    )


def test_conflicting_failure_stages_do_not_choose_one_as_known_evidence():
    log = analyzer()
    for stage in ("routing", "generating"):
        log.feed(
            "NOT COMPLETED: "
            + json.dumps({"request_id": RID, "stage": stage})
            + "; error=ValueError."
        )
    report = log.summary()
    assert report["conflicting_request_ids"] == [RID] and report["failure_counts"] == []


def test_valid_assistant_omission_preserves_usage_without_claiming_original_saved():
    log = analyzer()
    row = completed()
    row["assistant_receipt"]["status"] = "omitted"
    log.feed(json.dumps(row))
    report = log.summary()
    assert report["completed_requests"] == 1 and report["invalid_metadata_records"] == 0
    assert report["requests_with_assistant_omission"] == 1
    assert report["known_token_totals"]["total_tokens"] == 350


def test_ordinary_json_answer_with_request_id_is_not_a_receipt_record():
    log = analyzer()
    log.feed(
        '{"request_id":"PRIVATE_EXAMPLE_ID","context_revision":"example","answer":"PRIVATE_ANSWER"}'
    )
    report = log.summary()
    assert report["invalid_metadata_records"] == 0 and report["completed_requests"] == 0
    assert "PRIVATE_" not in json.dumps(report)


def test_receipt_shaped_record_missing_request_id_is_invalid_evidence():
    log = analyzer()
    row = completed()
    row.pop("request_id")
    log.feed(json.dumps(row))
    assert log.summary()["invalid_metadata_records"] == 1


@pytest.mark.parametrize(
    "container", [{}, {"input_tokens": 100}, "PRIVATE_CORRUPT", 123, False]
)
def test_cli_rejects_present_invalid_usage_container_instead_of_missing(
    tmp_path, container
):
    import subprocess
    import sys

    path = tmp_path / "bad-usage.log"
    row = completed()
    row["usage"] = container
    path.write_text(json.dumps(row), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(TOOL), str(path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["invalid_usage_steps"] == 1 and report["requests_missing_usage"] == 0
    assert report["known_token_totals"] == {} and "PRIVATE_" not in result.stdout
