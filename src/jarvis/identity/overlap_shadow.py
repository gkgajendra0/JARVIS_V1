from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from jarvis.identity.overlap import OverlapEvidence, interpret_sortformer_probabilities
from jarvis.identity.sortformer_assets import ensure_sortformer_model
from jarvis.identity.sortformer_native import NativeSortformerDiarizer
from jarvis.identity.speaker_turn import SpeakerTurnAudio


@dataclass(frozen=True, slots=True)
class OverlapShadowResult:
    evidence: OverlapEvidence
    inference_ms: float
    realtime_factor: float


class NativeOverlapShadowObserver:
    """Read-only Sortformer overlap observer over already-captured canonical PCM.

    The native model is kept warm for the lifetime of the voice runtime. Calls are
    serialized because the upstream standalone diarizer ABI does not document one
    model instance as concurrently thread-safe. This observer never owns a sensor
    and never grants authority.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        library_path: Path | None = None,
        threshold: float = 0.5,
        push_seconds: float = 0.32,
    ) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if push_seconds <= 0.0:
            raise ValueError("push_seconds must be positive")
        self.threshold = float(threshold)
        self.push_seconds = float(push_seconds)
        self._diarizer = NativeSortformerDiarizer(
            model_path,
            library_path=library_path,
            gpu=0,
            preset="streaming",
        )
        self._lock = threading.Lock()

    @property
    def runtime_version(self) -> str:
        return self._diarizer.runtime_version

    @property
    def model_load_ms(self) -> float:
        return self._diarizer.model_load_seconds * 1000.0

    @property
    def model_path(self) -> Path:
        return self._diarizer.model_path

    def score(self, turn: SpeakerTurnAudio) -> OverlapShadowResult:
        started = time.perf_counter()
        with self._lock:
            run = self._diarizer.run_streaming(
                turn.samples,
                sample_rate=turn.sample_rate,
                push_seconds=self.push_seconds,
            )
        elapsed = time.perf_counter() - started
        evidence = interpret_sortformer_probabilities(
            run.probabilities,
            threshold=self.threshold,
        )
        return OverlapShadowResult(
            evidence=evidence,
            inference_ms=elapsed * 1000.0,
            realtime_factor=(elapsed / turn.duration_seconds)
            if turn.duration_seconds > 0.0
            else 0.0,
        )

    def close(self) -> None:
        self._diarizer.close()


def build_default_overlap_shadow_observer() -> NativeOverlapShadowObserver:
    return NativeOverlapShadowObserver(ensure_sortformer_model())
