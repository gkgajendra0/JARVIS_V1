"""Windows-local deterministic status speech for cloud-provider failures.

This path intentionally avoids Gemini/OpenAI. It synthesizes a fixed JARVIS-owned
status sentence with Windows System.Speech into a temporary PCM WAV and then plays
that WAV through JARVIS's already-selected LiveKit audio output.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shutil
import sys
import tempfile
import wave
from pathlib import Path
from typing import Protocol

from livekit import rtc
from livekit.agents.voice import io

LOGGER = logging.getLogger(__name__)

_LOCAL_STATUS_SAMPLE_RATE = 24_000
_LOCAL_STATUS_FRAME_MS = 20
_LOCAL_STATUS_SYNTH_TIMEOUT_SECONDS = 10.0
_LOCAL_STATUS_PLAYBACK_TIMEOUT_SECONDS = 20.0


class LocalStatusSpeech(Protocol):
    async def speak(self, output: io.AudioOutput, text: str) -> None: ...


class WindowsLocalStatusSpeech:
    """Synthesize fixed status text locally with Windows System.Speech."""

    def __init__(
        self,
        *,
        synth_timeout_seconds: float = _LOCAL_STATUS_SYNTH_TIMEOUT_SECONDS,
        playback_timeout_seconds: float = _LOCAL_STATUS_PLAYBACK_TIMEOUT_SECONDS,
    ) -> None:
        if synth_timeout_seconds <= 0 or playback_timeout_seconds <= 0:
            raise ValueError("local status speech timeouts must be positive")
        self._synth_timeout_seconds = synth_timeout_seconds
        self._playback_timeout_seconds = playback_timeout_seconds

    async def _synthesize_to_wave(self, path: Path, text: str) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell is None:
            raise RuntimeError("Windows PowerShell is unavailable for local status speech")

        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        path_b64 = base64.b64encode(str(path).encode("utf-8")).decode("ascii")
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}'))
$path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{path_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        {_LOCAL_STATUS_SAMPLE_RATE},
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $synth.Rate = -1
    $synth.SetOutputToWaveFile($path, $format)
    $synth.Speak($text)
    $synth.SetOutputToNull()
}} finally {{
    $synth.Dispose()
}}
""".strip()
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        process = await asyncio.create_subprocess_exec(
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._synth_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError("Windows local status speech synthesis timed out") from None
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Windows local status speech synthesis failed"
                + (f": {detail}" if detail else "")
            )

    async def _play_wave(self, output: io.AudioOutput, path: Path) -> None:
        playback_finished = asyncio.get_running_loop().create_future()

        def on_playback_finished(event: object) -> None:
            del event
            if not playback_finished.done():
                playback_finished.set_result(None)

        output.on("playback_finished", on_playback_finished)
        try:
            with wave.open(str(path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                if channels != 1 or sample_width != 2 or sample_rate <= 0:
                    raise RuntimeError(
                        "Windows local status speech produced unsupported WAV format"
                    )
                samples_per_frame = max(
                    1, sample_rate * _LOCAL_STATUS_FRAME_MS // 1000
                )
                while True:
                    data = wav_file.readframes(samples_per_frame)
                    if not data:
                        break
                    samples = len(data) // 2
                    await output.capture_frame(
                        rtc.AudioFrame(
                            data=data,
                            sample_rate=sample_rate,
                            num_channels=1,
                            samples_per_channel=samples,
                        )
                    )
            output.flush()
            await asyncio.wait_for(
                playback_finished,
                timeout=self._playback_timeout_seconds,
            )
        finally:
            output.off("playback_finished", on_playback_finished)

    async def speak(self, output: io.AudioOutput, text: str) -> None:
        script = text.strip()
        if not script:
            raise ValueError("local status speech text must not be empty")

        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                path = Path(handle.name)
            await self._synthesize_to_wave(path, script)
            await self._play_wave(output, path)
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.warning(
                        "Temporary local status WAV could not be removed: %s", path
                    )


def build_local_status_speech() -> LocalStatusSpeech | None:
    """Return the zero-cloud Windows status speaker on the production OS."""

    if sys.platform != "win32":
        return None
    return WindowsLocalStatusSpeech()
