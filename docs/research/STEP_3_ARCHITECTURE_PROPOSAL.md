# Step 3 — Identity, Graduated Trust, Authority, and Observability Architecture Proposal

**Status:** PROPOSED — RESEARCH COMPLETE — AWAITING HUMAN APPROVAL — NOT IMPLEMENTED  
**Date:** 2026-08-30

This proposal is the implementation boundary produced by the Step-3 research and threat model. It is deliberately minimal in authority while complete in contracts: later file, browser, device, calendar, email, coding, and automation steps must reuse these contracts instead of inventing their own trust/consent paths.

## 1. Architectural thesis

JARVIS must feel like it knows who it is talking to without treating convenient biometrics as infallible authentication.

The architecture therefore uses three independent layers:

```text
IDENTITY EVIDENCE
"Who might this be?"
        |
        v
GRADUATED TRUST
"How strongly do current fresh facts support owner authority?"
        |
        v
ACTION AUTHORITY
"May this exact action execute, with these exact parameters, now?"
```

No layer may be skipped.

## 2. Proposed top-level architecture

```text
Accepted sensor/runtime inputs
------------------------------
Pocket 3 -> RF-DETR/OC-SORT track/head context
Microphone -> JARVIS-owned local audio / active turn segments
Windows -> current user/session/lock state

                +-----------------------------------+
                | Step-3 Evidence Providers         |
                |                                   |
selected head ->| FaceIdentityProvider              |
                |   OpenCV YuNet + SFace            |
                |                                   |
challenge ----->| FaceLivenessProvider              |
                |   MediaPipe Face Landmarker       |
                |                                   |
voice segment ->| SpeakerIdentityProvider           |
                |   sherpa-onnx candidate           |
                |                                   |
Windows --------| WindowsSessionProvider             |
                |                                   |
optional A/V -->| ActiveSpeakerProvider             |
                +----------------+------------------+
                                 |
                                 v
                         IdentityEvidence[]
                                 |
                                 v
                +----------------+------------------+
                | IdentitySession / Resolver        |
                | - one persistent OWNER profile   |
                | - ephemeral UNKNOWN subjects     |
                | - continuity/freshness           |
                +----------------+------------------+
                                 |
                                 v
                         TrustEvaluator
                                 |
                      T0 / T1 / T2 / T3
                                 |
                                 v
user/model intent ---> immutable ActionProposal ---> RiskClassifier
                                 |                         |
                                 +------------+------------+
                                              v
                                    AuthorityService
                                 +------------+-----------+
                                 |                        |
                          PolicyEngine (OPA)      ApprovalService
                                 |                /       |       \
                                 |        direct intent  spoken   StrongVerifier
                                 |                     exact yes  Windows Hello
                                 +------------+-----------+-------+
                                              |
                                     AuthorityDecision
                                              |
                                  final pre-execution gate
                                              |
                         Step 7+ governed executor (future)
                                              |
                                              v
                                        AuditEventStore
```

Step 3 itself does **not** build the Step-7 generic executor. It establishes the governance API that any later executor must require.

## 3. Subject model

Step-3 v1 has intentionally simple identity scope:

- `OWNER` — exactly one explicitly enrolled persistent identity;
- `UNKNOWN` — ephemeral people/voices that are never persistently enrolled or named.

There is no trusted guest/family/admin role in v1. Adding one later is a policy/product change, not a database-row shortcut.

Unknown subjects receive only ephemeral IDs scoped to a track/session, e.g. `unknown:vision:42`. Their embeddings are not written to persistent storage.

## 4. Canonical identity evidence

All providers return a JARVIS-owned immutable value rather than mutating trust directly.

Conceptual contract:

```python
@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    evidence_id: str
    session_id: str
    modality: EvidenceModality
    subject: SubjectCandidate       # OWNER or UNKNOWN/none
    observed_at_monotonic: float
    expires_at_monotonic: float
    source_id: str                  # camera/mic/windows/verifier
    provider_id: str
    model_id: str | None
    quality: EvidenceQuality
    score: float | None             # ephemeral; not necessarily audited
    threshold_id: str | None
    visual_track_id: int | None
    audio_turn_id: str | None
    association_id: str | None
    verdict: EvidenceVerdict
    reason_codes: tuple[str, ...]
```

