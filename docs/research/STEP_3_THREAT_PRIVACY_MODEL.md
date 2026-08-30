# Step 3 — Security and Privacy Threat Model

**Status:** PROPOSED RESEARCH ARTIFACT — NOT APPROVED — NOT IMPLEMENTED  
**Method:** STRIDE + LINDDUN PRO over a shared data-flow model  
**Date:** 2026-08-30

This document deliberately assumes that face recognition, voice recognition, and ambient presence evidence are spoofable. The architecture must remain safe when those signals are wrong, stale, missing, or adversarially manipulated.

## 1. Security objectives

Step 3 must preserve:

- **identity integrity:** JARVIS does not silently bind evidence from different people/sessions into one owner identity;
- **authorization integrity:** only JARVIS-owned policy/approval state can permit a consequential action;
- **transaction integrity:** approval applies to the exact material action that was presented;
- **confidentiality:** raw biometric media, templates, secrets, and private action payloads are minimized and protected;
- **availability with safe degradation:** loss of identity or policy services reduces capability instead of causing unsafe guesses;
- **accountability:** consequential decisions are reconstructable from redacted audit metadata;
- **privacy:** the system does not become a general-purpose surveillance or bystander-profiling system.

## 2. Explicit trust assumptions

### Trusted for the Step-3 threat boundary

- Windows kernel, Windows security subsystem, and the current logged-on user account are not fully compromised.
- The JARVIS authority process and its code loaded from the protected repository are trusted to enforce its own state machine.
- Local cryptographic primitives and the Windows Hello/FIDO2 platform are functioning as documented.
- The physical Pocket 3 and microphone may provide misleading or replayed input; they are **not** roots of trust.

### In scope

- nearby people attempting to operate JARVIS;
- TV/movie/phone audio causing wake or commands;
- recorded or synthesized/cloned owner voice;
- printed face photos, phone-screen photos, ordinary replayed video, and basic face presentation attacks;
- multiple visible/speaking people and identity-association ambiguity;
- stale face/voice/session evidence;
- Windows lock/unlock/session-switch transitions;
- LLM hallucination or prompt injection claiming that approval occurred;
- compromised or buggy future capability attempting to skip policy;
- transaction-parameter mutation after approval;
- replay of old approval receipts;
- policy engine outage/malformed output;
- audit/log tampering by processes that do not fully control the trusted Windows/JARVIS security boundary;
- accidental privacy leakage through logs, diagnostics, crash reports, or retained media.

### Not claimed to be prevented

- a fully compromised Windows kernel/admin environment that can replace JARVIS code, patch process memory, or control Windows Hello internals;
- invasive hardware implants or physical replacement of trusted platform components;
- nation-state-grade real-time biometric injection against the entire trusted endpoint;
- formal legal/regulatory compliance certification;
- formal NIST biometric-conformance claims from small local benchmarks.

High-risk action safety therefore rests on the trusted platform verifier and exact-action gate, not on pretending commodity sensors are unspoofable.

## 3. Canonical Step-3 DFD

```text
External entities
-----------------
Owner / unknown person / nearby attacker
Windows OS + Windows Hello / FIDO2
Pocket 3 camera
Local microphone
Future governed capability executor

                 camera frames                 mic PCM / turns
Pocket 3 --------------------------+     +------------------------- Microphone
                                   |     |
                                   v     v
                          +-----------------------+
                          | Identity Sensors      |
                          | - face embedding      |
                          | - liveness            |
                          | - speaker embedding   |
                          | - active speaker opt. |
                          +-----------+-----------+
                                      |
                                      | typed ephemeral evidence
                                      v
Windows session context ---> +---------------------+
                             | Identity Session /  |
                             | Trust Evaluator     |
                             +----------+----------+
                                        |
                                        | trust state
                                        v
LLM/request ---> immutable ActionProposal ---> RiskClassifier
                                        |             |
                                        +------v------+
                                               |
                                      +--------+--------+
                                      | AuthorityService |
                                      | + PolicyEngine   |
                                      +---+----------+---+
                                          |          |
                                 approval |          | audit
                                          v          v
                                 ApprovalService   AuditEventStore
                                  |        |
                         spoken exact     StrongVerifier
                         confirmation     Windows Hello/FIDO2
                                  \        /
                                   \      /
                                    v    v
                               AuthorityDecision
                                      |
                               final revalidation
                                      |
                                      v
                         Future governed executor
```

