# JARVIS V1 Current Plan

## Active Step

**Step 3 — Identity, Graduated Trust, Authority, and Observability Foundation**

## Current Stage

**PHASE 3A COMPLETE + MERGED — PHASE 3B ACTIVE — STARTUP OPERABILITY ACCEPTED — DUAL POCKET3 AUDIO OWNERSHIP REJECTED — ADR-013 SINGLE-MICROPHONE ACTIVE-SPEAKER REPLACEMENT IMPLEMENTED — REAL-MACHINE ACCEPTANCE NEXT — THEN 3B.11 SCORE-DISTRIBUTION BAKE-OFF**

This file is the operational source of truth for what is done, what is accepted, and what happens next. Detailed evidence belongs in `docs/research/`; significant architecture decisions belong in `docs/decisions/`.

---

## Completed / accepted foundation

| Slice | Status | Current disposition |
|---|---|---|
| Step 0 | Complete | product/repo foundation |
| Step 1 | Complete | realtime natural conversation architecture |
| Step 2 | Complete | local wake + voice lifecycle |
| Step 2.5 | Complete | Pocket3 vision/tracking/PTZ foundation |
| Step 3A | Complete + merged | authority/policy/approval/audit/session boundaries |
| 3B.1 | Accepted | encrypted single OWNER storage |
| 3B.2/3 | Accepted | pinned YuNet + SFace runtime/assets |
| 3B.4 | Accepted | Pocket3 face pipeline |
| 3B.5A | Accepted baseline | positive OWNER face calibration |
| 3B.6 | Accepted | encrypted multi-prototype OWNER enrollment |
| 3B.7A | Accepted | active facial-liveness fallback |
| 3B.7B | Human-accepted | passive MiniFAS temporal RGB liveness |
| 3B.8 | Human-accepted | runtime OWNER identity + liveness binding |
| 3B.9 | Deferred | attention waits for fixed monitor-relative sensor |
| 3B.10 | Accepted shadow provider | CAM++ speaker embedding foundation |
| 3B.10A | Human-accepted | passive canonical user-turn capture + OWNER-context bridge |
| Startup operability | Human-accepted configuration/preflight | `jarvis-setup`, machine profile, stable device selectors, consolidated preflight |

T2 `CORROBORATED_OWNER` remains intentionally disabled.

---

## Accepted startup operation

Normal operation no longer depends on rebuilding environment variables from chat/PowerShell history.

```text
one-time jarvis-setup
        ↓
%LOCALAPPDATA%\JARVIS\machine.json
        +
Windows environment for API keys only
        ↓
jarvis-voice
```

Real-machine setup proved:

- wake model persisted;
- tuned wake threshold `0.82` preserved;
- Pocket3 microphone persisted as stable `name + hostapi` selector;
- NVIDIA `24'TV` persisted as stable 48-kHz output selector;
- Gemini credential detected;
- vision/speaker/active-speaker switches persisted;
- official pinned LR-ASD AVA checkpoint acquired and integrity-verified automatically;
- legacy non-secret `JARVIS_*` Windows User overrides removed;
- stale inherited Tribit environment state no longer overrides the machine profile;
- `jarvis-voice` preflight passes without manually setting runtime variables.

Decision: `docs/decisions/ADR-012_MACHINE_CONFIGURATION_AND_STARTUP_PREFLIGHT.md`.

---

## Conversation audio — accepted

Production conversation audio remains:

```text
Pocket3 microphone @ 48 kHz
        ↓
LiveKit rtc.MediaDevices
WebRTC AEC + NS + HPF + AGC
        ↓
Gemini Live / AgentSession
        ↓
LiveKit MediaDevices output @ 48 kHz
        ↓
NVIDIA HDMI → 24'TV
```

Real acceptance already proved:

- no false self-interruption while JARVIS speaks and the user is silent;
- deliberate real human barge-in interrupts correctly;
- Bluetooth/Tribit path is not the accepted render path.

Decision: `docs/decisions/ADR-011_LIVEKIT_MEDIADEVICES_48K_FULL_DUPLEX.md`.

---

## 3B.11 integration correction — dual Pocket3 audio ownership REJECTED

The first active-speaker integration attempted two simultaneous consumers of the same Pocket3 microphone:

```text
Pocket3 mic
   ├── LiveKit MediaDevices → conversation
   └── GStreamer wasapi2src → raw LR-ASD evidence
```

Real-machine tests rejected this boundary in both acquisition orders.

### GStreamer first

- paired GStreamer AV started;
- Vision produced a real frame;
- LiveKit then resolved the Pocket3 microphone but failed opening `sounddevice.InputStream` with `PaErrorCode -9996: Invalid device`.

### PortAudio first

- Pocket3 PortAudio stream opened and became active;
- GStreamer paired AV then failed to reach PLAYING.

Conclusion:

```text
GStreamer first  → LiveKit mic fails
PortAudio first  → GStreamer paired AV fails
```

Therefore **two independent Pocket3 microphone owners are not a viable production architecture on this machine**.

Evidence: `docs/research/STEP_3B11_DUAL_AUDIO_OWNERSHIP_ACCEPTANCE_RESULTS.md`.

---

## ADR-013 replacement — IMPLEMENTED, REAL-MACHINE ACCEPTANCE NEXT

Keep one microphone owner and reuse the canonical JARVIS timelines:

```text
                            POCKET3
                               │
                ┌──────────────┴──────────────┐
                │                             │
             AUDIO                           VIDEO
                │                             │
     LiveKit MediaDevices only        normal OpenCV Vision
     AEC + NS + HPF + AGC                    │
                │                     timestamped frame
canonical timestamped user PCM               │
                │                     exact track/head sequence
                └──────────────┬──────────────┘
                               │
                       monotonic alignment
                               │
                            LR-ASD
```

Implementation now exists in:

- `src/jarvis/voice/canonical_active_speaker_runtime.py`;
- `src/jarvis/voice/production_runtime.py`.

The production builder no longer creates `GStreamerPairedAVSource` for active-speaker sensing.

This is deliberately a reuse/integration change, not a new DSP stack:

- LiveKit remains the only Pocket3 microphone owner;
- existing `ObservedSessionAudioInput` + `InMemorySpeakerTurnCapture` provide bounded canonical user-turn PCM with monotonic timestamps;
- existing Vision frames use monotonic timestamps and exact frame/snapshot association;
- existing LR-ASD provider remains unchanged;
- no temporary WAV/video files;
- no second microphone;
- no new echo canceller;
- no authority/prototype promotion.

Decision: `docs/decisions/ADR-013_SINGLE_OWNER_POCKET3_AUDIO_FOR_ACTIVE_SPEAKER.md`.

### Immediate acceptance gate

Run the new production `jarvis-voice` on the real PC and prove:

1. startup preflight passes with no manual runtime variables;
2. Pocket3 microphone opens successfully through LiveKit MediaDevices;
3. NVIDIA/TV 48-kHz output opens successfully;
4. normal Vision starts simultaneously without GStreamer audio ownership;
5. wake detection remains healthy;
6. startup greeting / conversation playback remains healthy;
7. JARVIS does not self-interrupt on its own TV speech;
8. deliberate real barge-in still works;
9. OWNER speech creates a bounded canonical speaker turn;
10. Vision produces overlapping timestamped visual-track/head evidence;
11. LR-ASD reaches a diagnostic `SCORED` result when evidence is sufficient;
12. no threshold/prototype admission is enabled.

If this gate fails, debug the exact failed boundary. Do not reintroduce dual microphone ownership.

---

## After ADR-013 real-machine acceptance

Proceed with the actual 3B.11 LR-ASD bake-off.

Required scenarios:

```text
A. OWNER visible + OWNER speaking
B. OWNER visible + TV/phone/off-camera other speech
C. OWNER visible + JARVIS playback only
D. OWNER visible + OWNER replay from phone
E. OWNER + another visible person; OWNER speaks
F. OWNER + another visible person; other person speaks
G. overlapping OWNER + other/background speech
H. temporary OWNER head/face loss
```

Measure:

- LR-ASD raw score distributions;
- false active assignment to a silent OWNER face;
- off-camera speech behavior;
- replay/playback behavior;
- overlap behavior;
- timing/alignment sensitivity;
- inference latency and GPU/CPU footprint;
- insufficient/ambiguous rate.

No leaderboard/default threshold is accepted directly.

Only after a safe temporal rule is human-accepted may `ACTIVE_OWNER_SPEAKER` permit **session-only** CAM++ prototype admission for the same actor/turn.

---

## Work after 3B.11 acceptance

1. Permit session-only CAM++ prototype admission only when fresh OWNER+liveness and active-speaker evidence agree on the same actor/turn.
2. Collect real speaker similarity distributions passively.
3. Decide whether CAM++ separation is sufficient or ERes2NetV2 materially improves ambiguity.
4. Run targeted non-owner / OWNER-replay / overlap acceptance before any speaker threshold promotion.
5. Define persistent encrypted voice-template format only behind strongly verified OWNER enrollment/update semantics.
6. Resolve authoritative OWNER-vs-UNKNOWN face separation when consenting live non-owner calibration becomes available, or keep T2 designed so provisional face evidence cannot be mistaken for authoritative identity.
7. Define deterministic T2 `CORROBORATED_OWNER` composition from final accepted evidence.
8. Run broader replay/stale/expiry/cross-session/cross-track/cross-actor/policy/degraded-mode tests.
9. Remove obsolete GStreamer conversation/paired-audio and custom barge-in production plumbing after replacement acceptance.
10. Final docs/quality-gate/roadmap reconciliation.
11. Protected-main review and merge of Phase 3B.
12. Revisit attention when fixed monitor-mounted hardware exists.

---

## Non-negotiable Step-3 invariants

- Identity evidence is not execution permission.
- Face, voice, liveness, active-speaker, attention, wake word, Windows-unlocked state, or model confidence never directly authorize consequential actions.
- Windows Hello/FIDO2 remains the strong-verification path for consequential authority.
- `SPOOF` fails closed.
- `UNCERTAIN` may request stronger evidence but may not silently upgrade trust.
- Raw biometric audio/video is memory-only by default.
- Provider/device/model boundaries remain replaceable.
- T2 stays disabled until its final multimodal predicate is accepted.

---

## Documentation discipline

- update `CURRENT_PLAN.md` whenever active slice/acceptance/next action changes;
- update `CURRENT_ARCHITECTURE.md` whenever the production boundary changes;
- significant architecture choices require ADRs;
- real-machine results belong in `docs/research/`;
- superseded experiments must be marked and eventually removed;
- documentation reconciliation is part of acceptance, not later cleanup.

## Immediate Next Action

**Pull the ADR-013 single-microphone implementation and run the real production `jarvis-voice` acceptance.**