Provider scores never have universal meaning. The trust evaluator reads modality-specific verdicts/quality/freshness, not a generic normalized confidence supplied by an LLM.

### Evidence modalities

- `WINDOWS_SESSION`
- `PERSON_PRESENCE`
- `FACE_MATCH`
- `FACE_LIVENESS`
- `SPEAKER_MATCH`
- `VOICE_SPOOF` (optional/future)
- `ACTIVE_SPEAKER` (optional/future)
- `STRONG_VERIFICATION`

## 5. Identity-session state

`IdentitySession` is memory-resident authoritative runtime state. A new identity session begins when JARVIS starts or after a security-invalidating Windows session transition.

Conceptual state:

```python
@dataclass(slots=True)
class IdentitySession:
    id: str
    windows_session_id: int | None
    windows_user_sid_hash: str | None
    created_at_monotonic: float
    evidence: EvidenceWindow
    owner_visual_track_id: int | None
    owner_state: OwnerState
    trust_tier: TrustTier
    invalidated_at: float | None
    invalidation_reason: str | None
```

Raw face crops, microphone audio, and model tensors never become canonical session state.

## 6. Trust vocabulary

Trust is a deterministic tier derived from typed predicates. It is **not** a floating score and is never generated by the LLM.

### T0 — `UNVERIFIED`

Meaning: no fresh evidence sufficient to bind the current actor to the owner.

Allowed experience:

- wake and ordinary nonsensitive conversation;
- public/general information;
- non-private generic status where policy permits.

Not allowed:

- disclosure of owner-private data;
- consequential side effects.

### T1 — `PRESENT_CONTEXT`

Meaning: JARVIS has fresh physical/session context but not sufficiently spoof-resistant owner evidence. Examples: active Windows session, a stable person track, or a face/speaker owner candidate without required liveness.

Use:

- personalization hints that do not disclose sensitive information;
- better conversational continuity;
- never enough by itself for protected execution.

### T2 — `CORROBORATED_OWNER`

Meaning: deterministic requirements establish a fresh owner hypothesis suitable for bounded low/moderate-risk authority.

Initial rule candidate:

- active/unlocked expected Windows session;
- fresh OWNER face match attached to one stable visual track;
- recent successful randomized face-liveness challenge on that same track;
- no unresolved subject-association ambiguity relevant to the requested action;
- all evidence within configured freshness/continuity windows.

Speaker match may corroborate T2 but **cannot create T2 alone**. When multiple people are visible, a speaker match does not bind the turn to the owner track unless an `ActiveSpeakerProvider` provides that association. Without it, spoken consequential approval escalates.

### T3 — `VERIFIED_OWNER`

Meaning: the currently logged-on Windows user successfully completed a fresh platform strong-verification step through `StrongVerifier` (Windows Hello first; WebAuthn/FIDO2 later).

Important distinction:

- T3 may be used as short-lived session context for policy decisions;
- **critical action authorization is still proposal-specific and one-time.** A previous T3 verification does not become a reusable blank cheque.

### No ambient T4

There is deliberately no "super-admin ambient trust" tier. Certain actions remain `RESTRICTED/DEV_ONLY` even with T3 because allowing a session trust level to disable policy/audit or authorize self-modification creates a confused authority boundary.

## 7. Initial freshness and invalidation policy

These are conservative starting values to be tuned only through the Step-3 benchmark, never silently by a model:

| Evidence/state | Initial maximum age | Additional condition |
| --- | ---: | --- |
| person/track continuity sample | 2 s | same canonical track |
| face-match evidence | 5 s | same visual track |
| speaker-match evidence | 10 s | current/adjacent turn only |
| active-speaker association | 3 s | same turn + visual track |
| successful active liveness | 60 s | same continuous owner track/session |
| T2 corroborated-owner state | 60 s rolling maximum | must retain required continuity; loss/ambiguity decays sooner |
| T3 general verified-session hint | 5 min maximum | invalidated on Windows/session security transition |
| spoken approval receipt | 30 s | one exact proposal, one use |
| strong action approval receipt | 60 s | one exact proposal, one use |

