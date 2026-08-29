# Step 3 — Identity, Trust, Authority, and Observability Research

**Status:** RESEARCH COMPLETE — ARCHITECTURE PROPOSED — NOT YET APPROVED — NOT IMPLEMENTED  
**Date:** 2026-08-30  
**Active product slice:** Step 3

This record completes the technology research required before Step-3 implementation. It deliberately separates identity evidence from trust, trust from authorization, and authorization from execution.

## 1. Required JARVIS behavior

Step 3 must let JARVIS answer four different questions without collapsing them into one score:

1. **Who or what is present?**
2. **How much may JARVIS trust that evidence right now?**
3. **Is this exact requested action permitted?**
4. **What happened, why, and what evidence supported the decision?**

The desired user experience is low-friction for ordinary conversation and appropriately stronger verification for private or consequential actions. A face match, speaker match, wake word, Windows login state, or LLM confidence must never directly become permission.

## 2. Security baseline from current standards

NIST SP 800-63B-4 is the most important external security constraint for this design:

- biometrics are probabilistic and biometric characteristics are not secrets;
- biometrics are appropriate only as part of multi-factor authentication with a physical authenticator in NIST's authentication model;
- a deployed biometric system should target a false match rate of 1 in 10,000 or better and an FNMR under 5% under the stated test conditions;
- facial recognition used for authentication must implement presentation-attack detection (PAD);
- biometric comparison based on **voice shall not be used** for authentication;
- PAD testing should consider ISO/IEC 30107 and an impostor attack presentation accept rate below 0.07.

JARVIS is not claiming NIST conformance. These requirements are used as a design warning against treating consumer camera/voice models as strong authenticators.

**Research conclusion:** face and voice become typed identity evidence. Strong verification for high-consequence actions uses a platform authenticator such as Windows Hello/FIDO2.

Sources:

- https://pages.nist.gov/800-63-4/sp800-63b/authenticators/
- https://csrc.nist.gov/pubs/sp/800/63/b/4/final
- https://www.iso.org/standard/83828.html

## 3. Strong local verification

### 3.1 Windows Hello / UserConsentVerifier — ADOPT + WRAP

Windows exposes `UserConsentVerifier` for application-requested verification. Desktop applications can use `IUserConsentVerifierInterop::RequestVerificationForWindowAsync`, which performs verification through Windows Hello, Passport PIN, or a fingerprint reader and displays a caller-supplied message.

The API returns explicit states such as `Verified`, `Canceled`, `RetriesExhausted`, `DeviceBusy`, `NotConfiguredForUser`, and `DisabledByPolicy`.

Current Python integration is realistic: `winrt-Windows.Security.Credentials.UI` 3.2.1 publishes CPython 3.11 Windows x64 wheels.

**Decision candidate:** implement a JARVIS-owned `StrongVerifier` interface with a Windows Hello/UserConsentVerifier adapter first. A successful result proves that the currently logged-on Windows user completed the platform verification step; JARVIS must still bind that result to its own immutable action proposal.

Sources:

- https://learn.microsoft.com/en-us/windows/win32/api/userconsentverifierinterop/nf-userconsentverifierinterop-iuserconsentverifierinterop-requestverificationforwindowasync
- https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.ui.userconsentverificationresult
- https://pypi.org/project/winrt-Windows.Security.Credentials.UI/

### 3.2 WebAuthn/FIDO2 — KEEP AS STRONGER/FUTURE ADAPTER

Windows has exposed Win32 WebAuthn APIs since Windows 10 1903. They support Windows Hello and external FIDO2 security keys. `WebAuthNAuthenticatorGetAssertion` produces an authenticator assertion after user consent to a specific transaction/challenge.

This is a strong future option for security-policy changes or other especially sensitive operations. It is more infrastructure than Step-3 v1 needs, so the interface must support it without requiring it initially.

Sources:

- https://learn.microsoft.com/en-us/windows/security/identity-protection/hello-for-business/webauthn-apis
- https://learn.microsoft.com/en-us/windows/win32/api/webauthn/

## 4. Windows session evidence

Windows RDS/WTS APIs expose whether the current session is active or disconnected/locked. `WTSDisconnected` can represent a signed-in user at the lock screen, and applications can subscribe to session lock/unlock notifications.

