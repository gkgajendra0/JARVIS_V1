# JARVIS V1 Current Architecture

This document describes implemented, validated, and human-accepted architecture only.

## Accepted Product Slices

- Step 0 — Clean Foundation: accepted.
- Step 1 — Natural Conversational Core: accepted on 2026-08-28.
- Step 2 — Wake, Voice Session, and Audio Robustness: accepted on 2026-08-29.
- Step 2.5 — Vision Sensor & Active Target Tracking Foundation: accepted on 2026-08-29 and merged to `main`.
- Development supervisor (`jarvis-dev`) — accepted on 2026-08-30 and merged to protected `main`.

Step 3 identity/trust/authority/observability is active planning/research and is **not** current architecture yet.

## Runtime Entry Points

- `python -m jarvis` runs the minimal non-voice foundation lifecycle.
- `jarvis-voice` runs the accepted voice runtime and, when enabled, the integrated Step-2.5 vision runtime.
- `jarvis-dev` runs the accepted development supervisor around `jarvis-voice`; it watches protected `origin/main` by default and remains development tooling rather than normal user-facing authority.
- `lk agent console src/jarvis/voice/entrypoint.py` remains a diagnostic harness rather than the normal background runtime.
- `JARVIS_VISION_ENABLED=true` enables integrated vision.
- `JARVIS_VISION_PREVIEW=true` enables the optional live observer window without opening a second camera pipeline.

## Development Supervisor

`src/jarvis/dev_supervisor.py` is a long-running parent process used only for the development workflow.

```text
protected origin/main
        |
        v
   jarvis-dev parent
        |
        +--> fetch + fast-forward check
        |
        +--> fixed scripted-TTS update question
        |         |
        |         v
        |    finalized spoken transcript
        |         |
        |         v
        |   deterministic Yes/No parser
        |         |
        |     explicit Yes only
        |         |
        +---------+
        |
        v
clean child shutdown
        |
        v
ff-only Git update
        |
        v
restart jarvis-voice
        |
        v
authenticated readiness handshake
        |
        +--> healthy: keep update
        |
        \--> unhealthy: restore previous SHA and restart last-known-good
```

### Development authority boundary

The realtime model does not decide whether a software update is approved. A fixed scripted-TTS adapter speaks the update question, the realtime voice path supplies finalized transcription, and deterministic JARVIS code parses explicit approval. Ambiguous speech, timeout, contradictory wording, or unavailable approval means No.

Until Step 3 provides verified identity, spoken update approval is a development-owner interaction gate rather than strong biometric authentication. The control channel is loopback-only and authenticated with a parent-generated token.

### Git/update safety

The supervisor:

- refuses dirty working trees and wrong branches;
- watches `origin/main` by default;
- fetches without changing the running repository;
- refuses non-fast-forward updates;
- never pulls/restarts before explicit approval;
- requests clean in-process shutdown before OS-level fallback;
- uses `git pull --ff-only` for approved updates;
- verifies the restarted child reaches the authenticated control-channel readiness point;
- restores the previous local SHA and restarts it if the updated child fails readiness;
- does not enter an automatic crash-restart loop.

Repository `main` is protected by the active `Main safety gate` ruleset. Changes require PR flow, strict required status checks `ruff` and `pytest`, deletion protection, non-fast-forward protection, and no bypass actors.

The parent supervisor intentionally does not replace its own running Python process during a child update. Supervisor-code changes take effect after the parent itself is restarted.

## Voice Runtime

1. JARVIS opens one 48 kHz mono input stream and the selected output device.
2. While idle, microphone PCM stays local and feeds the wake detector through a controlled 16 kHz inference stream.
3. A threshold/debounce policy accepts one wake event and disables further wake scoring during activation and conversation.
4. Buffered wake-tail/pre-roll followed by live PCM enters one selected realtime-provider session.
5. LiveKit/provider events are translated into canonical conversation state.
6. Explicit exit, inactivity, cancellation, or recoverable provider failure closes the active session and returns to local wake detection.

No realtime provider session is required while JARVIS is idle.

## Vision Runtime

```text
DJI Pocket 3
    |
    v
OpenCV DirectShow CameraSource
(latest-frame overwrite, 1280x720)
    |
    +--> MediaPipe BlazeFace Full-Range --> HeadObservation[]
    |
    +--> RF-DETR Nano BF16 --> Detection[] --> OC-SORT + DIoU --> Track[]
                                                |
                                          TargetManager
                                                |
                                   Head-first framing policy
                                                |
                              FollowController + ZoomController
                                                |
                                   duvc-ctl PtzController
                                                |
                                         Pocket 3 gimbal

VisionSnapshot --> diagnostics --> voice tools
             \--> optional live observer window
```

