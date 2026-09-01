"""Non-persistent Step 3B.10 speaker model bake-off on canonical JARVIS PCM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.config import JarvisConfig
from jarvis.voice.audio import LocalAudioRuntime, SessionAudioInput

_MIN_DBFS = -120.0
_DEFAULT_REFERENCE_COUNT = 5
_DEFAULT_REFERENCE_SECONDS = 3.0
_DEFAULT_TEST_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class SpeakerModelSpec:
    name: str
    path: Path

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("speaker model name must not be empty")


@dataclass(frozen=True, slots=True)
class SegmentMetrics:
    duration_seconds: float
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float


@dataclass(frozen=True, slots=True)
class ModelObservation:
    model_name: str
    scenario: str
    duration_seconds: float
    embedding_ms: float
    max_reference_cosine: float | None
    status: str


class InMemorySegmentRecorder:
    """Collect selected canonical frames without writing audio to disk."""

    def __init__(self) -> None:
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._sample_rate: int | None = None

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            raise RuntimeError("speaker benchmark recorder is already active")
        self._chunks.clear()
        self._sample_rate = None
        self._recording = True

    def accept_frame(self, frame: Any) -> None:
        if not self._recording:
            return
        if int(frame.num_channels) != 1:
            raise ValueError("speaker benchmark requires mono canonical audio")
        sample_rate = int(frame.sample_rate)
        if self._sample_rate is None:
            self._sample_rate = sample_rate
        elif sample_rate != self._sample_rate:
            raise ValueError("speaker benchmark sample rate changed during a segment")
        self._chunks.append(np.frombuffer(bytes(frame.data), dtype=np.int16).copy())

    def stop(self) -> tuple[np.ndarray, int]:
        if not self._recording:
            raise RuntimeError("speaker benchmark recorder is not active")
        self._recording = False
        if not self._chunks or self._sample_rate is None:
            self._chunks.clear()
            self._sample_rate = None
            raise RuntimeError("speaker benchmark captured no canonical audio")
        samples = np.concatenate(self._chunks)
        sample_rate = self._sample_rate
        self._chunks.clear()
        self._sample_rate = None
        return samples, sample_rate

    def clear(self) -> None:
        self._recording = False
        self._chunks.clear()
        self._sample_rate = None


class _NoOpWakeDetector:
    """Keep LocalAudioRuntime unchanged while the benchmark owns its session input."""

    def enable(self) -> None:
        return None

    def disable(self, *, clear_buffer: bool = True) -> None:
        del clear_buffer

    def feed(self, frame: Any) -> None:
        del frame

    async def aclose(self) -> None:
        return None


class SherpaSpeakerModel:
    """Thin exact-frontend wrapper around sherpa-onnx speaker embeddings."""

    def __init__(
        self,
        spec: SpeakerModelSpec,
        *,
        num_threads: int,
        provider: str,
        debug: bool,
    ) -> None:
        if num_threads <= 0:
            raise ValueError("speaker model num_threads must be positive")
        if not spec.path.is_file():
            raise FileNotFoundError(f"speaker model does not exist: {spec.path}")
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx is required for the speaker bake-off. "
                "Install the speaker extra with: pip install -e .[speaker]"
            ) from exc

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(spec.path),
            num_threads=num_threads,
            debug=debug,
            provider=provider,
        )
        if not config.validate():
            raise RuntimeError(f"invalid sherpa speaker model config: {config}")
        self.spec = spec
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.dimension = int(self._extractor.dim)
        self.size_bytes = spec.path.stat().st_size
        self.sha256 = _sha256_file(spec.path)

    def embed(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> tuple[np.ndarray | None, float]:
        waveform = int16_to_float32(samples)
        started = time.perf_counter()
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=sample_rate, waveform=waveform)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return None, elapsed_ms
        embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return normalize_embedding(embedding), elapsed_ms


def parse_model_spec(value: str) -> SpeakerModelSpec:
    name, separator, path_text = value.partition("=")
    name = name.strip()
    path_text = path_text.strip()
    if not separator or not name or not path_text:
        raise argparse.ArgumentTypeError("model must use NAME=PATH syntax")
    return SpeakerModelSpec(name=name, path=Path(path_text).expanduser())


def int16_to_float32(samples: np.ndarray) -> np.ndarray:
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.dtype != np.int16:
        raise ValueError("PCM must be a one-dimensional int16 array")
    return pcm.astype(np.float32) / 32768.0


def segment_metrics(samples: np.ndarray, sample_rate: int) -> SegmentMetrics:
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.dtype != np.int16 or pcm.size == 0:
        raise ValueError("segment metrics require non-empty 1-D int16 PCM")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    normalized = int16_to_float32(pcm)
    rms = float(np.sqrt(np.mean(np.square(normalized, dtype=np.float64))))
    peak = float(np.max(np.abs(normalized)))
    clipping_ratio = float(np.mean(np.abs(pcm.astype(np.int32)) >= 32760))
    return SegmentMetrics(
        duration_seconds=pcm.size / sample_rate,
        rms_dbfs=_amplitude_dbfs(rms),
        peak_dbfs=_amplitude_dbfs(peak),
        clipping_ratio=clipping_ratio,
    )


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("speaker embedding must be finite and non-empty")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("speaker embedding norm must be positive")
    return vector / norm


def max_reference_cosine(
    references: list[np.ndarray],
    embedding: np.ndarray,
) -> float:
    if not references:
        raise ValueError("at least one speaker reference is required")
    query = normalize_embedding(embedding)
    matrix = np.stack([normalize_embedding(item) for item in references])
    if matrix.shape[1] != query.size:
        raise ValueError("speaker reference and query dimensions must match")
    return float(np.max(matrix @ query))


def _amplitude_dbfs(amplitude: float) -> float:
    if amplitude <= 0:
        return _MIN_DBFS
    return max(_MIN_DBFS, 20.0 * math.log10(amplitude))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return (
        f"median={statistics.median(values):.4f}, "
        f"p95={ordered[p95_index]:.4f}, min={min(values):.4f}, "
        f"max={max(values):.4f}"
    )


def _print_segment_metrics(metrics: SegmentMetrics) -> None:
    print(
        "  segment "
        f"{metrics.duration_seconds:.2f}s | RMS {metrics.rms_dbfs:.1f} dBFS | "
        f"peak {metrics.peak_dbfs:.1f} dBFS | "
        f"clipped {metrics.clipping_ratio * 100.0:.3f}%"
    )


async def _consume_frames(
    source: SessionAudioInput,
    recorder: InMemorySegmentRecorder,
) -> None:
    async for frame in source:
        recorder.accept_frame(frame)


async def _capture_segment(
    recorder: InMemorySegmentRecorder,
    *,
    label: str,
    duration_seconds: float,
) -> tuple[np.ndarray, int, SegmentMetrics]:
    if duration_seconds <= 0:
        raise ValueError("capture duration must be positive")
    await asyncio.to_thread(
        input,
        f"Press Enter, then speak for {duration_seconds:.2f}s [{label}]... ",
    )
    print("  RECORDING")
    recorder.start()
    try:
        await asyncio.sleep(duration_seconds)
        samples, sample_rate = recorder.stop()
    except BaseException:
        recorder.clear()
        raise
    metrics = segment_metrics(samples, sample_rate)
    _print_segment_metrics(metrics)
    return samples, sample_rate, metrics


def _evaluate_segment(
    *,
    models: list[SherpaSpeakerModel],
    references: dict[str, list[np.ndarray]],
    samples: np.ndarray,
    sample_rate: int,
    scenario: str,
    observations: list[ModelObservation],
    add_as_reference: bool,
) -> None:
    for model in models:
        embedding, elapsed_ms = model.embed(samples, sample_rate=sample_rate)
        if embedding is None:
            print(
                f"  {model.spec.name}: NOT_READY "
                f"({elapsed_ms:.2f} ms; segment too short/model unavailable)"
            )
            observations.append(
                ModelObservation(
                    model_name=model.spec.name,
                    scenario=scenario,
                    duration_seconds=samples.size / sample_rate,
                    embedding_ms=elapsed_ms,
                    max_reference_cosine=None,
                    status="not_ready",
                )
            )
            continue

        score: float | None = None
        if add_as_reference:
            references[model.spec.name].append(embedding)
        elif references[model.spec.name]:
            score = max_reference_cosine(references[model.spec.name], embedding)

        suffix = "reference accepted" if add_as_reference else f"max cosine {score:.4f}"
        print(
            f"  {model.spec.name}: {elapsed_ms:.2f} ms | dim {embedding.size} | "
            f"{suffix}"
        )
        observations.append(
            ModelObservation(
                model_name=model.spec.name,
                scenario=scenario,
                duration_seconds=samples.size / sample_rate,
                embedding_ms=elapsed_ms,
                max_reference_cosine=score,
                status="ok",
            )
        )


def _parse_scenario_command(command: str) -> tuple[str, float] | None:
    normalized = command.strip()
    if not normalized:
        return None
    parts = normalized.split()
    if len(parts) > 2:
        raise ValueError("use: SCENARIO [SECONDS]")
    scenario = parts[0].strip()
    if not scenario:
        raise ValueError("scenario must not be empty")
    seconds = _DEFAULT_TEST_SECONDS if len(parts) == 1 else float(parts[1])
    if not math.isfinite(seconds) or seconds <= 0 or seconds > 30:
        raise ValueError("scenario seconds must be >0 and <=30")
    return scenario, seconds


def _print_final_summary(observations: list[ModelObservation]) -> None:
    print()
    print("SPEAKER BAKE-OFF SUMMARY")
    model_names = sorted({item.model_name for item in observations})
    for model_name in model_names:
        print(f"\n{model_name}")
        model_items = [item for item in observations if item.model_name == model_name]
        latencies = [item.embedding_ms for item in model_items if item.status == "ok"]
        print(f"  embedding latency ms: {_summary(latencies)}")
        scenarios = sorted(
            {item.scenario for item in model_items if item.scenario != "reference"}
        )
        for scenario in scenarios:
            items = [item for item in model_items if item.scenario == scenario]
            scores = [
                item.max_reference_cosine
                for item in items
                if item.status == "ok" and item.max_reference_cosine is not None
            ]
            not_ready = sum(item.status != "ok" for item in items)
            print(
                f"  {scenario}: n={len(items)}, not_ready={not_ready}, "
                f"max-reference cosine {_summary([float(v) for v in scores])}"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a non-persistent Step 3B.10 speaker embedding bake-off on the "
            "canonical processed JARVIS microphone stream."
        )
    )
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        type=parse_model_spec,
        metavar="NAME=PATH",
        help="Repeat for each sherpa-onnx compatible speaker embedding model.",
    )
    parser.add_argument(
        "--reference-count",
        type=int,
        default=_DEFAULT_REFERENCE_COUNT,
    )
    parser.add_argument(
        "--reference-seconds",
        type=float,
        default=_DEFAULT_REFERENCE_SECONDS,
    )
    parser.add_argument("--num-threads", type=int, default=1)
    parser.add_argument("--provider", default="cpu")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--input-device",
        default=None,
        help="Override JARVIS_AUDIO_INPUT_DEVICE for this diagnostic.",
    )
    parser.add_argument(
        "--output-device",
        default=None,
        help="Override JARVIS_AUDIO_OUTPUT_DEVICE for this diagnostic.",
    )
    return parser


async def run_speaker_benchmark(args: argparse.Namespace) -> int:
    if args.reference_count < 3:
        raise ValueError("reference-count must be at least 3")
    if not math.isfinite(args.reference_seconds) or args.reference_seconds < 1.0:
        raise ValueError("reference-seconds must be at least 1.0")

    models = [
        SherpaSpeakerModel(
            spec,
            num_threads=args.num_threads,
            provider=args.provider,
            debug=args.debug,
        )
        for spec in args.model
    ]
    names = [model.spec.name for model in models]
    if len(names) != len(set(names)):
        raise ValueError("speaker model names must be unique")

    print("JARVIS Step 3B.10 speaker identity model bake-off")
    print("--------------------------------------------------")
    print("DIAGNOSTIC ONLY: no authentication, T2/T3, or action authority.")
    print("Audio is captured from the canonical AEC/NS/HPF/AGC JARVIS route.")
    print("No raw audio, embedding, voiceprint, or biometric template is saved.")
    print("No similarity threshold is applied.")
    print()
    for model in models:
        print(
            f"{model.spec.name}: {model.spec.path} | dim={model.dimension} | "
            f"size={model.size_bytes / (1024 * 1024):.1f} MiB"
        )
        print(f"  sha256={model.sha256}")

    config = JarvisConfig.from_environment()
    input_device = args.input_device or config.audio_input_device
    output_device = args.output_device or config.audio_output_device
    runtime = LocalAudioRuntime(
        _NoOpWakeDetector(),  # type: ignore[arg-type]
        input_device_name=input_device,
        output_device_name=output_device,
        pre_roll_seconds=0.0,
        ring_buffer_seconds=max(1.0, config.audio_ring_buffer_seconds),
    )
    session_input = SessionAudioInput(capacity_frames=2_000)
    recorder = InMemorySegmentRecorder()
    consumer_task: asyncio.Task[None] | None = None
    references: dict[str, list[np.ndarray]] = {name: [] for name in names}
    observations: list[ModelObservation] = []

    try:
        await runtime.start()
        consumer_task = asyncio.create_task(
            _consume_frames(session_input, recorder),
            name="jarvis-speaker-benchmark-capture",
        )
        runtime.activate_session(session_input)
        await asyncio.sleep(0.1)

        print()
        print(
            f"REFERENCE PHASE: capture {args.reference_count} natural OWNER "
            f"segments of {args.reference_seconds:.1f}s each."
        )
        print("Use natural speech; vary wording rather than repeating a passphrase.")
        for index in range(args.reference_count):
            samples, sample_rate, _ = await _capture_segment(
                recorder,
                label=f"reference {index + 1}/{args.reference_count}",
                duration_seconds=args.reference_seconds,
            )
            _evaluate_segment(
                models=models,
                references=references,
                samples=samples,
                sample_rate=sample_rate,
                scenario="reference",
                observations=observations,
                add_as_reference=True,
            )
            del samples

        unusable = [name for name, values in references.items() if len(values) < 3]
        if unusable:
            print(
                "Insufficient usable reference embeddings for: " + ", ".join(unusable)
            )
            return 2

        print()
        print("TEST PHASE")
        print("Enter: SCENARIO [SECONDS]. Examples:")
        print("  owner-normal 3")
        print("  owner-quiet 3")
        print("  owner-hinglish 3")
        print("  owner-short 0.5")
        print("  tv 3")
        print("  jarvis-playback 3")
        print("Repeat a scenario to build a distribution. Enter q to finish.")

        while True:
            command = await asyncio.to_thread(input, "scenario> ")
            if command.strip().casefold() in {"q", "quit", "exit"}:
                break
            try:
                parsed = _parse_scenario_command(command)
            except (TypeError, ValueError) as exc:
                print(f"Invalid scenario: {exc}")
                continue
            if parsed is None:
                continue
            scenario, seconds = parsed
            samples, sample_rate, _ = await _capture_segment(
                recorder,
                label=scenario,
                duration_seconds=seconds,
            )
            _evaluate_segment(
                models=models,
                references=references,
                samples=samples,
                sample_rate=sample_rate,
                scenario=scenario,
                observations=observations,
                add_as_reference=False,
            )
            del samples
    finally:
        recorder.clear()
        runtime.deactivate_session()
        if consumer_task is not None:
            await asyncio.gather(consumer_task, return_exceptions=True)
        await runtime.aclose()
        for values in references.values():
            values.clear()

    _print_final_summary(observations)
    test_count = sum(item.scenario != "reference" for item in observations)
    outcome = "COMPLETE" if test_count else "INSUFFICIENT_TEST_SAMPLES"
    print()
    print("NO OWNER PROFILE CREATED")
    print("NO RAW AUDIO OR SPEAKER EMBEDDING PERSISTED")
    print("NO DEPLOYMENT THRESHOLD SELECTED")
    print(f"STEP_3B10_SPEAKER_BAKEOFF = {outcome}")
    return 0 if test_count else 2


def main() -> None:
    args = _build_parser().parse_args()
    try:
        raise SystemExit(asyncio.run(run_speaker_benchmark(args)))
    except KeyboardInterrupt:
        print("\nSpeaker bake-off stopped. No biometric material was persisted.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