Immediate invalidation triggers override every TTL:

- Windows lock/disconnect/logoff/user switch;
- identity session restart;
- owner visual track expires when that evidence is required;
- template/model incompatibility or integrity failure;
- material proposal mutation;
- approval consumption/cancellation;
- explicit `clear-session`.

## 8. Face-recognition execution design

Step 3 must not create a second full camera pipeline.

Proposed path:

```text
existing camera owner
   -> existing RF-DETR / OC-SORT person track
   -> existing head evidence
   -> eligible selected/interaction track only
   -> small head crop
   -> YuNet 5-point face alignment
   -> SFace embedding (CPU-first)
   -> temporal match observations
   -> IdentityEvidence(FACE_MATCH)
```

Rules:

- recognition is event/interaction-driven, not continuous persistent bystander identification;
- full-frame face search is avoided when existing track/head context can constrain the crop;
- raw crop is discarded after inference;
- comparison uses a fixed calibrated threshold version, never per-request threshold changes;
- multiple recent samples are aggregated deterministically (e.g. median/majority over a bounded evidence window) so one frame cannot elevate owner state;
- model/provider/checksum/license metadata are part of enrollment profile metadata;
- CPU is preferred initially to avoid RF-DETR GPU contention; GPU acceleration is optional only if benchmark shows a need.

OpenCV's published SFace cosine threshold `0.363` is a reference baseline, not an automatically accepted JARVIS security threshold. Real Pocket-3 positive/negative distributions determine the frozen JARVIS threshold.

## 9. Liveness challenge state machine

Active liveness is requested only when policy needs T2 and no fresh liveness evidence exists.

```text
IDLE
  |
  v
GENERATE RANDOM CHALLENGE
  |  e.g. BLINK -> TURN_LEFT
  v
PRESENT CHALLENGE
  |
  v
OBSERVE SAME VISUAL TRACK
  |
  +--> wrong track / timeout / lost face -> FAILED
  |
  +--> deterministic required motion sequence -> PASSED
                                                |
                                                v
                                     short-lived LIVENESS evidence
```

The challenge order is randomly selected per attempt and has a short timeout. A previously recorded successful motion sequence cannot be replayed as an approval token because the expected sequence and current track/session are fresh.

Liveness result is not authority. It only participates in T2 derivation.

## 10. Speaker identity design

The JARVIS audio runtime remains the single microphone owner. Step 3 receives a bounded local tap of already captured active-turn PCM.

```text
LocalAudioRuntime
    -> current speech turn/VAD segment
    -> bounded IdentityAudioTap
    -> local speaker embedding provider
    -> compare against encrypted OWNER speaker template
    -> OWNER_MATCH / UNKNOWN / INSUFFICIENT_AUDIO evidence
    -> immediately discard PCM/tensor
```

Rules:

- no second microphone stream;
- no cloud speaker recognition;
- no raw voice recording by default;
- voice match never creates T3 and never substitutes for liveness/strong verification;
- replay/deepfake detection, if later added, is an additional evidence type rather than a magical "secure voice" flag;
- multi-person audio/visual association is explicit; temporal coincidence alone is not enough.

## 11. Enrollment architecture

All persistent biometric enrollment mutations require `StrongVerifier`.

### Owner face enrollment

Proposed flow:

1. Verify current Windows user through Windows Hello.
2. Explain that only local embeddings are retained and raw frames are discarded.
3. Start a live randomized challenge.
4. Capture quality-gated samples across frontal and moderate left/right pose plus ordinary near/far variation.
5. Compute several embeddings and remove obvious low-quality/outlier samples.
6. Build a minimal template representation (benchmark chooses centroid vs small multi-template set).
7. Store model ID/version/checksum, threshold version, quality statistics, created time.
8. Encrypt the template under the owner-profile DEK.
9. Discard source frames/crops.
10. Audit enrollment metadata without embedding values.

### Owner speaker enrollment

