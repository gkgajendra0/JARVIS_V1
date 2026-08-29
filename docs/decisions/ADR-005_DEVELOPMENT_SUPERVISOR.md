# ADR-005 — Owner-Approved Development Supervisor

- **Status:** Accepted
- **Date:** 2026-08-30
- **Scope:** Development workflow only

## Context

JARVIS development needed a faster update loop without returning to the old pattern of uncontrolled self-modification, manual stop/pull/restart repetition, or allowing the conversational model to authorize changes to its own runtime.

The target behavior was:

- keep JARVIS running while checking for development updates;
- detect remote changes automatically;
- never pull or restart until the owner explicitly approves;
- ask through JARVIS voice rather than a silent terminal prompt;
- keep approval interpretation outside LLM/model authority;
- stop the running voice/vision child cleanly before changing code;
- accept only fast-forward repository updates;
- recover to the previous working version if the new child cannot become healthy;
- keep normal `jarvis-voice` free of automatic Git authority;
- use a repository-side gate so the normal update channel is protected by automated validation.

The current development machine is Windows and the accepted JARVIS runtime owns realtime voice, wake word, camera/GPU vision, and Pocket 3 PTZ resources. In-process module reload therefore has meaningful resource and state hazards.

## Decision

Adopt a separate long-running **`jarvis-dev` parent supervisor** around the existing `jarvis-voice` child process.

### Process model

- `jarvis-dev` is the development parent.
- `jarvis-voice` remains the normal user-facing runtime child.
- The parent watches `origin/main` by default.
- A branch override exists only for intentional pre-merge development testing.
- The parent never performs an automatic crash-restart loop.

### Repository/update model

The supervisor:

1. fetches the watched remote branch without changing the worktree;
2. compares local and remote SHAs;
3. refuses dirty worktrees, wrong branches, and non-fast-forward updates;
4. requests one explicit spoken owner decision;
5. on approval, requests a clean in-process child shutdown;
6. performs `git pull --ff-only`;
7. starts the new child;
8. requires an authenticated child-readiness handshake;
9. if readiness fails, resets the worktree to the previous local SHA and restarts that last-known-good version.

The running parent does not replace its own Python code during a child update. Supervisor-code changes become active after the parent itself is restarted.

### Voice approval model

Use a fixed scripted-TTS question rather than asking the realtime model to generate the authorization prompt.

The existing realtime voice path may provide finalized transcription, but deterministic JARVIS code parses the decision. The model does **not** decide whether approval occurred.

Accepted approval semantics:

- a leading explicit Yes or No may include natural, non-contradictory trailing speech;
- contradictory, ambiguous, missing, timed-out, or unavailable responses fail closed;
- only an explicit positive deterministic parse permits the update.

Until Step 3 identity/trust exists, this spoken gate is a development-owner interaction mechanism, not strong biometric authentication.

### Local control channel

Use an authenticated loopback-only supervisor↔voice protocol with a parent-generated random token. The channel supports:

- child hello/readiness;
- update approval request/response;
- clean shutdown request/acknowledgement.

This avoids granting the conversational model direct process/Git authority.

### Distribution gate

Use protected GitHub `main` as the normal update channel.

The repository `Main safety gate` ruleset requires:

- pull-request flow;
- strict `ruff` and `pytest` status checks;
- up-to-date branch before merge;
- deletion protection;
- non-fast-forward protection;
- no bypass actors.

The supervisor detects that a `main` commit exists; it does not independently reproduce GitHub CI semantics locally.

## Alternatives Considered

### 1. Manual terminal pull/restart only

**Rejected as the primary development loop.** Safe but unnecessarily repetitive and does not provide the intended JARVIS-like update experience.

### 2. Terminal Yes/No prompt inside the supervisor

**Rejected as the final UX.** It proved the update gate mechanically but did not let JARVIS ask the owner directly.

### 3. Let the realtime LLM generate the prompt and decide approval

**Rejected.** This would mix model interpretation with authority, and the current Gemini realtime path also proved incompatible with `AgentSession.generate_reply()` for this proactive generation use case.

### 4. In-process hot module reload

**Rejected.** Voice, audio, camera, GPU inference, PTZ, provider sessions, and background tasks make partial in-process replacement significantly harder to reason about than a supervised process restart.

### 5. Automatic pull/restart whenever remote changes

**Rejected.** Remote code must never become active without explicit owner approval.

### 6. Restart updated code without readiness/rollback

**Rejected.** A successful Git pull does not prove the new runtime is healthy. Last-known-good recovery is required for a safer development loop.

### 7. Poll arbitrary feature branches in normal use

**Rejected.** Feature-branch overrides are only a pre-merge testing mechanism. Protected `main` is the normal development distribution channel.

## Why This Choice

This design separates three concerns cleanly:

- **GitHub/protected `main`** decides what code is eligible to become the normal development version;
- **the human owner** decides when an eligible update may be applied to the running machine;
- **deterministic JARVIS supervisor code** performs shutdown, fast-forward update, readiness verification, and rollback.

The conversational model remains useful for voice/transcription but is not an authorization authority.

A process supervisor also provides a clearer resource-lifecycle boundary than in-process reload for the current Windows voice/vision/PTZ stack.

## Consequences and Tradeoffs

### Benefits

- substantially faster development iteration;
- explicit owner control remains intact;
- no silent self-update;
- model cannot self-authorize an update;
- clean resource teardown before replacement;
- failed startup can recover to last-known-good code;
- normal `jarvis-voice` remains free of Git polling unless launched under `jarvis-dev`;
- protected `main` gives one clear update channel with required automated gates.

### Costs / limitations

- the supervisor parent itself requires restart to load supervisor-code changes;
- spoken approval is not identity-verified until Step 3;
- a nearby speaker could potentially say an explicit Yes during development approval today;
- Git/network access remains an operational dependency for updates;
- the readiness handshake proves the child reached the accepted control-ready point, not every possible hardware/provider behavior;
- provider-side approval-session response noise may still appear in logs even though it has no authorization role.

## Replacement Boundary

The development workflow is intentionally separate from product runtime authority.

Replaceable pieces include:

- remote/branch polling strategy;
- scripted TTS provider;
- transcription provider/session implementation;
- readiness criteria;
- future authenticated owner-verification mechanism;
- future release/signing/CI attestation model.

The durable JARVIS semantics are:

- no update without explicit owner approval;
- model/provider cannot grant its own update authority;
- repository state must change safely and predictably;
- failed updates must preserve/recover a known-good runtime where practical;
- development tooling must not silently become normal product authority.

## Reconsider When

Revisit this ADR if any of the following become true:

- Step 3 provides strong verified-owner identity suitable for update approval;
- JARVIS becomes a Windows service and service-manager supervision is preferable;
- signed releases/artifacts replace direct Git worktree updates;
- multiple machines require coordinated version rollout;
- the runtime becomes reliably hot-swappable with demonstrably safe resource isolation;
- GitHub/protected `main` is no longer the development distribution mechanism;
- the supervisor itself becomes part of governed self-repair/self-improvement in later roadmap steps.
