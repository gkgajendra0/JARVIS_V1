# JARVIS V1 Quality Gates

These are universal completion rules for major JARVIS product slices. Individual steps may add stricter criteria in `CURRENT_PLAN.md`.

A step is not `DONE` merely because code exists or unit tests pass. A deliberately deferred item also does not have to keep a step open forever when its unavailable behavior is explicitly bounded, fails safely, is documented, and does not block the next slice.

## 1. Scope Gate

- The implementation matches the approved active slice.
- Explicit non-scope remains unimplemented.
- Deferred hardening is recorded with its current fail-safe product limitation and reconsideration trigger.
- No unrelated technology or future-capability detour has been smuggled in.
- No old-JARVIS runtime dependency has been introduced.
- Future capability ideas are recorded without automatically replacing the current release.

## 2. Ownership and Architecture Gate

- Each responsibility has one authoritative owner.
- No duplicate conversation/context/memory/authority state has been introduced.
- Provider-specific SDK types do not leak into core domain/state without a deliberate accepted reason.
- New external mechanics have a replacement boundary where practical.
- No giant composition module or broad hidden global state has been introduced.
- Development/repair tooling is not accidentally initialized as normal runtime authority.
- Multiple user-facing capabilities reuse the accepted common execution/authority boundary rather than inventing parallel routers and result contracts.
- `CURRENT_ARCHITECTURE.md` reflects only accepted running architecture.

## 3. Automated Test Gate

As appropriate to the slice:

- unit tests cover important domain contracts;
- integration tests cover real subsystem boundaries;
- failure/timeout/malformed-provider paths are tested;
- regression tests protect previously accepted behaviour;
- import/startup safety remains valid;
- tests prove unauthorized execution cannot occur where authority is involved;
- important legacy failure scenarios relevant to the slice are represented where still applicable.

Repository baseline automation on protected `main` currently requires both:

- `ruff` — formatting and lint;
- `pytest` — the repository unit/regression suite on a clean Ubuntu runner.

A green PR head is necessary but not always sufficient. Hardware/provider/Windows-only behavior still needs slice-specific validation and real human acceptance where CI cannot prove it.

## 4. Truthfulness and Semantic Fidelity Gate

- JARVIS never reports completion when execution did not complete.
- Failure, partial completion, unavailable providers, stale information, and unverified results are represented truthfully.
- Fallback behavior preserves the original user intent instead of answering a nearby question.
- Current/fresh claims have source/freshness evidence when the product slice requires it.
- A source/router/provider classification cannot become a false spoken claim merely because the requested source/capability was unavailable.
- Read-only evidence is not described as though a write/action occurred.
- A deferred capability must be reported as unavailable rather than simulated by a weaker path.

## 5. Authority and Risk Gate

All future capability work must preserve the accepted Step-3 proportional-risk model.

### Low-risk read

Examples: bounded system status, approved file metadata, trusted-source retrieval.

Expected behaviour:

- bounded target/resource scope;
- policy permission;
- usually no repetitive per-turn confirmation when the user has clearly requested the read and the resource class is approved;
- truthful failure if the target/provider is unavailable.

### Reversible local action

Examples: open an approved application, create a note/reminder, adjust an approved setting.

Expected behaviour:

- clear user intent;
- bounded adapter rather than arbitrary shell authority;
- confirmation when ambiguity or meaningful side effects warrant it;
- undo/rollback where technically practical.

### Persistent write or external communication

Examples: send email, modify calendar, edit/move files, submit browser forms.

Expected behaviour:

- separate read/draft/proposal from commit/send/write authority;
- explicit approval bound to the materially relevant target/content/parameters;
- preview/draft-before-commit where practical;
- stronger confirmation when rollback is unavailable;
- if a required actor-binding or trust signal is intentionally not yet accepted, the action remains blocked or uses an explicitly accepted stronger verification path rather than silently weakening the floor.

### Destructive, financial, security-sensitive, or self-modifying action

Examples: destructive deletion, unrestricted shell/installation/security changes, spending/financial commitment, credential-sensitive changes, self-modification.

Expected behaviour:

- separately designed governance;
- exact-action binding;
- strong step-up trust where appropriate;
- backup/dry-run/rollback when applicable;
- remain blocked if the required safety/authority design does not yet exist.

Universal authority rules:

- capabilities cannot self-authorize;
- model/provider/UI cannot bypass JARVIS authority;
- approval-like natural-language text cannot silently activate/install a capability;
- identity evidence is not itself execution permission;
- approval for one materially specific action cannot be reused for a different action;
- secrets and sensitive payloads are not unnecessarily logged.

