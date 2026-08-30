# JARVIS V1 Current Architecture

This document describes implemented, validated, human-accepted, and merged architecture only.

## Accepted Product Slices

- Step 0 — Clean Foundation: accepted.
- Step 1 — Natural Conversational Core: accepted on 2026-08-28.
- Step 2 — Wake, Voice Session, and Audio Robustness: accepted on 2026-08-29.
- Step 2.5 — Vision Sensor & Active Target Tracking Foundation: accepted on 2026-08-29 and merged to `main`.
- Development supervisor (`jarvis-dev`) — accepted on 2026-08-30 and merged to protected `main`.
- Time-aware startup greeting interaction — accepted on 2026-08-30.
- Step 3A — Deterministic Authority Foundation + Windows strong verification/session invalidation: accepted on 2026-08-30 and merged to protected `main` through PR #7 (`6651de01d0c4ae81a25480ef26d2399181cee870`).

Step 3 is not complete. Owner biometric identity, liveness, attention-provider integration, speaker identity, and full T0/T1/T2 trust derivation remain future Step-3 slices.

## Runtime Entry Points

- `python -m jarvis` runs the minimal non-voice foundation lifecycle.
- `jarvis-voice` runs the accepted voice runtime and, when enabled, the integrated Step-2.5 vision runtime.
- `jarvis-dev` runs the accepted development supervisor around `jarvis-voice`; it watches protected `origin/main` by default and remains development tooling rather than normal user-facing authority.
- `lk agent console src/jarvis/voice/entrypoint.py` remains a diagnostic harness rather than the normal background runtime.
- `JARVIS_VISION_ENABLED=true` enables integrated vision.
- `JARVIS_VISION_PREVIEW=true` enables the optional live observer window without opening a second camera pipeline.
- `JARVIS_STARTUP_GREETING=true` is the default and enables one time-aware greeting per voice-runtime start; set it to `false` to disable the greeting without changing the rest of startup.

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

The development supervisor remains separate from the Step-3 authority runtime. Step 3A adds the reusable user-facing authority foundation; the supervisor does not silently inherit stronger identity semantics until explicitly integrated in a later accepted slice.

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

## Authority Foundation — Step 3A

Step 3A owns deterministic action authority before biometric providers are allowed to influence protected decisions.

```text
Action request
    |
    v
immutable ActionProposal
(canonical material + fingerprint + expiry + session binding)
    |
    v
RiskClassifier hard floor
    |
    +--> R5 RESTRICTED_DEV_ONLY -> deny normal runtime
    |
    v
PolicyEngine (OPA adapter available, fail closed)
    |
    v
Approval requirement + trust requirement + obligations
    |
    +--> direct / explicit approval paths
    |
    +--> R4 strong path
             |
             v
      StrongApprovalService
             |
             v
      StrongVerifier
      (Windows Hello v1)
             |
      VERIFIED only
             |
             v
 proposal/session-bound one-time STRONG approval
    |
    v
AuthorityService
    |
    +--> audit-before-protected-execution
    |
    v
short-lived ExecutionPermit
    |
    v
final pre-execution revalidation
    |
    v
consume approval + permit exactly once
```

### Canonical authority types

`src/jarvis/authority/types.py` owns the accepted deterministic vocabulary:

- trust tiers T0 `UNVERIFIED`, T1 `PRESENT_CONTEXT`, T2 `CORROBORATED_OWNER`, T3 `VERIFIED_OWNER`;
- risk classes R0 `ROUTINE`, R1 `PRIVATE_READ`, R2 `REVERSIBLE_LOCAL_CHANGE`, R3 `PERSISTENT_OR_EXTERNAL`, R4 `CRITICAL`, R5 `RESTRICTED_DEV_ONLY`;
- approval requirements `NONE`, `DIRECT_INTENT`, `EXPLICIT`, `STRONG`;
- attention states and typed evidence modalities.

Model/provider confidence cannot directly set these authority states.

### Exact-action proposals

`src/jarvis/authority/proposal.py` owns immutable `ActionProposal` creation and validation. Material target/parameter content is canonicalized before SHA-256 fingerprinting. Proposal IDs, sessions, expiry, action origin, and risk-relevant attributes remain explicit. Unicode-normalized-key collisions are rejected, and the fingerprint is recomputed at authority boundaries so object mutation cannot silently preserve an old approval.

A material parameter or target change requires a different proposal fingerprint and therefore a new approval.

### Risk hard floors

`src/jarvis/authority/risk.py` owns deterministic risk classification. Policy may add friction but cannot reduce the JARVIS hard floor. Critical security/financial/legal/destructive classes cannot be downgraded by model output or policy configuration.

### Approval state

`src/jarvis/authority/approval.py` owns pending/granted/denied/canceled/expired/consumed approval state. Approvals bind to proposal ID, proposal fingerprint, and authority session; expire; are invalidated with the session; and are one-time at execution.