**Decision candidate:** adopt a `WindowsSessionProvider` that observes current SID/session ID and lock/unlock/logon state. This is contextual evidence only. A Windows session being active does not prove the person in front of the microphone/camera is the owner.

A lock, user switch, logoff, or session disconnect must immediately invalidate pending approvals and elevated trust.

Sources:

- https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/ne-wtsapi32-wts_connectstate_class
- https://learn.microsoft.com/en-us/windows/win32/api/wtsapi32/nf-wtsapi32-wtsregistersessionnotification

## 5. Face identity candidates

### 5.1 OpenCV YuNet + SFace — PREFERRED INITIAL DEPLOYMENT CANDIDATE

OpenCV 5 exposes `FaceDetectorYN` and `FaceRecognizerSF`. The current OpenCV tutorial pairs YuNet with SFace and publishes reference similarity thresholds. The SFace model is approximately 36.9 MB and OpenCV reports 99.60% LFW accuracy with the current tutorial model; OpenCV Zoo's SFace directory reports 0.9940 accuracy in its evaluation and states that all files in the directory are Apache-2.0 licensed.

Advantages for JARVIS:

- OpenCV is already part of the accepted runtime;
- small CPU-friendly model, avoiding extra GPU contention with RF-DETR;
- ONNX model and stable OpenCV API;
- YuNet supplies the five landmarks expected by SFace alignment;
- easy to run only inside the existing selected/head crop rather than a second full-frame vision stack.

Important licensing caveat: an OpenCV Zoo issue opened in July 2026 asks maintainers to clarify the exact SFace weight's training-data provenance and commercial-use implications. The directory says Apache-2.0, but training-data provenance is not yet fully documented publicly.

**Research position:** suitable for this personal-development implementation and the best initial deployment candidate, but model ID/checksum/license provenance must be recorded. If JARVIS is distributed commercially later, re-check the unresolved provenance item or swap the provider.

Sources:

- https://docs.opencv.org/5.0/tutorials/dnn/dnn_face/dnn_face.html
- https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface
- https://github.com/opencv/opencv_zoo/issues/313

### 5.2 InsightFace / ArcFace buffalo_l — ACCURACY REFERENCE, NOT DEFAULT DEPLOYMENT

InsightFace is a mature, high-accuracy face-analysis stack. Its `buffalo_l` package uses a ResNet50 recognition model and reports 99.83 LFW, 99.33 CFP-FP, 98.23 AgeDB-30, and 97.25 IJB-C(E4) in its model-zoo table.

However, InsightFace explicitly states that public pretrained model packages, including `buffalo_l`, are non-commercial research models unless separately licensed. The code is MIT; the pretrained weights are not unrestricted commercial assets.

**Decision candidate:** use `buffalo_l` only as an isolated accuracy/robustness benchmark reference unless a separate license is deliberately acquired. Do not make it the architectural dependency.

Sources:

- https://github.com/deepinsight/insightface
- https://github.com/deepinsight/insightface/blob/master/model_zoo/README.md

### 5.3 DeepFace — REJECT AS PRODUCTION AUTHORITY LAYER

DeepFace is a useful MIT-licensed experimentation framework and wraps many models, including SFace, ArcFace, and Buffalo_L. Its documentation explicitly notes that wrapped model licenses are inherited.

It is useful for research comparison, but using it as JARVIS's production identity layer would hide provider/model/license differences behind another framework and duplicate the JARVIS-owned adapter boundary.

**Decision:** do not make DeepFace the production identity abstraction.

Source:

- https://github.com/serengil/deepface

## 6. Face liveness / presentation attack detection

### 6.1 What passive RGB PAD can and cannot prove

NIST FATE Part 10 evaluates passive, software-only PAD over conventional 2D imagery. That is useful evidence but does not make an ordinary webcam equivalent to trusted depth/IR hardware. ISO/IEC 30107-1 also scopes presentation attacks at the capture device and does not itself provide a complete system-security assessment.

**Conclusion:** any RGB-only PAD result from the Pocket 3 remains supporting evidence. It cannot replace Windows Hello/FIDO2 for high-consequence actions.

Sources:

- https://www.nist.gov/publications/face-analysis-technology-evaluation-fate-part-10-performance-passive-software-based
- https://www.iso.org/standard/83828.html