### Trust boundaries

1. **Sensor boundary:** camera/microphone data enters from spoofable physical channels.
2. **Provider/model boundary:** third-party models produce scores, not authority.
3. **LLM boundary:** model output is untrusted advisory content.
4. **Policy boundary:** OPA/other engine is a replaceable decision component and can fail/unavailable/misconfigure.
5. **Windows verifier boundary:** platform verification is stronger than ambient evidence but its result still has to be bound by JARVIS to one action proposal.
6. **Storage boundary:** profile/audit files can be read or modified by local processes unless protected.
7. **Execution boundary:** no side effect is permitted before a final authority revalidation immediately before execution.

## 4. STRIDE threat analysis

| ID | Category | Threat | Required mitigation | Residual / degraded behavior |
| --- | --- | --- | --- | --- |
| S-01 | Spoofing | Printed owner face is shown to camera | Face match never grants authority; active randomized liveness required for T2 | Failure leaves identity candidate/unverified |
| S-02 | Spoofing | Owner photo/video displayed on phone/TV | Randomized challenge, temporal track continuity, no single-frame elevation | Advanced real-time attacks still require strong verifier for critical action |
| S-03 | Spoofing | Recorded owner voice is played | Voice never authenticates; replay-like evidence cannot elevate to T3 | Voice can be ignored without blocking strong verification |
| S-04 | Spoofing | Synthetic/cloned owner voice | Same as S-03; optional spoof detector is advisory only | High-risk path unaffected because Windows Hello/FIDO2 required |
| S-05 | Spoofing | Nearby person says "yes" during approval | Spoken approval accepted only in bounded pending state, with sufficient owner trust and no speaker ambiguity | Ambiguity escalates to strong verifier |
| S-06 | Spoofing | Recognized owner is visible while another person speaks | Do not merge face + voice by time coincidence; require active-speaker binding when multi-person association matters | Without ASD, spoken consequential approval is disabled/escalated |
| S-07 | Spoofing | TV voice triggers wake or ordinary request | Wake remains activation only; T0 conversation allowed, protected actions fail authority gate | False conversation activation is nuisance, not permission |
| S-08 | Spoofing | Old face/voice evidence is reused after person leaves | Evidence TTL + track/session continuity + monotonic freshness | Trust decays automatically |
| S-09 | Spoofing | Windows account is unlocked but another person is at PC | Windows session is context only; not owner proof | Private/consequential actions require fresh owner evidence or strong verifier |
| S-10 | Spoofing | Virtual/replaced camera feed | Device identity/provenance can be telemetry but not trusted authority | Critical actions still require Windows verifier |
| T-01 | Tampering | Action parameters change after user approval | Immutable canonical proposal hash; any material change creates new proposal/receipt | Old receipt invalid |
| T-02 | Tampering | Capability tries TOCTOU substitution at execution | Final pre-execution hash/policy/approval revalidation | Deny and audit mismatch |
| T-03 | Tampering | Policy files are modified to allow more | Protected-repo workflow; policy version/hash; `opa check`; policy changes are R5/dev-only | Runtime refuses invalid/unexpected policy version |
| T-04 | Tampering | Policy engine returns malformed/undefined output | Strict schema validation; fail closed | Deny with dependency reason |
| T-05 | Tampering | Biometric template DB modified | AEAD-encrypted template payload, model/version metadata, integrity failure = unusable template | Re-enrollment required |
| T-06 | Tampering | Audit records edited/deleted | Restricted file ACL; optional chained HMAC; audit verification command/tests | Do not claim resistance to fully compromised same-user/admin process |
| T-07 | Tampering | LLM emits fabricated trust/approval fields | LLM types cannot be converted directly to authority types; authoritative values generated only by deterministic services | Fabricated claim remains text only |
| R-01 | Repudiation | User disputes a consequential action | Store proposal hash, material summary digest, approval method, policy version, timestamps, outcome | Audit is accountability evidence, not legal non-repudiation |
| R-02 | Repudiation | System cannot explain denial/step-up | Stable reason codes + policy diagnostics + evidence freshness summaries | Avoid exposing sensitive biometric details unnecessarily |
| I-01 | Information disclosure | Raw camera frames are retained | Memory-only processing; no default recording; immediate crop/frame release | Debug capture requires explicit dev mode and separate consent |
| I-02 | Information disclosure | Raw microphone/audio is retained | Identity audio tap is memory-only; discard after embedding/turn | No default speaker-training recording |
| I-03 | Information disclosure | Face/voice embeddings leak | Encrypt template payloads; single-owner minimal template set; no bystander templates | Embeddings remain sensitive biometric material |
| I-04 | Information disclosure | Secrets/private payloads appear in logs | Structured redaction; audit stores hashes/summaries/reason codes, never tokens/passwords/full sensitive payload | Tests inspect log/audit fixtures for leakage |
| I-05 | Information disclosure | Identity data sent to cloud model/provider | Face/speaker/liveness run locally; identity evidence not placed in LLM prompt by default | Human-readable identity state can be minimized to role/trust facts if necessary |
| I-06 | Information disclosure | Bystander faces become persistent profiles | Step-3 v1 has only OWNER + ephemeral UNKNOWN; unknown embeddings are never persisted | Guest enrollment is future explicit feature only |
| D-01 | DoS | Camera unavailable/overheated | Identity degrades; ordinary nonsensitive conversation remains; no sensor-based trust | Strong verifier may still enable an exact critical action if policy permits |
| D-02 | DoS | Microphone/speaker verification unavailable | Voice evidence omitted; never fail open | Camera/Hello or T0 conversation continues |
| D-03 | DoS | OPA sidecar crashes or times out | Hard timeout + fail closed; supervisor/health diagnostic | Protected actions denied, conversation remains available |
| D-04 | DoS | Windows Hello unavailable/not configured/busy | Explicit verifier result; do not substitute weak biometrics | R4 actions denied; user gets truthful setup/unavailable message |
| D-05 | DoS | Audit DB is full/unwritable | Protected action gate treats required-audit failure as deny for R3/R4; health alert | Routine T0 conversation may continue without sensitive side effects |
| D-06 | DoS | Repeated spoof/verification attempts | Backoff/rate limits; rely on Hello retry limits for platform verifier | No automatic weakening of requirements |
| E-01 | Elevation | Capability self-authorizes | Capability executor receives only signed/validated AuthorityDecision token/receipt from AuthorityService | Missing/invalid decision = no execution |
| E-02 | Elevation | LLM chooses lower risk class | RiskClassifier is deterministic JARVIS code; policy may only raise risk/requirements, never let LLM lower them | Model risk labels are advisory only |
| E-03 | Elevation | Attacker downgrades strong verifier to spoken "yes" | Approval method is policy output tied to risk class; no client-selected downgrade | Deny downgrade attempt and audit |
| E-04 | Elevation | Old approval receipt is replayed | One-time nonce/proposal ID, short expiry, consumed-at-execution flag | Replay denied/audited |
| E-05 | Elevation | User/session changes after approval | Bind receipt to identity session + Windows session; revalidate before execution | Session transition cancels pending/approved actions |
| E-06 | Elevation | Runtime disables audit/policy/identity checks | Those operations are R5 developer-only and unavailable to normal capability runtime | Code/repo changes require protected dev workflow |
| E-07 | Elevation | Malformed policy input omits a restrictive field | Typed schema, required fields, default deny on serialization/validation failure | Deny and surface internal diagnostic |

