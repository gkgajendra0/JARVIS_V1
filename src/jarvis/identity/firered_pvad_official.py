from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FIRERED_PVAD_PLUGIN_COMMIT = "3163734bf27878c2a76eba8849e973c5288a6b16"
FIRERED_PVAD_FILTER_ALPHA = 0.8
FIRERED_PVAD_MIN_SPEECH_SECONDS = 0.16
FIRERED_PVAD_MIN_SILENCE_SECONDS = 0.40


class FireRedOfficialParityUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FireRedOfficialParityRun:
    raw_probabilities: np.ndarray
    filtered_probabilities: np.ndarray
    frame_seconds: float
    processing_seconds: float
    warmup_processing_seconds: float
    realtime_factor: float
    frame_latencies_ms: tuple[float, ...]
    target_embedding: np.ndarray
    embedding_ms: float
    warmup_frames: int


class FireRedOfficialParityVad:
    """Benchmark FireRed pVAD with the lifecycle used by its official plugin.

    This stays benchmark-only. It mirrors the official plugin's 16 kHz / 10 ms
    ONNX contract, SpeechBrain ECAPA embedding path, LiveKit QUICK resampling,
    zero-speaker first-utterance warm-up, persistent mel/GRU state across the
    speaker update, and ExpFilter(alpha=0.8). It persists no biometric data.
    """

    sample_rate = 16_000
    frame_samples = 160
    frame_seconds = frame_samples / sample_rate

    def __init__(self, asset_dir: Path) -> None:
        try:
            import onnxruntime as ort
            import torch
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError as exc:
            raise FireRedOfficialParityUnavailable(
                "FireRed pVAD benchmark dependencies are missing; install "
                'the optional extra with: pip install -e ".[personalized-vad-benchmark]"'
            ) from exc

        self._ort = ort
        self._torch = torch
        model_path = asset_dir / "pvad.onnx"
        speaker_dir = asset_dir / "spkrec-ecapa-voxceleb"

        options = ort.SessionOptions()
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        options.inter_op_num_threads = 4
        options.intra_op_num_threads = 4
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
            sess_options=options,
        )
        self._speaker_encoder = EncoderClassifier.from_hparams(
            source=str(speaker_dir),
            savedir=str(speaker_dir),
            run_opts={"device": "cpu"},
        )
        self._reset_all_state()

    @staticmethod
    def _to_pcm16(samples: np.ndarray) -> np.ndarray:
        pcm = np.asarray(samples)
        if pcm.ndim != 1 or pcm.size == 0:
            raise ValueError("FireRed pVAD input must be non-empty mono PCM")
        if np.issubdtype(pcm.dtype, np.integer):
            info = np.iinfo(pcm.dtype)
            if info.bits == 16:
                return np.ascontiguousarray(pcm, dtype=np.int16)
            scale = float(max(abs(info.min), info.max))
            waveform = pcm.astype(np.float32) / scale
        else:
            waveform = pcm.astype(np.float32, copy=False)
        if not np.isfinite(waveform).all():
            raise ValueError("FireRed pVAD input contains non-finite samples")
        clipped = np.clip(waveform, -1.0, 1.0)
        return np.ascontiguousarray(np.rint(clipped * 32767.0), dtype=np.int16)

    def _reset_all_state(self) -> None:
        self._mel_buffer = np.zeros((1, 80, 15), dtype=np.float32)
        self._gru_buffer = np.zeros((2, 1, 256), dtype=np.float32)
        self._target_embedding = np.zeros((1, 192), dtype=np.float32)

    @staticmethod
    def _new_quick_resampler(input_rate: int):
        from livekit import rtc

        if input_rate == 16_000:
            return None
        return rtc.AudioResampler(
            input_rate=input_rate,
            output_rate=16_000,
            quality=rtc.AudioResamplerQuality.QUICK,
        )

    @classmethod
    def _push_quick_resampler(
        cls,
        resampler,
        samples: np.ndarray,
        *,
        sample_rate: int,
        flush: bool,
    ) -> np.ndarray:
        pcm16 = cls._to_pcm16(samples)
        if sample_rate == cls.sample_rate:
            return np.ascontiguousarray(
                pcm16.astype(np.float32) / np.iinfo(np.int16).max
            )
        if resampler is None:
            raise ValueError("resampler is required when sample rate is not 16 kHz")

        from livekit import rtc

        frame = rtc.AudioFrame(
            data=pcm16.tobytes(),
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=int(pcm16.size),
        )
        frames = list(resampler.push(frame))
        if flush:
            frames.extend(resampler.flush())
        if not frames:
            return np.empty(0, dtype=np.float32)
        combined = rtc.combine_audio_frames(frames)
        return np.asarray(combined.data, dtype=np.float32) / np.iinfo(np.int16).max

    def _build_target_embedding_official(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> tuple[np.ndarray, float]:
        resampler = self._new_quick_resampler(sample_rate)
        waveform = self._push_quick_resampler(
            resampler,
            samples,
            sample_rate=sample_rate,
            flush=True,
        )
        if waveform.size == 0:
            raise FireRedOfficialParityUnavailable(
                "FireRed ECAPA reference resampler produced no samples"
            )

        audio = self._torch.from_numpy(np.ascontiguousarray(waveform)).unsqueeze(0)
        started = time.perf_counter()
        with self._torch.no_grad():
            embedding = self._speaker_encoder.encode_batch(audio)[0][0].detach()
            embedding = embedding / embedding.norm(
                p=2,
                dim=0,
                keepdim=True,
            ).clamp_min(1e-12)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        target = embedding.cpu().unsqueeze(0).numpy().astype(np.float32, copy=False)
        if target.shape != (1, 192) or not np.isfinite(target).all():
            raise FireRedOfficialParityUnavailable(
                f"unexpected FireRed ECAPA target embedding shape: {target.shape}"
            )
        return np.ascontiguousarray(target), elapsed_ms

    def _infer_waveform(
        self, waveform: np.ndarray, exp_filter
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        tuple[float, ...],
        float,
    ]:
        raw: list[float] = []
        filtered: list[float] = []
        latencies: list[float] = []
        started = time.perf_counter()
        for offset in range(0, waveform.size, self.frame_samples):
            frame = waveform[offset : offset + self.frame_samples]
            if frame.size < self.frame_samples:
                frame = np.pad(frame, (0, self.frame_samples - frame.size))
            model_input = np.ascontiguousarray(frame.reshape(1, self.frame_samples))
            frame_started = time.perf_counter()
            outputs = self._session.run(
                None,
                {
                    "input_audio": model_input,
                    "spkemb": self._target_embedding,
                    "mel_buffer": self._mel_buffer,
                    "gru_buffer": self._gru_buffer,
                },
            )
            latency_ms = (time.perf_counter() - frame_started) * 1000.0
            probability = float(np.asarray(outputs[1]).reshape(-1)[0])
            raw.append(probability)
            filtered.append(float(exp_filter.apply(exp=1.0, sample=probability)))
            latencies.append(latency_ms)
            self._mel_buffer = np.asarray(outputs[2], dtype=np.float32)
            self._gru_buffer = np.asarray(outputs[3], dtype=np.float32)
        elapsed = time.perf_counter() - started
        return (
            np.asarray(raw, dtype=np.float32),
            np.asarray(filtered, dtype=np.float32),
            tuple(latencies),
            elapsed,
        )

    def run_official_lifecycle(
        self,
        reference_samples: np.ndarray,
        *,
        reference_sample_rate: int,
        samples: np.ndarray,
        sample_rate: int,
    ) -> FireRedOfficialParityRun:
        if sample_rate != reference_sample_rate:
            raise ValueError("reference and benchmark sample rates must match")

        from livekit.agents import utils

        self._reset_all_state()
        exp_filter = utils.ExpFilter(alpha=FIRERED_PVAD_FILTER_ALPHA)
        inference_resampler = self._new_quick_resampler(sample_rate)

        warmup_waveform = self._push_quick_resampler(
            inference_resampler,
            reference_samples,
            sample_rate=sample_rate,
            flush=False,
        )
        _, _, _, warmup_processing_seconds = self._infer_waveform(
            warmup_waveform,
            exp_filter,
        )

        target_embedding, embedding_ms = self._build_target_embedding_official(
            reference_samples,
            sample_rate=reference_sample_rate,
        )
        self._target_embedding = target_embedding.copy()

        test_waveform = self._push_quick_resampler(
            inference_resampler,
            samples,
            sample_rate=sample_rate,
            flush=True,
        )
        raw, filtered, latencies, processing_seconds = self._infer_waveform(
            test_waveform,
            exp_filter,
        )
        audio_seconds = test_waveform.size / self.sample_rate
        if audio_seconds <= 0:
            raise FireRedOfficialParityUnavailable(
                "FireRed pVAD benchmark resampler produced no test audio"
            )

        return FireRedOfficialParityRun(
            raw_probabilities=raw,
            filtered_probabilities=filtered,
            frame_seconds=self.frame_seconds,
            processing_seconds=processing_seconds,
            warmup_processing_seconds=warmup_processing_seconds,
            realtime_factor=processing_seconds / audio_seconds,
            frame_latencies_ms=latencies,
            target_embedding=target_embedding,
            embedding_ms=embedding_ms,
            warmup_frames=int(np.ceil(warmup_waveform.size / self.frame_samples)),
        )