1. Strong-verifier gate.
2. Explain that voice is corroborating evidence, not strong authentication.
3. Capture several normal speech segments in the ordinary microphone position.
4. Quality/VAD gate them.
5. Produce a minimal multi-segment/centroid template based on benchmark result.
6. Encrypt and discard source audio.

### Delete/re-enroll

- require strong verification;
- generate a new profile generation/DEK for re-enrollment rather than silently mixing incompatible templates;
- delete/destroy the old sealed DEK for crypto-shredding;
- clean SQLite deleted content as defense in depth;
- invalidate active identity sessions and require fresh evidence.

## 12. Action risk model

Risk is deterministic JARVIS state, not an LLM label. Each proposed action declares side-effect attributes; the `RiskClassifier` maps them to the minimum class. Policy may raise requirements but may not lower hardcoded security floors.

### Risk attributes

At minimum:

- reads private data;
- writes/persists state;
- external side effect/communication;
- reversible vs destructive/irreversible;
- financial/legal consequence;
- secret/credential access or export;
- security/permission change;
- executable/install/system change;
- identity/authority/audit change;
- self-modification;
- background/proactive execution;
- target scope (one item vs broad/bulk);
- user-visible vs silent.

### R0 — `ROUTINE`

Examples: ordinary conversation, public research, non-private status.

Minimum: T0. No extra approval.

### R1 — `PRIVATE_READ`

Examples later: read private calendar/email/file content, reveal sensitive personal context.

Minimum: T2 for owner-private disclosure. A direct current request can be sufficient intent once T2 is established. Proactive disclosure requires separate policy/consent.

### R2 — `REVERSIBLE_LOCAL_CHANGE`

Examples later: open an app, adjust volume, reversible local UI/state change.

Minimum: T2. A direct current request can count as intent for low-impact changes; inferred/proactive actions require explicit confirmation.

### R3 — `PERSISTENT_OR_EXTERNAL`

Examples later: write/rename a file, create calendar event/task, send ordinary message/email, modify persistent configuration where rollback is straightforward.

Minimum: T2 **plus exact explicit approval** unless policy specifically recognizes the originating user request as sufficiently explicit for a narrowly bounded operation. External communication should normally confirm recipient + material content/intent before execution.

Spoken approval is permitted only when the identity/actor association is unambiguous. Otherwise escalate to StrongVerifier.

### R4 — `CRITICAL`

Examples: irreversible deletion, financial transaction, credential/secret export, security setting or permission change, installing/running downloaded executable, broad destructive operation, account recovery, sensitive identity-template mutation.

Minimum: exact proposal + T3 `StrongVerifier`. Spoken "yes" alone is never sufficient.

### R5 — `RESTRICTED_DEV_ONLY`

Examples:

- disable/bypass authority policy;
- disable required audit controls;
- alter trust/risk floors from normal runtime;
- export raw biometric templates;
- grant unrestricted shell/system authority;
- autonomous self-modification;
- modify JARVIS protected update authorization to self-approve.

Normal runtime result: **DENY**. Such changes require the protected development workflow or a purpose-built future admin ceremony.

## 13. Default risk/trust/approval matrix

| Risk | Minimum trust | Approval requirement | If identity ambiguous | Audit required before execution |
| --- | --- | --- | --- | --- |
| R0 Routine | T0 | none | continue nonsensitive only | lightweight/optional |
| R1 Private read | T2 | direct-request intent normally | deny private disclosure or strong-verify | yes for sensitive reads |
| R2 Reversible local | T2 | direct intent; explicit if inferred/proactive | strong-verify or deny | yes |
| R3 Persistent/external | T2 | proposal-bound explicit approval | strong-verify | yes, mandatory |
| R4 Critical | T3 | proposal-bound StrongVerifier | StrongVerifier is already required; ambiguity never downgrades | yes, mandatory |
| R5 Restricted/dev-only | none | unavailable to normal runtime | deny | yes, mandatory |

Policies can demand **more** trust/approval than this table. They cannot demand less than the hard minimum for R4/R5.

## 14. Immutable action proposal

Before authority can be evaluated, model/tool intent must be converted into a typed immutable proposal.