The generic grant API is prohibited from claiming `STRONG_VERIFIER`. Strong approval requires a bound `StrongVerificationResult` with a unique verification ID. A successful strong proof can be consumed only once and cannot mint multiple strong approvals.

### Strong verification

`src/jarvis/authority/verifier.py` defines the replaceable `StrongVerifier` boundary and the accepted Windows Hello adapter. The Windows implementation invokes a small .NET 9 desktop helper under `tools/windows/Jarvis.WindowsHelloVerifier`.

The helper uses the desktop `UserConsentVerifierInterop.RequestVerificationForWindowAsync` route with a real WinForms message loop and an application-owned HWND. Its stdout contract is lowercase JSON and is executed/validated by Windows CI.

A `StrongVerificationResult` contains:

- status;
- verifier ID;
- unique verification ID;
- exact proposal fingerprint;
- exact authority session ID;
- reason codes.

`src/jarvis/authority/strong_approval.py` owns the only accepted bridge from strong verification to a STRONG approval. `VERIFIED` may grant one matching pending strong approval. Cancel/unavailable/error/mismatch fails closed and cannot fall back to voice, face, attention, or generic explicit approval.

Windows Hello/PIN verification is platform strong verification; JARVIS receives only the verification result, not the PIN or biometric secret.

### Windows session boundary

`src/jarvis/authority/session.py` owns authority-session state and the Windows WTS provider/guard. The Windows adapter uses `WTSSessionInfoEx` explicit session lock state rather than assuming that a logged-on session is safe.

Lock, user/session transition, disconnect/logoff, or other invalidation events cancel active authority state and permits for that JARVIS authority session.

Windows session state is contextual evidence only; an unlocked desktop does not prove that the person in front of the camera/microphone is the OWNER.

### Policy boundary

`src/jarvis/authority/policy.py` owns the JARVIS `PolicyEngine` contract and fail-closed OPA adapter. OPA traffic is restricted to loopback, response shape is strict, and expected policy version is validated. Policy-engine failure, malformed output, unavailable policy, or version mismatch does not authorize protected actions.

### Authority service and execution permit

`src/jarvis/authority/service.py` combines risk hard floors, policy requirements, trust/attention/actor predicates, and bound approval state. Required audit happens before protected execution permission is issued.

`src/jarvis/authority/permit.py` owns short-lived execution permits. Immediately before an executor may act, `AuthorityService.revalidate_and_consume()` checks proposal/session/fingerprint/risk/policy/approval bindings again. Successful execution authorization consumes the permit and approval exactly once. Mutation, expiry, replay, session change, audit failure, or changed authority state invalidates execution.

Step 3A does not yet implement the later generic Step-7 executor. It defines the governance contract that future executors must require.

### Audit boundary

`src/jarvis/authority/audit.py` owns structured security/authority audit events plus in-memory and SQLite implementations. Sensitive metadata-key classes such as biometric embeddings and access tokens are rejected rather than casually logged.

Operational telemetry is not the authority audit source of truth.

### Attention contract only

Step 3A establishes the typed attention evidence/authority predicate boundary but does not yet integrate a gaze/eye model into accepted runtime authority. Face/liveness/attention evidence remains non-authoritative until its later Step-3 slice is implemented and human-accepted.

## Voice Runtime

1. JARVIS opens one 48 kHz mono input stream and the selected output device.
2. When enabled, JARVIS selects one deterministic startup line from a local time-of-day phrase pool and speaks it through the scripted-TTS adapter. Selection is random within the applicable pool, happens once per voice-runtime start, and greeting failure is non-fatal.
3. While idle, microphone PCM stays local and feeds the wake detector through a controlled 16 kHz inference stream.
4. A threshold/debounce policy accepts one wake event and disables further wake scoring during activation and conversation.
5. Buffered wake-tail/pre-roll followed by live PCM enters one selected realtime-provider session.
6. LiveKit/provider events are translated into canonical conversation state.
7. Explicit exit, inactivity, cancellation, or recoverable provider failure closes the active session and returns to local wake detection.

No realtime provider session is required while JARVIS is idle. Startup greeting text is selected by JARVIS code rather than generated by the realtime conversational model.

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

`src/jarvis/voice/runtime.py` owns startup greeting, idle/activation/active/recovery transitions, starts/stops the integrated vision service safely when enabled, and exposes the authenticated development-control client only when launched by `jarvis-dev`.

`src/jarvis/voice/startup_greeting.py` owns the local time-of-day greeting pools and random selection semantics. It chooses text only; playback remains behind the shared scripted-speech boundary.

`src/jarvis/voice/livekit_session.py` constructs the selected Gemini or OpenAI realtime provider and maps provider events into JARVIS state.

`src/jarvis/voice/scripted_speech.py` owns deterministic system speech such as startup greetings and development update prompts behind a replaceable TTS boundary. This keeps fixed JARVIS-owned messages separate from realtime-model generation.

