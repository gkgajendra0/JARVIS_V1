from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class FireRedPVadUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FireRedPVadRun:
    probabilities: np.ndarray
    frame_seconds: float
    processing_seconds: float
    realtime_factor: float
    frame_latencies_ms: tuple[float, ...]


class FireRedPersonalizedVad:
    """Benchmark-only adapter for FireRedChat pVAD.

    The official model contract is preserved: 16 kHz mono float32 audio, 10 ms
    frames, a 192-d ECAPA target-speaker embedding, and persistent mel/GRU state.
    This class owns no microphone and persists no biometric material.
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
            raise FireRedPVadUnavailable(
                "FireRed pVAD benchmark dependencies are missing; install "
                'the optional extra with: pip install -e ".[personalized-vad-benchmark]"'
            ) from exc

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
        self._target_embedding = np.zeros((1, 192), dtype=np.float32)
        self.reset_stream_state()

    def reset_stream_state(self) -> None:
        self._mel_buffer = np.zeros((1, 80, 15), dtype=np.float32)
        self._gru_buffer = np.zeros((2, 1, 256), dtype=np.float32)

    def build_target_embedding(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> tuple[np.ndarray, float]:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        pcm = np.asarray(samples)
        if pcm.ndim != 1 or pcm.size == 0:
            raise ValueError("target-speaker reference must be non-empty mono PCM")
        if np.issubdtype(pcm.dtype, np.integer):
            info = np.iinfo(pcm.dtype)
            scale = float(max(abs(info.min), info.max))
            waveform = pcm.astype(np.float32) / scale
        else:
            waveform = pcm.astype(np.float32, copy=False)
        if not np.isfinite(waveform).all():
            raise ValueError("target-speaker reference contains non-finite samples")

        torch = self._torch
        audio = torch.from_numpy(np.ascontiguousarray(waveform)).unsqueeze(0)
        if sample_rate != self.sample_rate:
            try:
                import torchaudio.functional as audio_f
            except ImportError as exc:
                raise FireRedPVadUnavailable(
                    "torchaudio is required to resample the pVAD speaker reference"
                ) from exc
            audio = audio_f.resample(audio, sample_rate, self.sample_rate)

        started = time.perf_counter()
        with torch.no_grad():
            embedding = self._speaker_encoder.encode_batch(audio)[0][0].detach()
            embedding = embedding / embedding.norm(p=2, dim=0, keepdim=True).clamp_min(
                1e-12
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        target = embedding.cpu().unsqueeze(0).numpy().astype(np.float32, copy=False)
        if target.shape != (1, 192) or not np.isfinite(target).all():
            raise FireRedPVadUnavailable(
                f"unexpected FireRed ECAPA target embedding shape: {target.shape}"
            )
        self._target_embedding = np.ascontiguousarray(target)
        return self._target_embedding.copy(), elapsed_ms

    def _resample_to_model_rate(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> np.ndarray:
        pcm = np.asarray(samples)
        if pcm.ndim != 1 or pcm.size == 0:
            raise ValueError("pVAD input must be non-empty mono PCM")
        if np.issubdtype(pcm.dtype, np.integer):
            info = np.iinfo(pcm.dtype)
            scale = float(max(abs(info.min), info.max))
            waveform = pcm.astype(np.float32) / scale
        else:
            waveform = pcm.astype(np.float32, copy=False)
        waveform = np.ascontiguousarray(np.clip(waveform, -1.0, 1.0))
        if sample_rate == self.sample_rate:
            return waveform
        try:
            import torchaudio.functional as audio_f
        except ImportError as exc:
            raise FireRedPVadUnavailable(
                "torchaudio is required to resample FireRed pVAD benchmark audio"
            ) from exc
        torch = self._torch
        audio = torch.from_numpy(waveform).unsqueeze(0)
        with torch.no_grad():
            resampled = audio_f.resample(audio, sample_rate, self.sample_rate)[0]
        return np.ascontiguousarray(resampled.cpu().numpy(), dtype=np.float32)

    def run(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> FireRedPVadRun:
        waveform = self._resample_to_model_rate(samples, sample_rate=sample_rate)
        self.reset_stream_state()
        probabilities: list[float] = []
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
            latencies.append((time.perf_counter() - frame_started) * 1000.0)
            probabilities.append(float(np.asarray(outputs[1]).reshape(-1)[0]))
            self._mel_buffer = np.asarray(outputs[2], dtype=np.float32)
            self._gru_buffer = np.asarray(outputs[3], dtype=np.float32)
        elapsed = time.perf_counter() - started
        audio_seconds = waveform.size / self.sample_rate
        return FireRedPVadRun(
            probabilities=np.asarray(probabilities, dtype=np.float32),
            frame_seconds=self.frame_seconds,
            processing_seconds=elapsed,
            realtime_factor=elapsed / audio_seconds,
            frame_latencies_ms=tuple(latencies),
        )