Conceptual schema:

```python
@dataclass(frozen=True, slots=True)
class ActionProposal:
    proposal_id: str
    nonce: str
    identity_session_id: str
    created_at: datetime
    expires_at: datetime
    capability: str
    operation: str
    resource_type: str
    resource_id: str | None
    parameters: CanonicalJson
    material_summary: str
    risk_attributes: ActionRiskAttributes
    risk_class: RiskClass
    origin: ActionOrigin             # direct_user / model_suggested / proactive / system
    origin_turn_id: str | None
    proposal_hash: str               # SHA-256 over canonical material fields
```

The material summary is user-facing. The canonical hash is machine-facing. Approval binds the hash, not merely human-language text.

## 15. Approval modes

```text
NONE
DIRECT_REQUEST_INTENT
EXPLICIT_SPOKEN
STRONG_VERIFIER
DEVELOPER_ONLY
```

### Direct request intent

A clearly bounded user request in the current active turn can be recorded as an `IntentReceipt`. It is not equivalent to a separate confirmation when policy requires one.

### Explicit spoken approval

The same principle used by `jarvis-dev` applies: a bounded approval session listens only for deterministic explicit decision grammar. The LLM does not classify approval.

For Step 3, the approval is additionally bound to the proposal ID/hash and identity session. A nearby generic "yes" outside the pending window has no effect.

### Strong verifier

The Windows Hello prompt includes a concise material action summary. The deterministic adapter maps only `Verified` to a successful receipt. Cancel, busy, not configured, retries exhausted, exceptions, or timeout are not approvals.

## 16. Approval receipt

```python
@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    receipt_id: str
    proposal_id: str
    proposal_hash: str
    identity_session_id: str
    method: ApprovalMethod
    subject: SubjectId
    issued_at_monotonic: float
    expires_at_monotonic: float
    verifier_id: str | None
    one_time: bool
```

Receipts are runtime authority objects, not strings injected into model context. Consumed/expired/canceled receipts cannot be replayed.

## 17. Authority state machine

```text
PROPOSED
   |
   v
RISK_CLASSIFIED
   |
   v
POLICY_EVALUATED
   |        \
   |         \--> DENIED -> AUDIT -> CLOSED
   |
   +--> ALLOW_NO_EXTRA_APPROVAL
   |                |
   |                v
   |          PRE_EXECUTION_REVALIDATE
   |
   +--> REQUIRE_APPROVAL
                    |
                    v
             AWAITING_APPROVAL
               /    |      \
          denied  expired  approved
             |       |        |
             v       v        v
           CLOSED  CLOSED   APPROVED
                               |
                               v
                    PRE_EXECUTION_REVALIDATE
                               |
                  +------------+------------+
                  |                         |
                invalid                    valid
                  |                         |
                  v                         v
                DENY                    EXECUTION_TOKEN
                                             |
                                             v
                              Step-7+ executor (future)
                                             |
                                             v
                                      EXECUTED/FAILED
                                             |
                                             v
                                           AUDIT
```

Any material mutation after `PROPOSED` resets the flow with a new proposal.

## 18. Policy-engine boundary

`PolicyEngine` is replaceable:

```python
class PolicyEngine(Protocol):
    async def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...
```

`PolicyRequest` contains only canonical facts:

- subject/identity state;
- trust tier and evidence freshness predicates;
- action capability/operation/resource;
- deterministic risk class/attributes;
- action origin;
- Windows/session state;
- requested approval mode if any;
- relevant policy context.

OPA may return a structured document such as:

```json
{
  "effect": "require_approval",
  "minimum_trust": "T2",
  "approval_mode": "explicit_spoken",
  "reasons": ["external_side_effect"],
  "obligations": ["audit_before_execution", "confirm_recipient"]
}
```

The adapter validates every field. Missing/undefined/malformed/timeout = DENY.

OPA is never the executor, never a biometric resolver, and never allowed to modify its own policy.

## 19. Final enforcement token

Later executors should not receive raw model text or "approved=true" booleans. They receive a short-lived JARVIS `ExecutionAuthorization` containing:

- proposal ID/hash;
- authority decision ID;
- identity session ID;
- policy version/hash;
- approval receipt ID/hash where required;
- allowed capability/operation/resource;
- expiry;
- one-time execution nonce.

The executor checks it and reports execution result back to the audit service. This prevents every later capability from inventing its own consent mechanism.

## 20. Audit architecture

Initial store: local SQLite.

Separate tables/areas:

- owner profile/model metadata;
- encrypted biometric templates;
- policy/version metadata;
- security/authority audit events.

Proposed audit event:

```python
@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    timestamp_utc: datetime
    monotonic_sequence: int
    event_type: str
    identity_session_id: str | None
    subject_role: str | None
    trust_tier: str | None
    proposal_id: str | None
    proposal_hash: str | None
    policy_version: str | None
    decision_id: str | None
    reason_codes: tuple[str, ...]
    redacted_metadata: Mapping[str, JsonValue]
    previous_event_mac: str | None
    event_mac: str | None
```

A chained HMAC is proposed only if its key-protection and crash/recovery behavior passes testing. It provides tamper evidence within the stated endpoint threat model; it is not marketed as immutable against a fully compromised OS/admin.

## 21. Privacy storage design

```text
random OWNER profile DEK
        |
        +--> AES-GCM encrypt face template
        +--> AES-GCM encrypt voice template
        +--> AES-GCM encrypt any sensitive calibration payload
        |
        v
DPAPI(user-scope) seals DEK
        |
        v
SQLite stores encrypted blobs + sealed DEK + non-sensitive metadata
```

No plaintext profile DEK is written to configuration or source control. Raw biometric media is not stored.

## 22. Provider/version manifest

Every biometric model/provider promoted into the implementation must have a manifest entry containing at least:

- provider name/version;
- model name/version;
- immutable file checksum;
- source URL;
- code license;
- model/weight license;
- training-data/provenance note if known;
- backend/device (CPU/CUDA/ONNX Runtime/etc.);
- embedding dimension;
- threshold/calibration version;
- enrollment compatibility version.

Unknown licensing/provenance is an explicit state, never silently interpreted as permissive.

## 23. Benchmark and selection plan

Technology research is complete, but local models still require evidence on the actual hardware before a provider is promoted from candidate to accepted implementation.

### 23.1 Face provider benchmark

Candidates:

1. OpenCV YuNet + SFace — intended deployment candidate.
2. InsightFace `buffalo_l` — isolated accuracy robustness reference only, subject to non-commercial model terms.

Dataset collected deliberately for benchmark only, with raw benchmark media deleted afterward unless explicitly retained:

- owner frontal normal light;
- low/uneven light;
- moderate left/right pose;
- glasses/no-glasses if applicable;
- seated/standing ordinary distances;
- motion-transition frames;
- consented non-owner negative samples if available;
- photo/screen attacks evaluated separately under liveness.

Acceptance:

- stable deterministic threshold, versioned after calibration;
- no false OWNER acceptance in the available local negative set;
- target owner FNMR under 5% in the defined normal-use acceptance set where achievable;
- no reliance on a single frame: temporal evidence aggregation required;
- identity sampling must not reduce accepted camera/wake/conversation behavior by more than 10% relative to baseline;
- deployment provider should keep face embedding off the RF-DETR GPU unless benchmark proves CPU inadequate;
- model loading/latency must fit the current 8-GB-GPU/16-GB-RAM machine without destabilizing vision.

The local sample size cannot prove a statistical NIST FMR of 1:10,000; documentation must say so.

### 23.2 Liveness benchmark

Live trials:

- normal blink challenge;
- left/right head-turn challenge;
- randomized two-step sequence;
- glasses and ordinary lighting conditions.

Attack trials:

- printed photo;
- owner photo on phone/tablet;
- prerecorded owner video on screen;
- paused/looped video;
- TV/monitor presentation where feasible.

Acceptance for the scoped attacks:

- zero successful attack acceptance in the local test matrix;
- at least 95% successful live completion in normal conditions;
- wrong challenge order, wrong track, timeout, or track swap must fail;
- successful challenge evidence invalidates on identity-session/security transition;
- documentation explicitly states that advanced injection/real-time deepfake resistance is not proven.

