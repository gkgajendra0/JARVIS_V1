"""Live acceptance runner for Pocket 3 native OWNER reacquisition."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from jarvis.identity.owner_context import build_default_owner_context_observer
from jarvis.identity.owner_evidence import OwnerIdentityThresholds
from jarvis.identity.passive_liveness import PassiveLivenessThresholds
from jarvis.logging_config import configure_logging
from jarvis.vision.camera import OpenCVCameraConfig, OpenCVCameraSource
from jarvis.vision.native_owner_tracking import (
    build_default_native_owner_tracking_observer,
)
from jarvis.vision.service import build_default_vision_service

LOGGER = logging.getLogger(__name__)

_TRACKING_EVIDENCE_WINDOW = 5
_SEARCHING_PERCEPTION_FPS = 10.0
_LOCKED_PERCEPTION_FPS = 1.0
_OPENCV_THREADS = 1


def run_native_owner_tracking_live(
    *,
    camera_index: int = 0,
    ble_name: str = "OsmoPocket3-C36F",
    head_model_path: str | Path | None = None,
    preview: bool = True,
) -> int:
    if sys.platform != "win32":
        print("Pocket 3 native OWNER tracking acceptance currently requires Windows.")
        return 2
    if camera_index < 0:
        raise ValueError("camera_index must be non-negative")

    configure_logging("INFO")
    if preview:
        os.environ["JARVIS_VISION_PREVIEW"] = "true"
    else:
        os.environ["JARVIS_VISION_PREVIEW"] = "false"

    print("JARVIS Pocket 3 native OWNER reacquisition acceptance")
    print("----------------------------------------------------")
    print(f"USB camera index: {camera_index}")
    print(f"Pocket BLE name: {ble_name}")
    print("Software PTZ: SAFE / not armed")
    print(
        "Adaptive perception: "
        f"{_SEARCHING_PERCEPTION_FPS:.1f} FPS searching/reacquiring -> "
        f"{_LOCKED_PERCEPTION_FPS:.1f} FPS while native lock is healthy"
    )
    print(f"OpenCV threads: {_OPENCV_THREADS}")
    print(f"Tracking-only OWNER evidence window: {_TRACKING_EVIDENCE_WINDOW} samples")
    print("Expected flow:")
    print("  1. JARVIS recognizes live OWNER and sends one A6.")
    print(
        "  2. Pocket 3 native ActiveTrack follows OWNER; JARVIS throttles perception."
    )
    print("  3. OWNER leaves the frame; JARVIS ramps perception back up and recenters.")
    print("  4. OWNER returns; JARVIS sends a fresh A6 and Pocket relocks.")
    print("Press Ctrl+C after the leave-and-return scenario is complete.")
    print()

    owner_observer = build_default_owner_context_observer(
        identity_thresholds=OwnerIdentityThresholds(
            window_size=_TRACKING_EVIDENCE_WINDOW
        ),
        liveness_thresholds=PassiveLivenessThresholds(
            window_size=_TRACKING_EVIDENCE_WINDOW
        ),
    )
    tracking_observer = build_default_native_owner_tracking_observer(
        owner_context=owner_observer.state,
        ble_name=ble_name,
        searching_perception_fps=_SEARCHING_PERCEPTION_FPS,
        locked_perception_fps=_LOCKED_PERCEPTION_FPS,
    )
    camera = OpenCVCameraSource(
        OpenCVCameraConfig(
            device_index=camera_index,
            width=1280,
            height=720,
            backend="dshow",
        )
    )
    service = build_default_vision_service(
        head_model_path=head_model_path,
        evidence_observer=owner_observer,
        tracking_observer=tracking_observer,
        camera_source=camera,
        perception_fps=_SEARCHING_PERCEPTION_FPS,
        perception_fps_provider=tracking_observer.perception_fps_hint,
        opencv_threads=_OPENCV_THREADS,
    )

    try:
        service.start()
        while service.running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        LOGGER.info("Pocket 3 native OWNER tracking acceptance stopped by operator")
    finally:
        if service.running:
            service.stop()

    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run JARVIS Pocket 3 native OWNER reacquisition acceptance."
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV/DirectShow camera index for the Pocket 3 USB webcam.",
    )
    parser.add_argument(
        "--ble-name",
        default="OsmoPocket3-C36F",
        help="Pocket 3 BLE device name.",
    )
    parser.add_argument(
        "--head-model-path",
        default=None,
        help="Optional BlazeFace model path override.",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Disable the OpenCV vision preview window.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    return run_native_owner_tracking_live(
        camera_index=args.camera_index,
        ble_name=args.ble_name,
        head_model_path=args.head_model_path,
        preview=not args.no_preview,
    )


if __name__ == "__main__":
    raise SystemExit(main())