### Capture ownership

`src/jarvis/vision/camera.py` owns the physical camera stream. The accepted Pocket 3 path uses OpenCV DirectShow, one camera owner, and an overwrite-slot latest-frame design rather than an accumulating queue. Controlled hardware testing sustained approximately 29.34 FPS at 1280x720.

### Person detection

`src/jarvis/vision/detector.py` adapts RF-DETR Nano into JARVIS-owned normalized `Detection` values. Native PyTorch/CUDA BF16 is the accepted initial inference path. Detector candidate count is engineering telemetry and is not canonical visible-person truth.

### Person tracking

`src/jarvis/vision/tracker.py` owns the provider-neutral `Tracker` boundary and adapters for mature Roboflow tracking implementations.

The accepted production default is OC-SORT with DIoU association and XYXY state estimation because live testing showed fast sitting/standing motion could produce large inter-analysis box jumps. Human validation confirmed the same track ID survived repeated fast sit/stand motion after this change. BoT-SORT and ByteTrack remain replaceable fallback adapters behind the same JARVIS contract.

Tracker historical first-seen bookkeeping is time-bounded for long-running operation.

### Head-first framing

MediaPipe BlazeFace Full-Range supplies head evidence. Initial lock eligibility requires three consecutive linked-head frames. Once a target is locked:

- `HEAD` is the primary pan/tilt framing anchor;
- `HEAD_HOLD` briefly preserves trusted head height while the same body track supplies horizontal continuity;
- `BODY` uses only the already locked body track with reduced-authority vertical control;
- disappearance does not permit automatic target switching.

Head evidence is not identity or authorization.

### Target ownership and safety

`TargetManager` owns exactly one explicitly selected track. Lock and arm are separate actions. Follow begins disarmed, missing target state produces no motion, target expiry clears selection and disarms follow, and a newly created unrelated track is never silently substituted for the selected target.

### PTZ and adaptive zoom

`src/jarvis/vision/ptz.py` adapts `duvc-ctl` Pocket 3 camera-control properties behind JARVIS-owned movement semantics. Pan, tilt, and zoom ranges are queried as hardware device units rather than assumed degrees.

The accepted follow path includes calibrated Pocket 3 tilt polarity, direction-specific pan scaling, bounded command cadence, and adaptive zoom. Zoom is derived from the already locked body track's apparent size, uses hysteresis and a conservative hardware range cap, and cannot select or change a target.

### Live observer

`src/jarvis/vision/observer.py` provides an optional small OpenCV observer window. It does not own the camera or run a second detector/tracker. It displays the latest camera frame together with the most recent canonical interpretation: track boxes/IDs, head boxes, selected target, framing source, pan/tilt/zoom command, follow state, and interpretation age.

Display refresh is decoupled from inference refresh so a smooth camera feed does not imply the perception model itself runs at camera FPS.

## Canonical Conversation and Voice Components

`src/jarvis/conversation.py` owns provider-independent session lifecycle and accepted user/assistant turns. Provider history is operational state rather than canonical JARVIS truth.

`src/jarvis/voice/wakeword.py` adapts the local LiveKit WakeWord model and receives PCM from the JARVIS audio owner rather than owning a microphone.

`src/jarvis/voice/audio.py` owns physical microphone/speaker lifecycle, routing, AEC/noise-processing, activation pre-roll, and bounded queues.

`src/jarvis/voice/runtime.py` owns idle/activation/active/recovery transitions, starts/stops the integrated vision service safely when enabled, and exposes the authenticated development-control client only when launched by `jarvis-dev`.

`src/jarvis/voice/livekit_session.py` constructs the selected Gemini or OpenAI realtime provider and maps provider events into JARVIS state.

`src/jarvis/voice/scripted_speech.py` owns fixed scripted speech for development update prompts behind a replaceable TTS boundary. This avoids using realtime-model generation as the authorization prompt source.

`src/jarvis/voice/agent.py` owns JARVIS voice identity, language behavior, and capability-truthfulness constraints.

`src/jarvis/voice/vision_tools.py` exposes only bounded inspection and explicit vision control actions. Voice-facing visible-person count comes from canonical tracks rather than raw detector candidates.

`src/jarvis/dev_control.py` owns the narrow authenticated loopback protocol between the development supervisor and voice runtime, including update-approval and shutdown/readiness messages plus deterministic spoken approval parsing.

