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

## Owner voice failure investigation

Owner Windows verification and all hosted CI passed at 1e32f2f55494. Actual voice smoke did not pass: the first captured run returned two model proposals then rejected them without a reason. Diagnostic commit 85647259290f added only fixed stage/reason codes. Its owner replay showed producer timeouts at the attachment's five-second ceiling. A later standby turn was source-denied as expected outside the reviewed script.

Reproduced fixes:
- A model batch with a goal before its explicitly named new topic failed despite both being source grounded. Move a single new topic before dependent proposals only if every dependent explicitly names that same topic. Unbound/foreign targets still reject atomically. The original live model payload was not logged, so this reproduces a real contract defect, not proof of that original rejected batch's exact contents.
- Cloud lab extraction now has an explicit bounded 20-second deadline propagated through per-session factory, controller and bridge. A real controller test with a 5.1-second asynchronous producer now succeeds; explicit short deadlines still expire. Ordinary attachment defaults remain five seconds. Authorization rechecks, bounded shutdown and epoch fences remain in force.
- Revised reviewed script names the vehicle field and establishes departure before correcting it; supported Hinglish wording exercises the existing conservative paraphrase rule. A complete typed model-fixture sequence passes the real parser and reducer with final vehicle, budget, departure and completed route checked. This is not native model accuracy evidence.
- Rejection diagnostics now include elapsed time and configured deadline without source/payload text. The model prompt states the actual lexical/key/ordering contract.

Verification: 205 focused tests passed in 13.47s, including full revised script, explicit-topic ordering, foreign/unbound rejection, controller deadline propagation and existing cancellation regressions. Independent scoped review found no critical or important issues and independently passed 43 producer/script/attachment tests. Its minor timing wording correction is reflected in the lab guide: cancellation is requested at 20 seconds, not a guarantee that an uncooperative client returns by then. Full local suite attempted; native Gemini/voice acceptance remains required.

Ruling: extend only the lab's async deadline to 20 seconds, the pipeline's existing maximum. Cost: slow inference can hold that observer's bounded queue longer; this is not a latency target or permission to delay voice callbacks. No admission/reducer privacy rule is relaxed.

Lifecycle follow-through: the lab's idle windows now have a 30-second minimum (preserving longer settings), preventing the usual 15-second idle close from canceling extraction before its deadline. Two regression cases verify short settings are raised and longer settings are retained. Explicit standby/close still uses the existing immediate revocation path.
