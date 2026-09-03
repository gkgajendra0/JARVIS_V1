from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass

import numpy as np
from livekit import api, rtc


class KrispCloudIsolationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KrispCloudIsolationRun:
    samples: np.ndarray
    sample_rate: int
    wall_seconds: float
    input_seconds: float
    output_seconds: float
    room_name: str

    @property
    def realtime_factor(self) -> float:
        if self.input_seconds <= 0:
            return 0.0
        return self.wall_seconds / self.input_seconds


def _require_cloud_environment() -> tuple[str, str, str]:
    url = os.getenv("LIVEKIT_URL", "").strip()
    api_key = os.getenv("LIVEKIT_API_KEY", "").strip()
    api_secret = os.getenv("LIVEKIT_API_SECRET", "").strip()
    missing = [
        name
        for name, value in (
            ("LIVEKIT_URL", url),
            ("LIVEKIT_API_KEY", api_key),
            ("LIVEKIT_API_SECRET", api_secret),
        )
        if not value
    ]
    if missing:
        raise KrispCloudIsolationUnavailable(
            "LiveKit Cloud credentials are missing: " + ", ".join(missing)
        )
    return url, api_key, api_secret


def _room_token(
    *,
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
) -> str:
    return (
        api.AccessToken(api_key=api_key, api_secret=api_secret)
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .to_jwt()
    )


def _as_pcm16_mono(samples: np.ndarray) -> np.ndarray:
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.size == 0:
        raise ValueError("Krisp benchmark input must be non-empty mono PCM")
    if np.issubdtype(pcm.dtype, np.integer):
        if pcm.dtype == np.int16:
            return np.ascontiguousarray(pcm)
        info = np.iinfo(pcm.dtype)
        scale = float(max(abs(info.min), info.max))
        normalized = pcm.astype(np.float32) / scale
    else:
        normalized = pcm.astype(np.float32, copy=False)
    if not np.isfinite(normalized).all():
        raise ValueError("Krisp benchmark input contains non-finite samples")
    normalized = np.clip(normalized, -1.0, 1.0)
    return np.ascontiguousarray(np.rint(normalized * 32767.0), dtype=np.int16)