### 6.2 Randomized active challenge with MediaPipe Face Landmarker — PREFERRED V1

MediaPipe Face Landmarker can emit 52 facial blendshapes, including left/right blink, and facial transformation matrices that can support head-pose estimation.

A randomized short challenge such as `blink`, `turn left`, or `turn right`, with a nonce-like per-attempt challenge sequence, gives explicit user participation and is substantially more robust to static photo and ordinary recorded-video attacks than a face match alone.

It is still vulnerable to sufficiently capable real-time reenactment/injection and therefore remains a liveness evidence source, not a strong authenticator.

**Decision candidate:** use MediaPipe Face Landmarker for active challenge-response liveness when T2 corroborated-owner trust is required. Cache the successful liveness evidence only for a short, continuity-bound window to avoid annoying the user.

Sources:

- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions
- https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/drawing_styles/face_landmarker/Blendshapes

### 6.3 MiniFASNet / passive PAD — DEFER

MiniFASNet is attractive because it is tiny (roughly 0.43M parameters) and ONNX-friendly. Multiple repositories expose Apache-licensed inference code. However, current due-diligence work has flagged that the provenance/license of commonly redistributed pretrained weights is not as clear as the code license.

**Decision:** do not make MiniFASNet a v1 dependency. It can be benchmarked later only after weight provenance is documented. Active challenge-response plus Windows Hello provides a cleaner first architecture.

Sources:

- https://github.com/yakhyo/face-anti-spoofing
- https://github.com/archledger/irlume/blob/main/models/README.md

## 7. Speaker identity candidates

NIST's current guidance is decisive: voice biometric comparison must not be treated as authentication. JARVIS may still use speaker identity to improve conversational context and corroborate another identity hypothesis.

### 7.1 SpeechBrain ECAPA-TDNN — ACCURACY REFERENCE

SpeechBrain's `spkrec-ecapa-voxceleb` model is Apache-2.0, about 89 MB, trained on VoxCeleb1+2, and reports a cleaned VoxCeleb1 EER around 0.8% (some model-card revisions report 0.69%). It is a strong mature reference for owner-vs-not-owner speaker verification.

It uses PyTorch and adds framework/dependency weight. JARVIS already has PyTorch for vision, but Step 3 should avoid destabilizing the accepted CUDA environment merely to add a corroborating signal.

Source:

- https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb

### 7.2 sherpa-onnx + WeSpeaker/3D-Speaker — PREFERRED DEPLOYMENT FAMILY TO BENCHMARK

`sherpa-onnx` supports local speaker embeddings/identification through ONNX and exposes models from WeSpeaker, 3D-Speaker, and NeMo. This is operationally attractive for JARVIS because it avoids a second large model framework in the realtime path.

WeSpeaker publishes ONNX inference paths and states that pretrained-model licensing follows the training dataset; VoxCeleb models are documented as CC BY 4.0. 3D-Speaker's repository is Apache-2.0, although each chosen model still needs a model-card/license record.

**Decision candidate:** benchmark a sherpa-onnx WeSpeaker deployment model against SpeechBrain ECAPA on the actual JARVIS microphone. Prefer sherpa-onnx if it meets the local owner/unknown separation gate; otherwise use SpeechBrain behind the same interface.

Sources:

- https://k2-fsa.github.io/sherpa/onnx/speaker-identification/
- https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md
- https://github.com/modelscope/3D-Speaker

## 8. Voice replay/deepfake resistance

ASVspoof 5 is the right warning against overtrusting speaker verification. The 2026 challenge report covers diverse crowdsourced conditions and modern spoof/deepfake/adversarial attacks; submitted systems still degrade under adversarial attacks and neural codecs/compression.

**Decision:** speaker identity is never enough for an authority elevation. A future `VoiceSpoofProvider` may add defensive evidence, but Step-3 correctness must not depend on perfectly detecting cloned voices.

Source:

- https://arxiv.org/abs/2601.03944

## 9. Multi-person and active-speaker association

A face match and a voice match occurring at the same time do not prove that the voice came from that face. This matters when a TV, another person, or an off-screen speaker is present.

