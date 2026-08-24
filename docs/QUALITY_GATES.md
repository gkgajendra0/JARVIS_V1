# JARVIS V1 Quality Gates

These are universal completion rules for major JARVIS product slices. Individual steps may add stricter criteria in `CURRENT_PLAN.md`.

A step is not `DONE` merely because code exists or unit tests pass.

## 1. Scope Gate

- The implementation matches the approved active slice.
- Explicit non-scope remains unimplemented.
- No unrelated technology or future-capability detour has been smuggled in.
- No old-JARVIS runtime dependency has been introduced.

## 2. Ownership and Architecture Gate

- Each responsibility has one authoritative owner.
- No duplicate conversation/context/memory/authority state has been introduced.
- Provider-specific SDK types do not leak into core domain/state without a deliberate accepted reason.
- New external mechanics have a replacement boundary where practical.
- No giant composition module or broad hidden global state has been introduced.
- `CURRENT_ARCHITECTURE.md` reflects only accepted running architecture.

## 3. Automated Test Gate

As appropriate to the slice:

- unit tests cover important domain contracts;
- integration tests cover real subsystem boundaries;
- failure/timeout/malformed-provider paths are tested;
- regression tests protect previously accepted behaviour;
- import/startup safety remains valid;
- tests prove unauthorized execution cannot occur where authority is involved.

## 4. Truthfulness Gate

- JARVIS never reports completion when execution did not complete.
- Failure, partial completion, unavailable providers, stale information, and unverified results are represented truthfully.
- Fallback behavior preserves the original user intent instead of answering a nearby question.
- Current/fresh claims have source/freshness evidence when the product slice requires it.

## 5. Authority and Safety Gate

For any slice with reads/actions:

- low-risk reads remain bounded;
- writes/external/destructive actions use the appropriate permission/approval level;
- approval is bound to the materially relevant action and parameters;
- capabilities cannot self-authorize;
- UI/model/provider cannot bypass JARVIS authority;
- secrets and sensitive payloads are not unnecessarily logged.

## 6. Resilience Gate

When applicable:

- provider/network/audio/device failures are handled without corrupting canonical JARVIS state;
- resources are cleaned up on shutdown/cancellation;
- fallback/degraded behavior is explicit;
- recovery does not leave the runtime stuck in an invalid state;
- rollback/disable path exists for newly introduced capability authority.

## 7. Performance Gate

Each active step defines relevant measurable thresholds before implementation when performance matters.

Possible measures include:

- perceived voice latency;
- turn-start/end responsiveness;
- model/provider latency;
- memory retrieval latency;
- CPU/RAM/GPU use;
- startup time;
- capability execution latency.

Do not optimize against imaginary requirements; measure the user-critical path for the active slice.

## 8. Human Acceptance Gate

The user must be able to use the feature normally, not only through synthetic tests.

The active plan should define concrete human acceptance scenarios. A major slice remains incomplete until those scenarios are accepted or explicitly waived with a documented reason.

## 9. Documentation Reconciliation Gate

Before a major step is marked `DONE`:

- `CURRENT_PLAN.md` reflects the final accepted state;
- `CURRENT_ARCHITECTURE.md` reflects the architecture that actually exists;
- `ROADMAP.md` marks the step correctly;
- `PRODUCT.md` is updated only if permanent product intent changed;
- a research record exists if a major technology selection required research;
- an ADR exists if a major architecture/technology decision needs durable reasoning.

Do not create duplicate final/historical copies. Git history is the archive.

## 10. Cleanup Gate

- rejected replacement implementations are removed when safe;
- dead scaffolding is not retained just in case;
- temporary debug code/data is removed or clearly excluded;
- abandoned experiments do not remain on the normal runtime path;
- no unrelated generated artifacts are committed.

## 11. Git Gate

A coherent accepted product slice should end in a clean, reviewable Git checkpoint.

The normal sequence is:

```text
Planning
-> Research when required
-> Architecture decision
-> Implementation
-> Automated validation
-> Human validation
-> Documentation reconciliation
-> Review diff
-> Commit
```

Commit/push policy can be tightened for consequential future self-modification work, but normal development should remain reviewable and deliberate.
