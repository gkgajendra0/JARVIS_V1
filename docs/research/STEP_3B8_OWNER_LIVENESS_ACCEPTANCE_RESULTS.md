# Step 3B.8 — OWNER + Liveness Real-Machine Acceptance Results

Date: 2026-08-30

## Status

**HUMAN ACCEPTANCE COMPLETE FOR THE NON-REDUNDANT 3B.8 SCOPE — T2 REMAINS DISABLED — FINAL RECONCILIATION PENDING**

This document records real Windows + DJI Pocket 3 acceptance evidence for the Step 3B.8 integrated OWNER identity + passive liveness path.

The harness is evidence-only. No result in this document grants T2 authority.

## Subtest 1 — live OWNER normal-use

Command:

```powershell
jarvis-owner-evidence-live --scenario live
```

Result:

```text
scenario = live
windows_session = wts:3
valid_integrated_observations = 300
associated_head_attempts = 361

max_prototype_cosine:
  n = 300
  min = 0.6128
  p05 = 0.6816
  median = 0.7982
  p95 = 0.8435
  max = 0.8779

minifas_real_probability:
  n = 300
  min = 0.9842
  p05 = 0.9974
  median = 0.9998
  p95 = 0.9999
  max = 1.0000

identity_state_counts = {'insufficient': 28, 'owner_candidate': 272}
liveness_state_counts = {'insufficient': 28, 'live': 272}
combined_state_counts = {'insufficient': 28, 'live_owner_candidate': 272}
session_invalidated = False

frames_saved = False
aligned_faces_saved = False
sface_embeddings_saved = False
pad_tensors_saved = False
pad_output_vectors_saved = False
identity_threshold_authoritative = False
live_non_owner_calibration_available = False
face_evidence_grants_T2 = False
STEP_3B8_OWNER_LIVENESS_EVIDENCE = COMPLETE
```

### Interpretation

PASS for the live-OWNER subtest.

- The encrypted enrolled 8-prototype OWNER template loaded successfully and was compatible with the pinned SFace runtime.
- Genuine live OWNER temporal identity reached `OWNER_CANDIDATE` for 272 of 300 integrated observations after temporal warm-up/reset periods.
- Passive MiniFAS liveness reached `LIVE` for the same 272 observations.
- The combined same-session/same-track assessment reached `LIVE_OWNER_CANDIDATE` for the same 272 observations.
- No session invalidation occurred.
- No raw frames, aligned faces, SFace embeddings, PAD tensors, or PAD output vectors were persisted.
- `face_evidence_grants_T2 = False` remained intact.

The 28 `INSUFFICIENT` observations are exactly consistent with two 14-observation temporal warm-up periods. Because both identity and liveness show the same count, this is consistent with one shared freshness-gap reset after the initial warm-up. The current harness does not print an explicit temporal-reset counter, so that reset explanation is an inference from the counts rather than a directly logged event. The fail-closed behavior itself is acceptable; repeated resets in later runs should be monitored for runtime UX impact.

### Threshold note

The live run supports the provisional OWNER-candidate integration floor but does not make it authoritative. The genuine run had:

- raw minimum max-prototype cosine `0.6128`, below the provisional `0.65` temporal OWNER-candidate floor;
- p05 `0.6816` and median `0.7982`;
- temporal fusion nevertheless produced stable `OWNER_CANDIDATE` after valid windows filled.

A consenting live non-owner calibration remains required before OWNER-vs-UNKNOWN thresholds may participate in T2.

## Subtest 2 — Windows session lock invalidation

Command:

```powershell
jarvis-owner-evidence-live --scenario session-lock
```

Human action: after selecting the OWNER track, Windows was locked with the normal Windows lock path.

Result:

```text
scenario = session-lock
windows_session = wts:3
valid_integrated_observations = 0
associated_head_attempts = 0
max_prototype_cosine: n/a
minifas_real_probability: n/a
identity_state_counts = {}
liveness_state_counts = {}
combined_state_counts = {}
session_invalidated = True
frames_saved = False
aligned_faces_saved = False
sface_embeddings_saved = False
pad_tensors_saved = False
pad_output_vectors_saved = False
identity_threshold_authoritative = False
live_non_owner_calibration_available = False
face_evidence_grants_T2 = False
STEP_3B8_OWNER_LIVENESS_EVIDENCE = SESSION_INVALIDATED_FAIL_CLOSED
```

### Interpretation

PASS for Windows-session invalidation.

The harness detected the real WTS lock transition, cleared identity/liveness evidence, failed closed, and terminated the evidence session. The lock happened before integrated observations were accumulated in this particular run; that does not weaken the security result because the tested invariant is that a lock/session transition immediately invalidates the evidence context rather than allowing it to continue or be reused after unlock.

`face_evidence_grants_T2 = False` remained intact.

## Replay-attack acceptance coverage

The user explicitly declined repeating the same phone-photo and phone-video attacks already completed during 3B.7B. Those attacks are therefore not rerun merely to exercise the new wrapper.

The accepted evidence is composed as follows:

1. Real Pocket-3 3B.7B human attack evidence already demonstrated MiniFAS temporal liveness separation:
   - normal-use genuine-live 15-frame minimum `0.9855`;
   - phone-photo 15-frame maximum `0.2229`;
   - prerecorded phone-video 15-frame maximum `0.0000` at reported precision.
2. 3B.8 automated binding tests verify that `OWNER_CANDIDATE + SPOOF` maps deterministically to `SPOOFED_OWNER_PRESENTATION` and does not request an active challenge or grant T2.
3. The 3B.8 real live run verifies the same-track OWNER + MiniFAS integration on the real Pocket 3.

This avoids redundant human attack collection while preserving the security claim actually supported by evidence. It does not claim broader PAD robustness beyond the already tested Pocket-3 attack set.

## Track-loss hardening

During 3B.8 review, one harness gap was found proactively: when the selected runtime target became `None`, the harness previously dropped `current_track_id` but relied on temporal freshness behavior before the evidence windows were cleared.

That was tightened so selected-target loss now immediately:

- discards both temporal identity and liveness windows;
- clears the latest integrated binding;
- stops collection;
- clears the last face rectangle;
- requires a fresh selected target and new evidence window before collection can resume.

The accepted temporal primitives already fail closed on explicit clear and cross-track binding. Automated validation of the hardened exact head is required before final 3B.8 reconciliation.

## 3B.8 acceptance conclusion

Human acceptance evidence now covers the non-redundant real-machine properties:

- real OWNER normal-use integration → PASS;
- real Windows lock/session invalidation → PASS;
- Pocket-3 phone-photo/video PAD attacks → inherited from accepted 3B.7B real-machine evidence rather than rerun;
- same-track spoof mapping, cross-track rejection, co-freshness, provider/session binding, and no-T2 behavior → automated coverage;
- immediate selected-track-loss clearing → hardened in implementation and subject to final automated validation;
- raw biometric persistence → absent in all acceptance output;
- `identity_threshold_authoritative = False` remains explicit because live non-owner calibration is still unavailable;
- `face_evidence_grants_T2 = False` remains explicit throughout.

No authoritative OWNER-vs-UNKNOWN threshold and no T2 trust composition is claimed by Step 3B.8 itself.