Audio-visual active-speaker detection (ASD) solves a narrower problem: which visible face is speaking. Current lightweight options include Light-ASD (MIT, CVPR 2023) and LR-ASD (IJCV 2025).

**Decision candidate:** define an `ActiveSpeakerProvider` contract now, but do not require a heavy ASD model for Step-3 v1. When more than one person is visible and JARVIS cannot bind the speaking turn to the recognized owner, spoken authorization must fail closed or escalate to Windows Hello. If real usage shows a need, benchmark LR-ASD/Light-ASD later without changing authority semantics.

Sources:

- https://github.com/Junhua-Liao/Light-ASD
- https://github.com/Junhua-Liao/LR-ASD

## 10. Speaker diarization

NVIDIA NeMo's current Sortformer family supports offline and streaming diarization, including streaming models for up to four speakers. This is mature technology but materially heavier than JARVIS needs for turn-by-turn owner/unknown classification on a single local microphone.

**Decision:** do not make NeMo Sortformer part of the Step-3 critical path. Keep it as a provider candidate if overlapping-speaker requirements are demonstrated later.

Sources:

- https://docs.nvidia.com/nemo/speech/nightly/asr/speaker_diarization/intro.html
- https://docs.nvidia.com/nemo/curator/v26.04/curate-audio/process-data/quality-filtering/speaker-separation

## 11. Policy-engine candidates

### 11.1 Open Policy Agent — PREFERRED V1 POLICY ENGINE

OPA is a mature general-purpose policy engine under Apache-2.0. It cleanly separates policy decision from enforcement, accepts structured JSON input, and can produce structured JSON decisions rather than only a boolean. Rego supports explicit default-deny rules and rich deny/reason output.

That maps well to JARVIS because a policy response can include fields such as effect, required trust, approval mode, reason codes, and obligations.

The simplest Python integration is a local OPA subprocess/sidecar on loopback. This adds lifecycle management, so the JARVIS adapter must treat OPA timeout/unavailability/undefined decision as **DENY**, never allow.

**Decision candidate:** WRAP OPA behind `PolicyEngine`. JARVIS owns the action schema, risk classifier, trust evaluator, approval state machine, and final enforcement. OPA evaluates declarative policy only.

Sources:

- https://www.openpolicyagent.org/docs
- https://www.openpolicyagent.org/docs/policy-reference/keywords/default
- https://github.com/open-policy-agent/opa

### 11.2 Cedar — STRONG ALTERNATIVE

Cedar is purpose-built for authorization and models requests as principal/action/resource/context. Schemas validate action applicability and context shape. It has excellent authorization semantics and analyzability.

`cedarpy` 4.8.7 currently ships CPython 3.11 Windows x64 wheels, but the Python binding is much newer than the Cedar core. Cedar's native authorization result is fundamentally Allow/Deny, so JARVIS would still need a separate obligation/step-up layer.

**Decision:** keep Cedar behind the same future `PolicyEngine` interface. Prefer OPA initially because the structured decision/obligation model maps more directly to Step 3 and OPA is operationally mature.

Sources:

- https://docs.cedarpolicy.com/auth/authorization.html
- https://docs.cedarpolicy.com/schema/json-schema.html
- https://pypi.org/project/cedarpy/

### 11.3 Casbin — REJECT FOR INITIAL STEP 3

Casbin/PyCasbin is a good Python-native access-control framework with RBAC/ABAC support. It is simpler operationally, but Step 3 needs richer, explainable decision obligations and exact-action step-up semantics beyond ordinary subject/object/action authorization.

**Decision:** do not select Casbin for v1. It remains a lower-complexity fallback if OPA proves operationally unjustified.

## 12. Exact-action authorization principles

OWASP's Transaction Authorization guidance maps closely to JARVIS's needs:

- the user should see/understand significant transaction data;
- authorization should be distinct from ordinary authentication;
- authorization should be unique per operation;
- material transaction changes invalidate prior authorization;
- state transitions must not be skippable;
- a final control gate must verify authorization immediately before execution;
- credentials/receipts should expire quickly.

**Decision candidate:** every consequential JARVIS action becomes an immutable `ActionProposal` with a canonical hash. Any material parameter change creates a new proposal and invalidates the old approval. Approval is one-time and is revalidated at the execution boundary.

Source:

- https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html

## 13. Sensitive storage

### 13.1 DPAPI — ADOPT FOR USER-SCOPED KEY SEALING

Windows DPAPI normally protects data so only the same Windows user on the same machine can decrypt it; `CryptUnprotectData` also performs an integrity check. `CRYPTPROTECT_LOCAL_MACHINE` is inappropriate for biometric templates because it allows any user on the machine to decrypt.

**Decision candidate:** use user-scoped DPAPI to seal JARVIS profile/audit encryption keys, not to create a false claim that same-user malware is defeated.

Sources:

- https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata
- https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata

### 13.2 Envelope encryption — ADOPT

OWASP recommends minimizing sensitive storage, separating encryption keys from data, and using distinct data-encryption and key-encryption keys.

**Decision candidate:** sensitive biometric templates are encrypted with a randomly generated profile DEK using AES-GCM; the DEK is sealed using user-scoped DPAPI. Deleting the sealed profile DEK enables practical crypto-shredding of residual encrypted template pages/backups.

Source:

- https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html

### 13.3 SQLite — ADOPT AS LOCAL STORE

SQLite is sufficient for a single-PC owner profile and audit store. `PRAGMA secure_delete` can overwrite deleted SQLite content, while `VACUUM` can remove residual deleted content; SSD/file-system realities mean this is defense-in-depth, not a guaranteed physical erase.

**Decision candidate:** SQLite for structured local state, application-level encryption for sensitive fields, restrictive filesystem permissions, and explicit retention/purge logic.

Source:

- https://www.sqlite.org/pragma.html#pragma_secure_delete

### 13.4 SQLCipher — DEFER

SQLCipher Community Edition uses a BSD-style license with attribution and provides whole-database encryption. It is credible but adds another native dependency and does not eliminate the need for careful key storage.

**Decision:** do not require SQLCipher initially. Revisit if the threat model later requires transparent whole-database encryption beyond field-level sensitive-data protection.

Source:

- https://www.zetetic.net/sqlcipher/license/

### 13.5 TPM/CNG — OPTIONAL HARDENING

The Windows Microsoft Platform Crypto Provider can create TPM-backed non-exportable keys. This is useful for future audit-signing or higher-value local key protection.

**Decision:** keep a `KeyProtector` boundary that can move from DPAPI to TPM/CNG without changing identity/authority data schemas. Do not make TPM availability a Step-3 v1 blocker.

Sources:

- https://learn.microsoft.com/en-us/windows/security/hardware-security/tpm/how-windows-uses-the-tpm
- https://learn.microsoft.com/en-us/windows/win32/seccertenroll/cng-key-storage-providers

## 14. Audit and operational telemetry

OWASP recommends logging authentication/authorization failures, high-risk administrative actions, privilege/consent changes, sensitive access, and suspicious attempts, while avoiding raw secrets, tokens, passwords, and unnecessary PII. Logs should be protected from unauthorized modification/deletion and should not be retained beyond their purpose.

OpenTelemetry Python currently marks traces and metrics Stable, while logs remain Development.

**Decision candidate:**

- JARVIS `AuditEventStore` is the authoritative security/authority audit trail;
- OpenTelemetry is optional operational tracing/metrics correlation, not audit authority;
- audit events store structured metadata/reason codes and action hashes, never raw audio/video, embeddings, passwords, secrets, or complete sensitive payloads;
- audit integrity should be application-tamper-evident with a chained HMAC if the key-protection implementation passes validation; this does not claim protection against a fully compromised Windows/admin environment.

Sources:

- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- https://opentelemetry.io/docs/languages/python/

## 15. Threat-model methods

Microsoft's STRIDE categories cover spoofing, tampering, repudiation, information disclosure, denial of service, and elevation of privilege. LINDDUN PRO provides systematic privacy analysis over every DFD interaction and is particularly appropriate where accountability/traceability matters.

**Decision candidate:** Step 3 uses one canonical DFD, then runs both STRIDE and LINDDUN PRO over it. The detailed model is in `STEP_3_THREAT_PRIVACY_MODEL.md`.

Sources:

- https://learn.microsoft.com/en-us/azure/security/develop/secure-design
- https://linddun.org/pro/

## 16. Proposed technology stack