class KrispCloudIsolationRunner:
    """Replay memory-only PCM through LiveKit Cloud-backed Krisp VIVA.

    This helper is benchmark-only. It never owns the JARVIS microphone and does
    not alter the canonical security PCM path. A synthetic publisher sends the
    supplied audio to a short-lived test room; a second participant subscribes
    through the public Krisp FrameProcessor API and returns the isolated frames.
    """

    def __init__(self, *, noise_suppression_level: int = 75) -> None:
        if not 0 <= noise_suppression_level <= 100:
            raise ValueError("noise_suppression_level must be between 0 and 100")
        self._noise_suppression_level = int(noise_suppression_level)

    async def run(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
        trailing_silence_seconds: float = 0.75,
    ) -> KrispCloudIsolationRun:
        if sample_rate != 48_000:
            raise ValueError("Krisp benchmark requires canonical 48 kHz PCM")
        if trailing_silence_seconds < 0:
            raise ValueError("trailing_silence_seconds must be non-negative")

        try:
            from livekit.plugins import krisp
        except ImportError as exc:
            raise KrispCloudIsolationUnavailable(
                "Krisp benchmark dependency is missing; install the "
                'optional extra with: pip install -e ".[krisp-benchmark]"'
            ) from exc

        url, api_key, api_secret = _require_cloud_environment()
        pcm = _as_pcm16_mono(samples)
        input_seconds = pcm.size / sample_rate
        room_name = f"jarvis-krisp-benchmark-{uuid.uuid4().hex[:12]}"
        publisher_identity = f"jarvis-krisp-pub-{uuid.uuid4().hex[:8]}"
        subscriber_identity = f"jarvis-krisp-sub-{uuid.uuid4().hex[:8]}"

        publisher_room = rtc.Room()
        subscriber_room = rtc.Room()
        remote_track_future: asyncio.Future[rtc.Track] = (
            asyncio.get_running_loop().create_future()
        )

        @subscriber_room.on("track_subscribed")
        def _on_track_subscribed(track, _publication, participant) -> None:
            if participant.identity != publisher_identity:
                return
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if not remote_track_future.done():
                remote_track_future.set_result(track)

        source: rtc.AudioSource | None = None
        stream: rtc.AudioStream | None = None
        reader_task: asyncio.Task[None] | None = None
        output_chunks: list[np.ndarray] = []

        async def _read_output() -> None:
            assert stream is not None
            async for event in stream:
                output_chunks.append(
                    np.frombuffer(event.frame.data, dtype=np.int16).copy()
                )

        started = time.perf_counter()
        try:
            subscriber_token = _room_token(
                api_key=api_key,
                api_secret=api_secret,
                room_name=room_name,
                identity=subscriber_identity,
            )
            publisher_token = _room_token(
                api_key=api_key,
                api_secret=api_secret,
                room_name=room_name,
                identity=publisher_identity,
            )
            await subscriber_room.connect(url, subscriber_token)
            await publisher_room.connect(url, publisher_token)

            source = rtc.AudioSource(sample_rate, 1, queue_size_ms=250)
            local_track = rtc.LocalAudioTrack.create_audio_track(
                "jarvis-krisp-benchmark-audio",
                source,
            )
            await publisher_room.local_participant.publish_track(
                local_track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
            remote_track = await asyncio.wait_for(remote_track_future, timeout=10.0)

            processor = krisp.voice_isolation(
                noise_suppression_level=self._noise_suppression_level
            )
            stream = rtc.AudioStream.from_track(
                track=remote_track,
                sample_rate=sample_rate,
                num_channels=1,
                frame_size_ms=10,
                noise_cancellation=processor,
                auto_close_noise_cancellation=True,
            )
            reader_task = asyncio.create_task(
                _read_output(),
                name="jarvis-krisp-benchmark-reader",
            )

            frame_samples = sample_rate // 100
            tail_samples = round(trailing_silence_seconds * sample_rate)
            replay = np.concatenate([pcm, np.zeros(tail_samples, dtype=np.int16)])
            for offset in range(0, replay.size, frame_samples):
                chunk = replay[offset : offset + frame_samples]
                if chunk.size < frame_samples:
                    chunk = np.pad(chunk, (0, frame_samples - chunk.size))
                frame = rtc.AudioFrame(
                    data=np.ascontiguousarray(chunk, dtype=np.int16).tobytes(),
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=frame_samples,
                )
                await source.capture_frame(frame)

            await source.wait_for_playout()
            expected_samples = replay.size
            deadline = time.monotonic() + 3.0
            while sum(chunk.size for chunk in output_chunks) < expected_samples:
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.02)
        finally:
            if stream is not None:
                await stream.aclose()
            if reader_task is not None:
                await asyncio.gather(reader_task, return_exceptions=True)
            if source is not None:
                await source.aclose()
            await publisher_room.disconnect()
            await subscriber_room.disconnect()

        wall_seconds = time.perf_counter() - started
        if not output_chunks:
            raise KrispCloudIsolationUnavailable(
                "Krisp Cloud room produced no isolated audio frames"
            )
        output = np.concatenate(output_chunks)
        if output.size < pcm.size:
            raise KrispCloudIsolationUnavailable(
                "Krisp output was shorter than benchmark input: "
                f"{output.size} < {pcm.size} samples"
            )
        output = np.ascontiguousarray(output[: pcm.size], dtype=np.int16)
        return KrispCloudIsolationRun(
            samples=output,
            sample_rate=sample_rate,
            wall_seconds=wall_seconds,
            input_seconds=input_seconds,
            output_seconds=output.size / sample_rate,
            room_name=room_name,
        )