### 23.3 Speaker benchmark

Candidates:

1. sherpa-onnx compatible WeSpeaker model — deployment candidate.
2. SpeechBrain ECAPA — accuracy reference.

Conditions:

- quiet near mic;
- ordinary room noise;
- different distances/orientations;
- TV playing;
- non-owner voices;
- playback of recorded owner voice;
- synthetic/cloned voice sample if legally/ethically available for self-testing.

Acceptance:

- useful owner-vs-unknown separation in normal live speech;
- no path from speaker result alone to T2/T3;
- replay/clone tests must demonstrate that even a false voice match cannot authorize R3/R4;
- extraction should fit after a speech turn without materially delaying conversational response;
- chosen model license/provenance recorded before promotion.

If no candidate produces robust local separation without harming runtime, speaker identity remains diagnostics/context only and Step 3 remains secure.

### 23.4 Active-speaker benchmark — CONDITIONAL

Only run if real multi-person testing shows unacceptable friction and we decide spoken R3 approval must work with several visible people.

Candidates: LR-ASD / Light-ASD.

Acceptance must prove temporal association to the correct visual track under two-person speech/TV cases. Otherwise the safe fallback remains StrongVerifier.

### 23.5 Windows Hello benchmark

Test on the real Windows machine:

- availability/configuration detection;
- success;
- user cancel;
- wrong/retry exhaustion path where safe;
- device busy/unavailable mapping;
- Windows lock/unlock around pending verification;
- proposal mutation before/after verification;
- expiry and one-use behavior;
- repeated operations cannot reuse an old receipt.

Target UX: normal prompt appears promptly; p95 total user-verification flow is dominated by human interaction, while JARVIS API overhead should be negligible (<250 ms excluding user response/platform UI).

### 23.6 OPA benchmark and policy tests

Must cover:

- every R0-R5 policy matrix combination;
- default deny on missing rule/field;
- malformed JSON/output;
- process unavailable/crash;
- timeout;
- invalid policy compile/check;
- policy version/hash mismatch;
- explicit attempted downgrade from StrongVerifier to spoken approval;
- unknown future capability/action defaults to deny.

Target local policy evaluation p95: <50 ms including loopback adapter overhead under normal load. Policy latency is not allowed to block ordinary conversation when no action is being authorized.

### 23.7 Audit/storage tests

- encrypted profile cannot be decoded without unsealing expected user-scoped key;
- corrupt ciphertext/tag fails closed;
- no raw biometric media/vector appears in audit/log fixtures;
- proposal-sensitive payload is redacted/hash-minimized;
- retention purge executes at configured boundary;
- profile deletion destroys key reference and makes residual encrypted template unusable;
- chained HMAC, if enabled, detects row modification/deletion/reordering in the tested threat model;
- crash/restart recovers sequence without silently accepting broken audit integrity;
- R3/R4 execution is denied if mandatory audit write cannot succeed.

## 24. Human acceptance scenarios

Step 3 cannot be accepted from unit tests alone. Real acceptance must include:

1. **Ordinary chat:** unverified speaker can wake JARVIS and ask a public question without security friction.
2. **Owner recognition:** JARVIS can identify the enrolled owner locally during an active interaction without storing raw media.
3. **Photo attack:** owner photo must not create T2.
4. **Screen/video attack:** recorded face/video must not satisfy the randomized liveness flow in the scoped test set.
5. **TV/recorded voice:** can cause at most conversation noise/voice match; never protected authority.
6. **Unknown person:** cannot retrieve private owner data or cause side effects requiring T2+.
7. **Owner private read:** after fresh T2 evidence, a bounded private read policy can allow the action without Windows Hello.
8. **Persistent/external action:** exact material action is presented; unrelated/ambiguous "yes" does nothing.
9. **Multiple people:** without reliable speaker-to-face association, spoken consequential approval fails safely and JARVIS offers strong verification.
10. **Critical action:** Windows Hello is required; spoken "yes" cannot bypass it.
11. **Action mutation:** change recipient/path/amount/target after approval and old receipt is rejected.
12. **Windows lock:** trust and pending approvals invalidate immediately; unlock does not restore old approval.
13. **OPA outage:** protected action is denied, while normal conversation remains alive.
14. **Hello unavailable:** JARVIS truthfully says strong verification is unavailable; no biometric downgrade.
15. **Audit outage:** R3/R4 action does not execute silently.
16. **Delete owner profile:** strong-verifier-gated deletion removes usable templates and invalidates active identity state.
17. **Restart:** no stale in-memory evidence/approval survives application restart.
18. **Model update:** incompatible biometric model cannot silently compare old template.