## Authoritative State

| State | Owner |
| --- | --- |
| Foundation lifecycle | `JarvisApp` |
| Environment configuration | `JarvisConfig` |
| Physical microphone/speaker | JARVIS local audio runtime |
| Wake inference | `WakeDetector` implementation |
| Wake/idle/active/recovery lifecycle | `VoiceRuntimeController` |
| Canonical accepted conversation | `ConversationSession` |
| Camera capture | `CameraSource` implementation |
| Person detections | `ObjectDetector` adapter -> canonical `Detection` |
| Person tracks | `Tracker` adapter -> canonical `Track` |
| Selected visual target | `TargetManager` |
| Head/body framing semantics | JARVIS framing policy |
| Follow/zoom movement intent | JARVIS follow/zoom controllers |
| Pocket 3 hardware movement | `PtzController` adapter |
| Vision diagnostics/observer | JARVIS vision service |
| Development update detection/restart/rollback | `jarvis-dev` supervisor |
| Development update approval interpretation | deterministic JARVIS parser in `dev_control.py` |
| Development update distribution gate | protected GitHub `main` + required `ruff`/`pytest` checks |
| Human identity, trust, permissions | Not implemented; Step 3 |

## External Dependencies

Core accepted dependencies include:

- Python 3.11 or newer;
- Git and GitHub for the development supervisor workflow;
- `livekit==1.1.15`;
- `livekit-agents[google,openai]==1.7.1`;
- `livekit-wakeword==0.2.1`;
- OpenCV 5.0.0.93;
- PyTorch / torchvision CUDA runtime used by RF-DETR;
- `rfdetr==1.9.4`;
- `trackers==2.6.0`;
- `mediapipe==1.0.1`;
- `duvc-ctl==2.1.0` on Windows;
- one selected realtime-provider account/key;
- local wake-word and BlazeFace model assets outside the repository.

## Validation and Human Evidence

Protected `main` requires PR flow with strict `ruff` and `pytest` status checks. Step-specific hardware/human validation remains required where CI cannot prove the behavior.

Real Windows + RTX 5060 Ti + DJI Pocket 3 use has established:

- stable DirectShow capture and physical Pocket 3 PTZ control;
- RF-DETR Nano CUDA inference;
- stable canonical tracking under ordinary movement;
- safe HEAD -> HEAD_HOLD -> BODY -> HEAD framing degradation/recovery;
- explicit lock and separate arm behavior;
- real pan/tilt/adaptive-zoom follow behavior;
- target-loss stop/disarm semantics without intentional person switching;
- truthful voice reporting based on canonical track state;
- integrated observer sharing the same runtime state;
- fast sit/stand motion preserving one OC-SORT track ID;
- explicit owner confirmation that Step 2.5 is working well with no remaining blocking functional issue;
- `jarvis-dev` detecting a remote update, speaking the approval question, accepting explicit spoken approval outside model authority, shutting JARVIS down cleanly, applying a fast-forward update, restarting voice/vision, and returning to wake mode without a shutdown timeout;
- the final supervisor running on `main` while watching `origin/main` in default mode.

Automated supervisor tests cover configuration safety, deterministic approval parsing, update readiness, and last-known-good rollback behavior. GitHub CI runs both Ruff and pytest on clean Ubuntu runners.

Earlier long endurance matrices from Step 2 remain waived and must not be represented as exhaustively validated.

## Current Limitations

- perception updates are slower than raw camera capture; observer `analysis age` exposes that distinction;
- no tracker can guarantee continuity through complete disappearance or arbitrary long occlusion;
- head/person observations do not identify a human;
- no face recognition, liveness/anti-spoofing, voice identity, trust score, or user-facing authorization layer exists yet;
- spoken development-update approval is not identity-verified until Step 3 provides stronger identity/trust evidence;
- the realtime approval session can still emit provider-side/internal assistant-response noise even though that model output is not routed as approval authority;
- the running `jarvis-dev` parent must be restarted to load changes to supervisor code itself;
- no general scene understanding, OCR, gesture understanding, or visual memory exists yet;
- provider/network/cost/privacy constraints still apply to realtime conversation;
- JARVIS is not yet installed as a production background Windows service.

## Architecture Update Rule

Step 3 identity/trust/authority architecture may be added here only after research, recorded decisions, human approval, implementation, automated validation, and real human acceptance. Vision, wake word, face recognition, voice recognition, model confidence, or any other sensor evidence must never directly grant permission.
