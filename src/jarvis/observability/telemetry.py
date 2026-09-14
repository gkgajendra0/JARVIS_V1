"""OpenTelemetry trace and metric adapter owned by JARVIS."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    service_name: str = "jarvis"
    service_version: str = "0.1.0"
    environment: str = "local"
    export_otlp: bool = False


class TelemetryRuntime:
    def __init__(self, config: TelemetryConfig) -> None:
        resource = Resource.create(
            {
                "service.name": config.service_name,
                "service.version": config.service_version,
                "deployment.environment.name": config.environment,
            }
        )
        self._tracer_provider = TracerProvider(resource=resource)
        metric_readers = []
        if config.export_otlp:
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter())
            )
            metric_readers.append(
                PeriodicExportingMetricReader(OTLPMetricExporter())
            )
        self._meter_provider = MeterProvider(
            resource=resource,
            metric_readers=metric_readers,
        )
        self.tracer = self._tracer_provider.get_tracer("jarvis")
        self.meter = self._meter_provider.get_meter("jarvis")

    @contextmanager
    def span(
        self,
        name: str,
        *,
        component_id: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        merged = {"jarvis.component.id": component_id}
        merged.update(attributes or {})
        with self.tracer.start_as_current_span(name, attributes=merged) as span:
            yield span

    def shutdown(self) -> None:
        self._tracer_provider.shutdown()
        self._meter_provider.shutdown()


_RUNTIME: TelemetryRuntime | None = None
_LOCK = Lock()


def configure_telemetry(config: TelemetryConfig | None = None) -> TelemetryRuntime:
    global _RUNTIME
    with _LOCK:
        if _RUNTIME is None:
            _RUNTIME = TelemetryRuntime(config or TelemetryConfig())
        return _RUNTIME


def telemetry_runtime() -> TelemetryRuntime:
    return configure_telemetry()