## 5. LINDDUN privacy analysis

LINDDUN PRO is applied to the same DFD so privacy threats are considered for every send/transfer/receive interaction, not just the database.

| Category | Privacy threat | Design response |
| --- | --- | --- |
| Linkability | Stable biometric identifiers make sessions linkable beyond what is needed | Keep raw evidence ephemeral; one local owner profile; audit uses session/action IDs rather than embedding values |
| Linkability | Unknown people become linkable across camera sessions | Never persist unknown embeddings/face crops; ephemeral unknown IDs expire with session/track |
| Identifiability | Stored embeddings reveal that a specific person is enrolled | Encrypt biometric template payload; restrict profile metadata; do not expose template inventory to LLM/tools |
| Identifiability | Logs state the owner's name for every presence event | Audit stores `OWNER` role/subject ID where sufficient; avoid unnecessary real-world names |
| Non-repudiation | Overly detailed logs create an unnecessary permanent behavior history | Audit only consequential security/authority events; bounded retention; do not store full conversation by default |
| Detectability | System state reveals whether owner is home/present | Presence/identity state stays local and is not exposed externally unless an explicit future capability is authorized |
| Disclosure | Raw frames/audio leak through diagnostics/crash paths | No disk recording by default; sanitize exception/context data; dev capture is explicit and visibly enabled |
| Disclosure | Biometric template file is copied | AES-GCM encrypted template data; profile key sealed to Windows user via DPAPI |
| Disclosure | Audit includes message body, file contents, secrets, recipient private data | Store minimal material summary/digest and redacted identifiers according to event type |
| Unawareness | User does not realize enrollment/identity processing is happening | Enrollment is an explicit local flow with purpose, modalities, retention, delete/re-enroll explanation |
| Unawareness | Bystanders are silently enrolled | Impossible in v1 data model: only explicit OWNER enrollment may persist biometric material |
| Unawareness | Liveness challenge is mistaken for strong authentication | UI/voice semantics call it identity/liveness evidence, not security verification; critical actions visibly invoke Windows Hello |
| Non-compliance | Model/data licenses are ignored | Each model has provider/model ID, checksum, version, source, license/provenance note; production promotion blocks unknown license status |
| Non-compliance | Data retained indefinitely "just in case" | Explicit retention policy and purge job/tests; no raw media retention |
| Non-compliance | User cannot remove biometric profile | Strongly verified delete flow plus crypto-shredding of profile key and DB cleanup |