## 25. Proposed implementation sequence

This order reduces security risk and avoids letting biometrics become authority before the authority engine exists.

### Phase 3A — Authority skeleton first

- canonical types/contracts;
- ActionProposal/hash/risk classifier;
- OPA adapter + fail-closed policy;
- ApprovalService state machine;
- StrongVerifier Windows Hello adapter;
- AuditEventStore foundation;
- Windows session invalidation;
- exhaustive policy/TOCTOU/replay tests.

No face/voice authority yet.

### Phase 3B — Owner profile + face evidence

- encrypted profile store / DPAPI key sealing;
- explicit owner enrollment/delete/re-enroll;
- YuNet + SFace provider;
- face evidence aggregation/freshness;
- MediaPipe randomized liveness;
- T0/T1/T2 trust evaluator;
- photo/screen/live human benchmark.

### Phase 3C — Speaker evidence

- bounded audio tap;
- isolated benchmark SpeechBrain vs sherpa-onnx candidate;
- deploy chosen provider if it adds useful corroboration;
- TV/replay/unknown voice tests;
- no change to strong-authorization floor.

### Phase 3D — Multi-person + hardening

- real two-person/TV ambiguity testing;
- add LR-ASD/Light-ASD only if needed to improve bounded spoken approval;
- audit-integrity hardening;
- complete STRIDE/LINDDUN residual-risk review;
- final human acceptance and documentation reconciliation.

## 26. ADRs to create only after approval

If this proposal is approved, the implementation branch should record at least these accepted decisions:

1. **ADR-006 — Identity evidence is non-authoritative and trust is predicate-based.**
2. **ADR-007 — Exact-action authority uses deterministic risk/policy/approval outside the LLM.**
3. **ADR-008 — Windows Hello is the initial strong verifier; WebAuthn remains replaceable future adapter.**
4. **ADR-009 — Local biometric privacy/storage and audit boundaries.**
5. Provider/model-specific ADR only after local benchmark selects the face/speaker deployment model.

Do not create an "accepted" provider ADR merely because a benchmark candidate runs.

## 27. Explicit non-scope

Step 3 does not grant:

- file/system/browser/email/calendar/device execution;
- unrestricted shell access;
- remote execution;
- passive continuous world profiling;
- long-term personal memory;
- guest/family trust roles;
- cloud face/voice recognition;
- smart-glasses identity;
- autonomous security-policy modification;
- self-improvement/self-repair authority.

Those later capabilities consume Step-3 authority contracts.

## 28. Approval decision requested

The proposed Step-3 architecture is:

- local, typed face/voice/session evidence;
- SFace/YuNet as initial face deployment candidate subject to real benchmark;
- MediaPipe randomized active liveness rather than uncertain passive-PAD weights;
- sherpa-onnx speaker model benchmarked against SpeechBrain, with voice remaining corroboration only;
- Windows Hello as the strong-verification root for critical actions;
- four trust tiers T0-T3 with no ambient super-admin tier;
- deterministic R0-R5 risk classification;
- OPA behind a JARVIS-owned fail-closed policy interface;
- immutable proposal hashing + one-time exact-action approval receipts + final revalidation;
- SQLite local storage with envelope-encrypted biometric templates and user-scoped DPAPI key sealing;
- structured privacy-aware audit, optional HMAC tamper evidence, OTel only for operations;
- STRIDE + LINDDUN validation and explicit degraded-mode behavior.

This proposal should move to implementation only after explicit human approval.
