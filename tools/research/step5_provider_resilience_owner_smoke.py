"""Owner-machine smoke for Step-5 zero-cloud provider-failure speech.

This is acceptance scaffolding only. It does not call Gemini/OpenAI and does not
simulate a successful cloud operation. It verifies that the production Windows-local
status path can synthesize and play the bounded quota message through JARVIS's
configured conversation output device.
"""

from __future__ import annotations

import asyncio
import sys

from livekit import rtc

from jarvis.config import JarvisConfig
from jarvis.provider_resilience import ProviderFailure, ProviderFailureKind
from jarvis.voice.audio import DEVICE_CHANNELS, DEVICE_SAMPLE_RATE, FRAME_SAMPLES
from jarvis.voice.local_status_speech import WindowsLocalStatusSpeech
from jarvis.voice.media_devices_audio import (
    MediaDevicesAudioOutput,
    MediaDevicesConversationRuntime,
)


async def _run() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Step-5 owner smoke requires Windows")

    config = JarvisConfig.from_environment()
    if config.audio_output_device is None:
        raise RuntimeError("JARVIS_AUDIO_OUTPUT_DEVICE is not configured")

    media_devices = rtc.MediaDevices(
        input_sample_rate=DEVICE_SAMPLE_RATE,
        output_sample_rate=DEVICE_SAMPLE_RATE,
        num_channels=DEVICE_CHANNELS,
        blocksize=FRAME_SAMPLES,
    )
    outputs = MediaDevicesConversationRuntime._attach_host_api_names(
        media_devices.list_output_devices()
    )
    output_device = MediaDevicesConversationRuntime._resolve_device(
        outputs,
        config.audio_output_device,
        kind="output",
    )
    MediaDevicesConversationRuntime._require_48k_output(output_device)
    selected = next(
        item for item in outputs if int(item["index"]) == int(output_device)
    )
    print(f"STEP5_SMOKE_OUTPUT: {selected['name']} @ {DEVICE_SAMPLE_RATE} Hz")

    output = MediaDevicesAudioOutput(
        media_devices,
        output_device=output_device,
    )
    await output.start()
    try:
        failure = ProviderFailure(
            provider=config.ai_provider,
            kind=ProviderFailureKind.QUOTA_EXHAUSTED,
            status_code=429,
            retryable=False,
        )
        print(f"STEP5_SMOKE_MESSAGE: {failure.spoken_message}")
        await WindowsLocalStatusSpeech().speak(output, failure.spoken_message)
    finally:
        await output.aclose()

    print("STEP5_SMOKE_STATUS: PASS")


def main() -> int:
    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - owner smoke must report boundary failure
        print(f"STEP5_SMOKE_STATUS: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