## 6. Data minimization and retention schedule

The following is the proposed default. Retention is an explicit policy setting and may be made **shorter**, not silently extended by model/provider code.

| Data | Default persistence | Retention | Notes |
| --- | --- | --- | --- |
| Full camera frames | none | in-memory frame lifetime only | Existing vision runtime owns capture; no Step-3 recorder |
| Identity face crop | none | discard immediately after embedding/liveness result | Never written to disk by production path |
| Raw microphone PCM for identity | none | discard after turn/embedding extraction | Existing audio owner remains sole mic owner |
| Unknown-person face embedding | none | memory TTL/session only | Never becomes a profile |
| Owner face template | encrypted | until delete/re-enroll/model migration | Store minimal embedding centroids/templates, not source images |
| Owner speaker template | encrypted | until delete/re-enroll/model migration | No source audio by default |
| Active `IdentityEvidence` | none | seconds/minutes in memory | Freshness encoded; not canonical long-term memory |
| Strong-verifier result | metadata only | receipt lifetime in memory; audit summary 90 days | No PIN/biometric data is visible to JARVIS |
| Approval receipt | metadata | consumed immediately; audit summary 90 days | One-time proposal-bound receipt |
| Security/authority audit events | yes | 90 days default | Configurable; redacted structured metadata |
| Routine debug logs | yes | 7 days default | Not authoritative audit |
| Full transcripts | not Step-3 audit data | existing conversation policy only | Do not duplicate into audit |
| Model benchmark media | separate explicit dev artifact | delete after benchmark unless deliberately retained | Never production default |

### Deletion caveat

SQLite `secure_delete`/`VACUUM` is useful defense in depth, but SSD/filesystem wear-leveling prevents a strong physical-erasure guarantee. Sensitive profile payloads therefore use per-profile envelope encryption. Destroying the sealed profile DEK makes residual encrypted copies cryptographically unusable within the stated threat model.

## 7. Enrollment threat model

Enrollment is one of the highest-value operations because poisoning it makes future recognition wrong by design.

Required controls:

1. Strong Windows Hello/FIDO2 verification before creating, replacing, exporting, or deleting OWNER templates.
2. Only one persistent OWNER identity in Step-3 v1.
3. Explicit modality selection: face and/or speaker corroboration.
4. Face enrollment performs live randomized challenge before accepting samples.
5. Capture multiple quality-gated samples across moderate pose/lighting variation.
6. Store only embeddings/centroids plus model/version/calibration metadata; raw captures are discarded.
7. Re-enrollment is a replace operation; old and new template generations are not silently mixed.
8. Model-version changes require explicit migration/re-enrollment if embeddings are incompatible.
9. Template deletion destroys the profile DEK, deletes rows, checkpoints/cleans DB as appropriate, and records a redacted deletion audit event.
10. No conversational model/tool may call enrollment mutation without the authority service and strong-verifier requirement.

## 8. Multi-person privacy/safety rule

Step 3 must not solve uncertainty by collecting more data indefinitely.

When multiple people are visible:

- each vision track remains a separate ephemeral subject hypothesis;
- recognized owner face evidence attaches only to the matching track;
- a speaker match remains an audio-speaker hypothesis, not automatically the same person;
- unless an active-speaker provider links the turn to the owner track, spoken approval for R3/R4 actions is not accepted;
- no unknown person is assigned a persistent identity;
- ordinary T0 conversation may continue without exposing owner-private data.