`src/jarvis/voice/agent.py` owns JARVIS voice identity, language behavior, and capability-truthfulness constraints.

`src/jarvis/voice/vision_tools.py` exposes only bounded inspection and explicit vision control actions. Voice-facing visible-person count comes from canonical tracks rather than raw detector candidates.

`src/jarvis/dev_control.py` owns the narrow authenticated loopback protocol between the development supervisor and voice runtime, including update-approval and shutdown/readiness messages plus deterministic spoken approval parsing.

## Authoritative State

| State | Owner |
| --- | --- |
| Foundation lifecycle | `JarvisApp` |
| Environment configuration | `JarvisConfig` |
| Physical microphone/speaker | JARVIS local audio runtime |
| Startup greeting text selection | `startup_greeting.py` |
| Deterministic system speech playback | `ScriptedSpeech` adapter |
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
| Action proposal/fingerprint | `ActionProposal` |
| Deterministic risk floor | `RiskClassifier` |
| Policy evaluation boundary | JARVIS `PolicyEngine` / fail-closed OPA adapter |
| Approval lifecycle | `ApprovalService` |
| Strong verification -> strong approval bridge | `StrongApprovalService` |
| Platform strong verification | `StrongVerifier`; Windows Hello adapter v1 |
| Authority decision/pre-execution revalidation | `AuthorityService` |
| Execution authorization receipt | `PermitRegistry` / `ExecutionPermit` |
| Authority security audit | `AuditEventStore` |
| Windows authority-session validity | `WindowsWtsSessionProvider` + `WindowsSessionGuard` |
| Persistent OWNER biometric identity | Not implemented; Step 3B |
| Face/liveness/attention/speaker-derived trust | Not implemented; later Step 3 |

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
- .NET 9 SDK/runtime to build/run the accepted Windows Hello desktop helper during development;
- optional local OPA runtime when the OPA `PolicyEngine` adapter is selected;
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
- the final supervisor running on `main` while watching `origin/main` in default mode;
- a real startup on the feature branch speaking the randomly selected late-night line `Online and ready, sir.` and then entering local wake detection normally;
- Windows WTS reporting the active session unlocked;
- `Win+L` producing authority invalidation for that session;
- Windows Hello/PIN returning a real `VERIFIED` strong-verification result;
- proposal/session-bound strong proof producing a STRONG approval and R4 `ALLOW`;
- the execution permit and approval being consumed exactly once at final revalidation;
- a real canceled Windows Hello verification producing canceled approval, authority `DENY`, `permit=None`, and no execution permission.

Automated authority tests cover proposal canonicalization/integrity, Unicode collision rejection, risk hard floors, direct/spoken/strong approval semantics, attention-bound spoken approval, strong-proof binding and replay protection, policy failure/version validation, loopback restriction, audit failure, proposal/permit expiry, session invalidation, TOCTOU mutation, and one-time permit/approval consumption. Windows CI compiles the .NET 9 helper and executes its JSON contract probe. GitHub CI also runs Ruff and the complete pytest suite on clean runners.

Earlier long endurance matrices from Step 2 remain waived and must not be represented as exhaustively validated.

## Current Limitations

- Step 3A governs authority but is not yet wired into broad user-facing capability execution; the Step-7 generic executor does not exist yet;
- no persistent OWNER biometric profile or encrypted face-template store is accepted yet;
- no face recognition, face liveness/anti-spoofing, gaze/attention model, speaker identity, or active-speaker association is accepted yet;
- T2/T3 vocabulary exists, but ambient biometric trust derivation is not yet implemented; T3 in Phase 3A is supplied only in bounded strong-verification test/context paths rather than inferred from face/voice;
- Windows Hello Face is not required by JARVIS; the accepted strong path can use Windows Hello PIN, while Pocket 3 remains ordinary RGB evidence rather than a Hello/TrueDepth-class authenticator;
- perception updates are slower than raw camera capture; observer `analysis age` exposes that distinction;
- no tracker can guarantee continuity through complete disappearance or arbitrary long occlusion;
- head/person observations do not identify a human;
- startup greetings are time-aware but not identity-aware; greeting text must not imply verified owner recognition;
- spoken development-update approval is still a development-tool interaction gate and is not automatically upgraded to the Step-3 strong-authority flow;
- the realtime approval session can still emit provider-side/internal assistant-response noise even though that model output is not routed as approval authority;
- the running `jarvis-dev` parent must be restarted to load changes to supervisor code itself;
- no general scene understanding, OCR, gesture understanding, or visual memory exists yet;
- provider/network/cost/privacy constraints still apply to realtime conversation;
- JARVIS is not yet installed as a production background Windows service.

## Architecture Update Rule

Only Step-3 slices that have completed research/decision, implementation, automated validation, real human acceptance, documentation reconciliation, and protected-main merge may appear here as current architecture. Vision, wake word, face recognition, voice recognition, attention, model confidence, or any other sensor evidence must never directly grant permission.