| Responsibility | Proposed choice | Decision type | Notes |
| --- | --- | --- | --- |
| Windows session context | WTS/session notifications | WRAP | Context only; lock invalidates trust |
| Strong local verification | Windows Hello `UserConsentVerifier` | ADOPT + WRAP | Exact-action result binding owned by JARVIS |
| Future strong verifier | Win32 WebAuthn/FIDO2 | KEEP AS ADAPTER | Security key/passkey path |
| Face detection/alignment for identity | OpenCV YuNet | ADOPT + WRAP | Run on selected/head crop only |
| Face embedding | OpenCV SFace | ADOPT + WRAP, subject to benchmark | CPU-first; provenance note retained |
| Face accuracy reference | InsightFace buffalo_l | BENCHMARK ONLY | Public weights non-commercial unless licensed |
| Liveness | MediaPipe Face Landmarker randomized challenge | ADOPT + WRAP | Supporting evidence only |
| Passive MiniFASNet PAD | Deferred | REJECT FOR V1 | Weight-provenance uncertainty |
| Speaker embedding | sherpa-onnx + licensed WeSpeaker candidate | BENCHMARK/ADOPT IF PASSES | Local ONNX deployment |
| Speaker accuracy reference | SpeechBrain ECAPA | BENCHMARK | Voice never strong authentication |
| Diarization | NeMo Sortformer | DEFER | Heavy; add only if real overlap requirement |
| Active speaker | LR-ASD/Light-ASD | DEFERRED ADAPTER | Needed only to remove multi-person ambiguity |
| Policy engine | Open Policy Agent | ADOPT + WRAP | Fail closed; structured decisions |
| Policy alternative | Cedar | KEEP AS ALTERNATIVE | Strong schema/auth model |
| Local state/audit | SQLite | ADOPT | Structured + retention |
| Sensitive-data encryption | AES-GCM DEK + user-scoped DPAPI wrapping | ADOPT | No raw biometric retention |
| Future key hardening | TPM/CNG Platform Crypto Provider | DEFERRED ADAPTER | Non-exportable key option |
| Operational telemetry | OpenTelemetry traces/metrics | OPTIONAL | Not audit authority |

## 17. What JARVIS must own

No third-party package is allowed to become the authority boundary. JARVIS owns:

- the canonical identity-evidence schema;
- subject/session lifecycle and freshness;
- deterministic trust derivation;
- action-risk classification;
- immutable action proposal and fingerprint;
- policy-input schema and fail-closed adapter behavior;
- approval state machine;
- exact-action binding and expiry;
- final pre-execution authority gate;
- audit-event schema, retention, and redaction;
- model/version/license manifests;
- privacy controls and enrollment/deletion lifecycle.

The LLM can explain, summarize, recommend, or generate a human-friendly action summary. It cannot set the authoritative subject, trust tier, risk class, approval result, proposal hash, policy decision, or final allow/deny result.

## 18. Rejected shortcuts

The following are explicitly rejected:

- `recognized face -> permission`;
- `recognized voice -> permission`;
- `wake word -> owner`;
- `Windows is unlocked -> owner is speaking`;
- weighted confidence sums where two weak signals become a strong one;
- LLM deciding whether a spoken response is approval;
- reusing a generic session-level "yes" for later actions;
- storing raw camera/audio "for future use";
- silently recognizing/persistently profiling every visible bystander;
- fail-open behavior when a policy engine, identity sensor, verifier, or audit dependency is unavailable;
- allowing normal runtime tools to modify authority policy, disable audit, export biometric templates, or self-authorize.

## 19. Research conclusion

Step 3 should be a **governance layer**, not a biometric-login feature.

Natural recognition comes from local face/speaker evidence, but only deterministic JARVIS rules can translate fresh evidence into bounded trust. Persistent/external or dangerous actions require action-specific consent, and critical operations step up to Windows Hello/FIDO2. Policy evaluation remains outside the LLM, and every consequential decision produces a privacy-aware audit event.

The concrete trust tiers, action-risk matrix, state machines, degraded behavior, schemas, and validation gates are defined in the accompanying architecture proposal. No technology in this record is accepted as implemented architecture until the user explicitly approves the proposal and the normal implementation/validation/human-acceptance lifecycle completes.