This intentionally prefers a little extra friction over a confused-deputy failure.

## 9. Degraded-mode matrix

| Failure / uncertainty | Safe behavior |
| --- | --- |
| Face provider unavailable | No face-derived identity elevation; voice/context remains advisory; strong verifier still available |
| Liveness provider unavailable | Face match may support cosmetic personalization only; cannot create T2 for protected actions |
| Speaker provider unavailable | No speaker corroboration; do not block strong verifier |
| Multiple people, no active-speaker association | No spoken consequential approval; escalate to strong verifier |
| Camera unavailable | Nonsensitive conversation allowed; protected private reads/actions require other permitted proof or deny |
| Windows session locked/disconnected | Immediately drop to T0, cancel pending approvals, invalidate action receipts |
| Windows Hello not configured | R4 operations denied with truthful setup guidance; never fall back to face/voice |
| Policy engine timeout/crash | Protected action denied; conversation remains available |
| Policy output malformed/undefined | Deny + audit/diagnostic |
| Audit store unavailable | R3/R4 action denied because accountable execution cannot be recorded |
| Biometric template fails integrity/decryption | Treat modality as unavailable; request re-enrollment after strong verification |
| Model version changed unexpectedly | Refuse incompatible template comparison; no silent threshold/model migration |
| Evidence is stale | Recompute/step up; never extend TTL because user is inconveniently positioned |
| Approval expires | New approval flow required |
| Proposal changes after approval | Old receipt invalid; present the changed action again |
| LLM says user approved but deterministic gate did not receive valid receipt | Ignore model claim; deny |

## 10. Audit-event security boundary

The authoritative audit trail is not the normal Python log stream.

Minimum event families:

- identity session created/invalidated;
- evidence state transition summaries (not raw embeddings);
- liveness challenge started/result;
- strong verification requested/result;
- policy decision and policy version/hash;
- approval requested/granted/denied/expired;
- proposal mutated/invalidated;
- final authority allow/deny;
- execution started/completed/failed for later governed capabilities;
- enrollment/re-enrollment/deletion;
- policy/security-configuration change attempts;
- audit integrity/retention failures.

Every event includes an event ID, monotonic/wall-clock time, session ID, proposal ID/hash where relevant, stable reason codes, component/model/policy version, and redacted outcome metadata.

Never include:

- raw camera/audio;
- biometric vectors;
- Windows PIN/Hello biometric information;
- passwords, API keys, access tokens;
- unredacted secrets;
- full sensitive document/message content merely for audit convenience.

## 11. Privacy-visible controls

Step 3 should expose explicit local controls (CLI initially; later UI/voice only through authority):

- `identity status` — which modalities are configured, not raw templates;
- `identity enroll-owner` — strong-verifier-gated;
- `identity delete-owner` — strong-verifier-gated;
- `identity clear-session` — immediately forget ephemeral evidence;
- `audit status` — retention/integrity health;
- `audit purge` — policy-controlled; cannot selectively delete inconvenient security events without authorization;
- `identity diagnostics` — off by default; does not reveal embeddings.

A visible indicator/log line should state when a deliberate enrollment or liveness challenge is active. Passive continuous bystander profiling is out of scope.

## 12. Threat-model completion criteria

Before Step 3 can be human-accepted:

- every DFD boundary above has automated failure-path tests where feasible;
- each STRIDE threat has either a tested mitigation or an explicit accepted residual risk;
- privacy tests confirm raw media and embeddings do not enter ordinary logs/audit;
- lock/unlock/session-switch behavior is verified on the real Windows machine;
- photo/screen/video replay liveness attacks are exercised against the Pocket 3;
- voice playback/TV/clone-style attacks are exercised as evidence failures, without any path to strong authority;
- exact-action mutation/replay/expiry/TOCTOU tests pass;
- OPA unavailable/malformed-policy behavior is demonstrably fail closed;
- Windows Hello cancel/not-configured/busy/failure paths do not downgrade;
- audit retention/redaction/integrity behavior is tested;
- human acceptance includes both low-friction ordinary interaction and deliberate high-risk friction.

This threat model must be updated if Step 3 later adds guest identities, cloud biometric services, smart glasses, mobile companion devices, passive world awareness, or remote execution. Those additions introduce new trust boundaries and are not silently covered by this model.
