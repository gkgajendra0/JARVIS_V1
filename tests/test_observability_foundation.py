from __future__ import annotations

import logging

from opentelemetry import trace

from jarvis.logging_config import configure_logging
from jarvis.observability.logging import get_logger
from jarvis.observability.telemetry import TelemetryConfig, TelemetryRuntime


def test_structured_logging_keeps_console_contract_and_writes_jsonl(tmp_path) -> None:
    target = tmp_path / "jarvis.jsonl"
    configured = configure_logging("INFO", jsonl_path=target)
    assert configured == target

    get_logger("jarvis.test").info(
        "self_awareness_probe",
        component_id="observability",
        api_key="must-not-be-persisted",
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = target.read_text(encoding="utf-8")
    assert "self_awareness_probe" in content
    assert "observability" in content
    assert "must-not-be-persisted" not in content
    assert "[REDACTED]" in content


def test_telemetry_runtime_creates_local_trace_without_export() -> None:
    runtime = TelemetryRuntime(
        TelemetryConfig(
            service_name="jarvis-test",
            environment="test",
            export_otlp=False,
        )
    )
    try:
        with runtime.span(
            "test.operation",
            component_id="observability",
            attributes={"jarvis.test": True},
        ) as span:
            assert span.get_span_context().is_valid
            assert trace.get_current_span() is span
    finally:
        runtime.shutdown()
