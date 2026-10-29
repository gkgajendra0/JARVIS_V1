# Semantic session wiring implementation plan

Goal: bind each optional routed semantic producer to one canonical voice conversation and a live owner authorization generation. Keep startup disabled until independent privacy admission and source-bound checkpoint authority are supplied.

Architecture: construct producer and binding per voice session, rather than sharing a closure across wakes. Validate canonical turn object identity and unchanged owner authorization immediately before provider dispatch and after inference. Never promote source sensitivity or create owner grants.

Constraints: main stays unchanged; existing memory database and default startup stay unchanged; no automatic replay on a new wake; no plaintext storage.

## Task 1: Session-bound producer
- [x] Add failing tests for foreign/copied source, closed session, missing/rotated authority, classifier failure, restricted source, and rotation during dispatch/inference.
- [x] Add a session-bound routed producer factory using the existing structured client and source-clearance contract.
- [x] Verify semantic producer and pipeline tests plus Ruff.

## Task 2: Per-session controller construction
- [x] Test a per-session component factory: reject mixed direct/factory injection, construct fresh components for each conversation, fail closed on invalid factory output.
- [x] Wire optional per-session components at the canonical accepted-turn bridge; preserve existing direct injection compatibility.
- [ ] Verify full tests where dependencies permit and exact-head hosted CI after branch update.

## Remaining gates
This adapter is not a privacy classifier, a checkpoint write permit issuer, a continuity handoff or a live acceptance result. Those gates must be completed separately before production startup or a real-voice feature test is advertised ready.

## Task 3: Scripted transient integration lab

- [x] Admit only reviewed synthetic utterances; deny appended/unreviewed speech.
- [x] Create a new machine profile without copying memory or keys; redirect audit, deployment, routing and logs.
- [x] Build normal production transport with an explicit session factory and canonical owner approval; learning worker stays off.
- [x] Test grant lifecycle, denied Hello cleanup, settings isolation and environment restoration.
- [x] Add an exact-commit detached Windows launcher and include lab tests in the existing verifier.
- [ ] Whole-suite verification and fresh review; exact-head hosted CI.

Ruling: the first lab observes transient reducer results only. It does not claim checkpoint persistence, model context projection, cross-wake continuity, restart recovery, or general privacy admission. This staged lab narrows what the owner can verify; those acceptance gates remain open.

## Execution ledger

- Tasks 1–2: resumed existing uncommitted implementation and tests against 1763309401bd; no previous test or CI result is claimed for new bytes.
- Task 3: profile module missing on resumption; observed collection failure, added implementation, tests passed. Added RED→GREEN coverage for environment restoration, grant lifecycle and denied-Hello cleanup.
- Fresh reviewer found three important issues: wrong config loader API, inherited biometric-store observers, and successful-Hello startup cleanup. Each reproduced with a failing regression and passed after fixes. Camera identity observers are disabled only in the lab. No deferred minor findings.
- Ruling: preserve the normal production controller and use its private resource references in this explicitly invoked lab adapter; this avoids a new public production startup mode. Cost: controller refactors must update the lab and its integration tests.
- Verification: 192 focused semantic/memory/session/lab tests passed; repository Ruff formatting/lint passed. Full suite attempted; spawned-process tests fail with `psutil.NoSuchProcess` in this execution environment (also reproduced independently). Do not weaken process-identity checks to accommodate the host. Exact-head hosted Linux/Windows CI remains required.