## 6. Privacy and Data Lifecycle Gate

When a slice touches conversation history, memory, files, email, calendar, provider data, observability, identity, or other personal information:

- collect/persist only data required for the accepted behaviour;
- distinguish temporary session state from durable storage;
- raw audio/full provider payloads/full transcripts are not retained by default without a concrete product reason;
- durable personal memory has a correction/removal path;
- secrets/tokens do not enter normal logs or model-visible context unnecessarily;
- observability stores operational evidence rather than becoming hidden surveillance;
- provider-side retention limitations are understood and not misrepresented as JARVIS-owned deletion guarantees;
- tests avoid embedding real personal secrets or credentials.

## 7. Resilience Gate

When applicable:

- provider/network/audio/device failures are handled without corrupting canonical JARVIS state;
- resources are cleaned up on shutdown/cancellation;
- fallback/degraded behavior is explicit;
- recovery does not leave the runtime stuck in an invalid state;
- rollback/disable path exists for newly introduced capability authority;
- local/offline fallback is not allowed to weaken trust/permission/truthfulness boundaries merely to remain available.

## 8. Performance Gate

Each active step defines relevant measurable thresholds before implementation when performance matters.

Possible measures include:

- perceived voice latency;
- turn-start/end responsiveness;
- model/provider latency;
- memory retrieval latency;
- CPU/RAM/GPU use;
- startup time;
- capability execution latency;
- background monitoring resource usage.

Do not optimize against imaginary requirements; measure the user-critical path for the active slice.

## 9. Human Acceptance Gate

The user must be able to use the feature normally, not only through synthetic tests.

The active plan should define concrete human acceptance scenarios. A major slice remains incomplete until those scenarios are accepted or explicitly waived/deferred with a documented reason and safe product boundary.

Human testing should validate product behaviour, not just that a technical provider responds.

## 10. Documentation Reconciliation Gate

Before a major step is marked `DONE`:

- `CURRENT_PLAN.md` reflects the final accepted state and next active slice;
- `CURRENT_ARCHITECTURE.md` reflects the architecture that actually exists;
- `ROADMAP.md` marks completed/active steps correctly;
- `PRODUCT.md` is updated only if permanent product intent changed;
- a research record exists if a major technology selection required research;
- an ADR exists if a major architecture/technology/deferral decision needs durable reasoning;
- capability status/step mapping remains internally consistent;
- residual limitations that affect future capabilities are explicit;
- accepted development/runtime infrastructure that changes future workflow or authority boundaries is documented rather than left only in PR history.

Do not create duplicate final/historical copies. Git history is the archive.

## 11. Cleanup Gate

- rejected replacement implementations are removed when safe;
- dead scaffolding is not retained just in case;
- temporary debug code/data is removed or clearly excluded;
- abandoned experiments do not remain on the normal runtime path;
- no unrelated generated artifacts are committed;
- compatibility paths are retained only when they still have an explicit product/rollback purpose.

## 12. Final Goal Coherence Gate

A later step must not optimize its own feature while damaging the final Personal Intelligence Runtime.

Before accepting major architecture, ask:

- Does this preserve one coherent JARVIS rather than introduce a second brain/state owner?
- Does it strengthen or preserve replaceability?
- Does it compose with memory, truthfulness, authority, observability, and capability boundaries?
- Can the user still understand what happened and why?
- Will this enable future daily-assistant workflows without forcing parallel architecture?
- Does it keep the user as the final authority over consequential actions and self-modification?

## 13. Git Gate

A coherent accepted product slice should end in a clean, reviewable, protected Git checkpoint.

The normal sequence is:

```text
Planning
-> Research when required
-> Architecture decision
-> Human approval
-> Implementation
-> Automated validation
-> Human validation
-> Documentation reconciliation
-> Review diff
-> PR to protected main
-> Required status checks
-> Merge
-> Post-merge verification when warranted
```

Current repository baseline:

- `main` is targeted by the active `Main safety gate` ruleset;
- changes require pull-request flow;
- `ruff` and `pytest` are strict required status checks;
- the branch must be up to date before merge;
- branch deletion/non-fast-forward changes are blocked by the ruleset;
- no bypass actors are configured.

The development supervisor may detect new `main` commits, but it must not weaken this repository gate or treat model-generated approval as Git authority. Consequential future self-modification work may require even stronger rules, but normal development should remain reviewable, deliberate, and reversible.
