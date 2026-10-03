# JARVIS Development Engine Control Plane Architecture

Status: **APPROVED DIRECTION / IMPLEMENTATION IN PROGRESS**  
Date: **2026-10-03**  
Scope: **Capability acquisition and governed engineering development**  
Branch: `feat/development-engine-control-plane`

## 1. Why this document exists

This document is the durable architectural anchor for the next JARVIS capability-development work.

The immediate problem is not that JARVIS lacks a capability-acquisition lifecycle. Phase 9H, EngineeringChange, DBOS WorkItems, Phase 5 dependency governance, Phase 7 promotion, Phase 8 package lifecycle, external acceptance, and GICC continuation already provide the major lifecycle primitives.

The problem is that the current development reasoner still uses a costly micro-step loop:

1. JARVIS assembles Work context.
2. The cloud reasoner chooses one bounded next action.
3. JARVIS executes that action.
4. JARVIS assembles context again.
5. The cloud reasoner chooses the next action.

This is safe, but it is inefficient when the primary development intelligence is funded by a shared ChatGPT-plan allowance. Recent owner-machine logs showed that one capability WorkItem carried an estimated 15,910-token legacy context when the C6 projection could represent the same durable history in about 6,916 tokens, and another WorkItem could shrink from about 17,592 to 5,797 estimated tokens. Those savings were measured while C6 was still in shadow mode, so the legacy payload remained active.

The architectural response is therefore not to weaken governance and not to manually build each capability. The response is to separate **engineering management** from **engineering intelligence**.

## 2. Frozen architectural principle

> **JARVIS is the durable engineering manager and control plane. The DevelopmentEngine is the engineering specialist. JARVIS owns execution authority, lifecycle truth, validation, promotion, activation, and recovery.**

The DevelopmentEngine may reason about difficult engineering work, inspect approved context, propose and perform development actions through a narrow governed interface, debug, iterate, and return a typed outcome.

It must not own:

- authoritative WorkItem state;
- EngineeringChange state transitions;
- secrets or PIN persistence;
- direct protected-main mutation;
- arbitrary dependency installation;
- unrestricted host shell access;
- production promotion;
- package activation;
- external-effect authority;
- final acceptance truth;
- merge authority.

## 3. Target architecture

```text
                         OWNER
                           |
                           v
                 +-------------------+
                 |       GICC        |
                 |    Owner Goal     |
                 +---------+---------+
                           |
                           v
        +-----------------------------------------+
        |                 JARVIS                  |
        |        ENGINEERING CONTROL PLANE        |
        |                                         |
        | Goal / Plan / EngineeringChange         |
        | DBOS durable workflow                    |
        | Phase 9 capability acquisition           |
        | Authority / OPA / secrets                |
        | Quota governor                           |
        | Research / architecture gates            |
        | Promotion / activation                   |
        | External acceptance                      |
        +----------------+------------------------+
                         |
                  DevelopmentTicketV1
                         |
                         v
        +-----------------------------------------+
        |           DEVELOPMENT ENGINE            |
        |                                         |
        | Provider-neutral interface               |
        | First implementation: Codex/ChatGPT      |
        | Persistent engineering thread            |
        | Compact development context              |
        +----------------+------------------------+
                         |
                  governed tool calls
                         |
                         v
        +-----------------------------------------+
        |      JARVIS DEVELOPMENT TOOL SURFACE    |
        |                                         |
        | list/search/read repository              |
        | write isolated worktree                  |
        | governed dependency request              |
        | sandboxed tests/static checks            |
        | inspect diff                             |
        | create candidate commit                  |
        | retrieve approved research evidence      |
        +----------------+------------------------+
                         |
                         v
                 DevelopmentResultV1
                         |
                         v
             JARVIS validates canonical truth
                         |
              +----------+----------+
              |                     |
           success                blocker
              |                     |
       CI / promotion        re-research /
       Phase 8 lifecycle     architecture /
       external acceptance   dependency /
                             provider wait
```

## 4. Responsibilities

### 4.1 JARVIS control plane

JARVIS remains responsible for:

- preserving the original owner goal;
- GICC goal and plan lineage;
- detecting capability gaps;
- EngineeringChange creation and stage transitions;
- DBOS durability and restart recovery;
- target/provider availability and quota admission;
- research acquisition and evidence storage;
- architecture approval gates;
- dependency trust, hashes, provenance, and Phase 5 substrate;
- sandbox and worktree creation;
- secrets and typed owner-input handling;
- CI and promotion;
- Phase 8 package admission and lifecycle;
- explicit activation;
- physical/external acceptance;
- rollback/disable evidence;
- final GICC continuation.

### 4.2 DevelopmentEngine

The DevelopmentEngine is responsible only for engineering intelligence inside an authorized development ticket:

- understand the approved architecture;
- inspect relevant source;
- inspect approved research evidence;
- determine implementation details;
- write or modify source through approved development tools;
- request approved dependencies through governed dependency APIs;
- run governed tests;
- interpret failures;
- iterate implementation;
- inspect the resulting diff;
- return a typed completion or blocker.

### 4.3 Owner

The owner should only be required for genuinely owner-only boundaries:

- material architecture approval;
- explicit promotion/activation decisions when policy requires them;
- credentials, pairing PIN, or one-time protected input;
- physical-world confirmation that JARVIS cannot independently read back;
- merge approval under repository governance.

The owner must not be used as a substitute for missing automation. JARVIS must not ask the owner to research protocols, open UIs, run commands, install packages, debug code, or manually test software merely because the capability is missing.

## 5. Provider-neutral DevelopmentEngine boundary

The capability architecture must not hardcode ChatGPT or Codex into Phase 9.

Introduce a provider-neutral boundary:

```python
class DevelopmentEngine(Protocol):
    async def execute(
        self,
        ticket: DevelopmentTicketV1,
        *,
        tools: DevelopmentToolPort,
    ) -> DevelopmentResultV1: ...
```

The first implementation will be the ChatGPT-plan/Codex engine, but future implementations may include a local coding model, another approved cloud coding runtime, or a future JARVIS-native engineering engine.

Provider identity must therefore remain outside the canonical capability lifecycle.

## 6. DevelopmentTicketV1

A development ticket is an immutable, bounded engineering assignment. It should contain only the information necessary to perform the approved stage:

- `ticket_id`
- `work_id`
- `engineering_change_id`
- `goal_id`
- `goal_digest`
- `architecture_artifact_id`
- `architecture_digest`
- exact base repository revision
- exact isolated workspace identity
- required capability operations
- approved dependency/discovery/secret requirements
- bounded research evidence references
- relevant repository context / repo-map slice
- acceptance criteria
- allowed development tool names
- policy/authority constraints
- current attempt number
- deterministic ticket digest

The ticket must not contain plaintext secrets or unnecessary full Work history.

## 7. DevelopmentResultV1

The DevelopmentEngine must return one typed disposition rather than free-form workflow authority.

Initial dispositions:

- `COMPLETED`
- `NEEDS_RESEARCH`
- `NEEDS_ARCHITECTURE_REVISION`
- `NEEDS_DEPENDENCY`
- `BLOCKED_RESOURCE`
- `FAILED`

The result should include:

- ticket identity and digest;
- engine identity/version;
- development thread/session identifier when available;
- summary;
- candidate commit/revision when completed;
- changed-file metadata;
- test/static-check evidence;
- evidence references;
- requested dependency information when relevant;
- architecture-revision reason when relevant;
- provider/resource blocker information when relevant;
- token/usage telemetry when available;
- result digest.

A DevelopmentResult does **not** itself transition EngineeringChange. JARVIS deterministically maps the result into the canonical lifecycle.

## 8. DevelopmentToolPort

The DevelopmentEngine must not receive unrestricted host authority.

The approved tool surface should be narrow and source-owned. It should wrap the development substrate JARVIS already uses.

Initial operations:

- `list_files`
- `search_source`
- `read_file`
- `write_file`
- `run_tests`
- `run_static_checks`
- `inspect_diff`
- `resolve_python_dependency`
- `bind_capability_manifest`
- `record_substrate_verification`
- `commit_candidate`
- `get_research_evidence`
- `get_architecture_context`

The first implementation deliberately does **not** add a second architecture-context
tool: the exact approved architecture is already embedded in the immutable ticket.
Likewise, `run_static_checks` remains a staged follow-up rather than duplicating the
existing diagnostic/static-analysis substrate. The v1 DevelopmentEngine uses
network-disabled sandbox tests before the candidate commit, then the existing GitHub
CI/promotion gates remain the authoritative broader static/quality checks. A direct
development static-check tool should be admitted only by wrapping the existing
source-owned verifier substrate, not by granting Codex shell authority.

The tool implementation must enforce:

- isolated WorkItem worktree;
- allowed paths;
- payload bounds;
- no protected-main writes;
- no arbitrary shell;
- no arbitrary package-manager access;
- no secret persistence;
- dependency provenance;
- sandboxed test execution;
- deterministic tool schemas and typed observations.

## 9. First DevelopmentEngine implementation

The first implementation should use the official OpenAI Codex Python SDK when available and admitted.

Research basis:

- the SDK supports synchronous and asynchronous clients;
- `AsyncCodex` is the preferred integration path for an async host;
- threads can be started and resumed;
- turn results expose token usage;
- the SDK can run with read-only sandboxing and explicit approval policy;
- Codex app-server can use a ChatGPT-plan OAuth access token;
- stable SDK releases install a corresponding pinned Codex runtime.

Important security decision:

> Native Codex workspace write access is not the JARVIS security boundary.

For the initial implementation, the Codex engine should use the most restrictive practical host sandbox and perform source mutation through the JARVIS development tool interface.

If MCP is the selected transport for those development tools, MCP is only the transport. JARVIS remains the authorization source.

## 9.1 Initial Codex transport decision

The initial Codex adapter will use a persistent Codex development thread plus a
**structured JARVIS tool-batch protocol** over the provider-neutral
`DevelopmentToolPort`.

This is intentionally narrower than giving Codex direct host shell or workspace-write
authority:

1. Codex receives the immutable `DevelopmentTicketV1` and the schemas of the tools
   authorized by that ticket.
2. Codex returns either a bounded batch of requested JARVIS development-tool calls or
   a typed terminal development disposition.
3. JARVIS executes those calls through `DevelopmentToolPort`, which reuses the
   existing DEVELOPMENT executors and persists every operation as canonical Work
   evidence.
4. The resulting compact observations are sent back into the same Codex thread as
   tool-level/external observations.
5. The thread may continue until it produces a typed `DevelopmentResultV1`, reaches
   a configured turn/tool budget, or becomes resource-blocked.

This keeps the first integration in-process, testable with a fake Codex runtime, and
independent of Codex's native host filesystem/shell authority. It also makes the
provider thread resumable working memory while WorkStore/DBOS remains canonical truth.

MCP remains a compatible future transport behind the same `DevelopmentToolPort`.
It should be adopted only if owner-machine benchmarks show that it improves reliability,
turn efficiency, or interoperability. The architectural boundary does not depend on
MCP.

The initial Codex process configuration must therefore remain restrictive:

- reuse the approved ChatGPT-plan access token without persisting it in development
  artifacts;
- use an isolated JARVIS-owned Codex home/configuration;
- deny provider-side approval escalation;
- use read-only/native sandboxing where practical;
- disable child-agent/swarm behavior initially;
- disable native web search for development turns unless a later governed design
  explicitly admits it;
- do not treat Codex native shell, workspace write, Git, package installation, or
  sandboxing as JARVIS authority.

The DevelopmentEngine may decide **what engineering work is needed**. JARVIS still
decides **which executable operations exist and whether they are authorized**.

## 10. Quota-efficiency rules

Cloud engineering intelligence is a scarce resource.

JARVIS must therefore implement:

### 10.1 Compact context

C6 bounded context should move from shadow to apply only after replay/regression validation proves the optimized context preserves required development decisions.

### 10.2 Reasoning admission

Before any expensive engineering invocation, JARVIS should produce a deterministic reasoning fingerprint from:

- goal digest;
- EngineeringChange stage;
- architecture digest;
- base revision;
- relevant evidence digests;
- relevant test/failure evidence;
- allowed-tool contract version.

If the fingerprint is unchanged and a valid result already exists, reuse the result rather than invoking cloud intelligence again.

### 10.2.1 Shared cloud-reasoning lease

The ChatGPT-plan allowance is shared not only by DevelopmentEngine turns but also by any
ordinary Work reasoning routed to the same connected plan. JARVIS therefore exposes one
`provider_api` resource lease with capacity 1 to both routed WorkReasoner invocations
and DevelopmentEngine sessions. A coherent DevelopmentEngine session holds this lease
for its bounded engineering assignment. Other deterministic Work can continue, but a
second background cloud-reasoning request waits rather than consuming the same shared
allowance concurrently.

This is a quota-governance rule, not a provider-specific lifecycle dependency. The
provider circuit still handles quota/rate/service pressure after a request is admitted.

### 10.3 One expensive development mission per shared allowance

The ChatGPT-plan allowance is shared. Multiple WorkItems must not independently hammer the same exhausted capacity domain.

JARVIS should serialize or explicitly budget expensive development sessions while allowing deterministic work to continue.

### 10.4 Provider pressure parks work

Subscription/rate-limit/resource pressure must move cloud-dependent work into a durable resource wait. It must not become terminal capability failure and must not trigger automatic paid fallback.

### 10.5 Long coherent engineering turns

The DevelopmentEngine should solve a meaningful bounded engineering assignment per turn/session rather than returning after every file read or test execution.

## 11. Thread/session durability

A provider coding thread is working memory, not canonical truth.

Canonical truth remains:

- WorkStore;
- DBOS;
- EngineeringChange artifacts;
- exact repository/worktree state;
- research and architecture artifacts;
- test and candidate evidence.

If a provider thread becomes unusable, JARVIS may create a replacement thread from the canonical ticket plus current exact worktree/evidence.

Provider working memory and cached DevelopmentResult reuse are valid only within the exact
DevelopmentEngine generation (`engine_id` + `engine_version`). Changing the
engineering provider/runtime generation must clear the saved provider thread binding and
invalidate cached-result reuse while preserving the canonical ticket, WorkStore evidence and
repository state needed for reconstruction.

No capability lifecycle state may depend solely on provider conversation memory.

## 12. Architecture-revision behavior

A critical requirement from the recent capability run:

When development proves that the approved architecture cannot safely satisfy the requirement, the developer must not ask the owner a generic architecture question.

Instead:

```text
DevelopmentResultV1
  disposition = NEEDS_ARCHITECTURE_REVISION
  reason = factual engineering blocker
  evidence_refs = exact evidence
```

Then JARVIS:

1. returns the exact EngineeringChange to governed research;
2. performs fresh research;
3. produces a replacement architecture tied to the exact research attempt;
4. presents the canonical owner architecture gate;
5. resumes development only after approval.

This preserves lifecycle continuity and prevents generic `WAITING_FOR_OWNER` loops.

## 13. Relationship to existing JARVIS phases

This design does not replace the existing control planes.

### Keep

- GICC
- Phase 9 capability acquisition
- EngineeringChange
- DBOS WorkItems
- Phase 5 dependency/discovery/secrets substrate
- Phase 7 promotion
- Phase 8 capability package admission/lifecycle
- CapabilityRuntime
- Authority/OPA
- Hardware/external acceptance
- GitHub PR/CI governance

### Change

- DEVELOPMENT stage engineering reasoning;
- cloud reasoning admission;
- development context packaging;
- repeated micro-step model decisions;
- provider development-session persistence.

## 14. Explicit non-goals

Do not:

- hardcode Hisense, VIDAA, TV IP addresses, ports, protocols, SDKs, applications, movies, or media providers into this framework;
- optimize the framework specifically for the first TV test;
- automatically enable paid provider fallback;
- give the development model merge authority;
- weaken owner approval/authority gates;
- allow arbitrary shell or protected-main mutation;
- replace DBOS with a coding-agent thread;
- build an LLM manager/researcher/architect/developer/tester swarm;
- make provider thread history canonical;
- bypass Phase 5 dependency verification;
- bypass Phase 8 package lifecycle;
- automatically activate an external capability.

## 15. Implementation sequence

### D0 — Architecture anchor

- Commit this document before functional changes.
- All subsequent implementation should reference this architecture.

### D1 — Provider-neutral contracts

- Add `DevelopmentTicketV1`.
- Add `DevelopmentResultV1`.
- Add `DevelopmentDisposition`.
- Add `DevelopmentEngine` protocol.
- Add deterministic digests and strict validation.
- Add unit tests.

### D2 — JARVIS development tool adapter

- Wrap the existing isolated-development operations behind `DevelopmentToolPort`.
- Do not duplicate shell/filesystem logic.
- Add policy tests proving the adapter cannot escape the WorkItem workspace.

### D3 — Codex engine adapter

- Add optional/lazy official Codex SDK integration.
- Prefer `AsyncCodex`.
- Use restricted sandbox and deny model-side escalation.
- Reuse approved ChatGPT-plan OAuth transport when configured.
- Persist only non-secret thread identity and usage metadata.
- Treat the reviewed Codex SDK version as the stable engine generation and fail closed
  before thread start/resume if the installed runtime generation differs.
- Add fake-SDK tests before owner-machine live proof.

### D4 — Durable session and reasoning admission

- Persist ticket/result/thread lineage.
- Add reasoning fingerprint/reuse.
- Scope provider thread identity and result reuse to the exact engine ID/version.
- Add shared ChatGPT-plan development admission/governor.
- Reuse provider-circuit resource waits.

### D5 — EngineeringChange integration

- DEVELOPMENT uses the DevelopmentEngine for capability development.
- Keep existing WorkEngine path for unrelated bounded Work where appropriate.
- Map typed DevelopmentResult dispositions into governed transitions.
- Preserve exact research-attempt/architecture lineage.
- Serve development research evidence only from the exact research attempt that produced
  the plan bound to the approved architecture; superseded attempts must never leak into a
  later development ticket.

### D6 — C6 apply validation

Implemented replay substrate:

- SHADOW model routes persist a backward-compatible safety decision fingerprint:
  selected action, `goal_complete`, `needs_owner`, owner question and canonical
  parameter digest;
- successful SHADOW model cycles with a ContextPack persist a small encrypted replay
  snapshot containing only historical Work state/status, purpose, action catalog,
  visible step IDs/history-prefix digest and evidence; full WorkStep payloads remain
  canonical only in WorkStore;
- replay reconstruction verifies the exact append-only history prefix before creating
  an optimized APPLY BrainRequest and fails closed on provenance drift;
- `tools/research/c6_context_owner_acceptance.py` remains zero-model by default,
  exposes `--decision-replay-preflight` to prove historical recorded-decision replay
  readiness without initializing ChatGPT-plan, and exposes an explicit bounded
  `--decision-replay` mode when durable legacy decision provenance exists;
- older Work routes may predate decision-output provenance and must never be backfilled
  from guessed later state. For those routes, `--paired-decision-preflight` validates
  whether their immutable C6 request snapshots can support a fresh same-request A/B,
  and `--paired-decision-benchmark` compares legacy-context vs optimized-context
  decisions using the current configured ChatGPT-plan model;
- the paired benchmark is capped at three cases / six model calls, requires at least
  two Work types and two distinct WorkItems, compares action, `goal_complete`,
  `needs_owner`, `owner_question`, and parameters, stops at the first mismatch,
  never executes the selected action, has no paid fallback, does not mutate the shared
  provider circuit, and never changes production routing;
- owner-machine preflight on 2026-10-03 found that the legacy model-route population
  predates replayable C6 request snapshots/provenance, so those rows remain explicitly
  non-comparable rather than being guessed or backfilled;
- when historical replay is unavailable, `tools/research/c6_benchmark_corpus.py`
  provides a checked-in descriptor-only three-case corpus derived from repository-tested
  Work shapes: development repair after a failed test, development ready for local
  commit, and research/acquisition requiring re-resolution after newer evidence. The
  corpus imports current production `BrainAction` descriptors directly and
  instantiates no executor/runtime service;
- `--fixture-decision-preflight` must prove all three fixture requests use the smaller
  optimized payload and cover both DEVELOPMENT and RESEARCH before any provider state is
  initialized. Only then may `--fixture-decision-benchmark` spend at most six
  ChatGPT-plan calls for same-request legacy-vs-optimized decision equivalence;
- optimized replay is compared against the durable legacy decision across action,
  completion, owner-wait, owner-question and parameter fields with usage/latency recorded.

Still required before APPLY promotion:

- replay a representative corpus of Work cycles that actually reached model reasoning
  under the current contract, spanning at least two Work types and distinct WorkItems;
- require the configured minimum number of comparable cases with no safety-field
  mismatches;
- review actual context/token reduction and provider behavior;
- move development context to `APPLY` only after that evidence is accepted.

### D7 — Architecture proof

The owner-machine proof is implemented as
`tools/research/development_engine_owner_acceptance.py`. It must operate only on a
disposable temporary Git repository, use the real governed DEVELOPMENT executors and
Docker test runner, leave the source repository unchanged, prove exact allowed-path/test
enforcement, record measured Codex usage when available, and prove a second identical
reasoning request reuses the durable result rather than invoking cloud intelligence
again.

Owner-machine proof in a disposable isolated repo/worktree:

1. use existing ChatGPT-plan authorization;
2. consult the same persistent app/account-scoped ChatGPT-plan subscription circuit used
   by production and refuse to probe while a known quota cooldown remains;
3. start the reviewed official Codex SDK only after zero-inference prerequisites pass;
4. expose harmless JARVIS-style development tools;
5. complete one bounded code task;
6. restart JARVIS/Codex process;
7. resume or reconstruct from canonical state;
8. record exact model calls, token usage and final shared-circuit state;
9. prove no direct protected-main mutation, uncontrolled shell access or automatic paid
   fallback.

### D8 — Blind capability acceptance

Only after D7 passes:

- submit a natural owner goal;
- allow JARVIS to discover the missing capability;
- research;
- architect;
- develop through DevelopmentEngine;
- test;
- promote;
- admit;
- explicitly activate;
- perform real external acceptance;
- resume the original GICC goal.

The first real device may be a television, but the framework must remain device- and protocol-agnostic.

## 16. Acceptance metrics

A development-engine implementation is not accepted merely because tests pass.

Measure:

- capability success rate;
- number of independent ChatGPT-plan engineering turns;
- input/output tokens per turn when available;
- context reduction vs legacy WorkReasoner;
- deterministic/model bypass ratio;
- duplicate reasoning calls avoided;
- development tool calls per model turn;
- recovery after restart;
- number of owner interventions;
- architecture-revision correctness;
- provider-pressure behavior;
- no governance regressions;
- no protected-main mutation;
- no automatic paid fallback.

Initial optimization hypothesis to test, not assume:

- at least 50% fewer independent cloud-development reasoning calls;
- target 60–80% fewer micro-step orchestration calls if capability quality remains unchanged or improves.

## 17. Definition of architectural success

The desired owner experience is:

> “JARVIS, I want you to control my TV and play the movie I request.”

JARVIS should be able to:

- determine whether the capability exists;
- acquire fresh evidence;
- design an approved integration;
- hand the bounded development ticket to the engineering specialist;
- let the specialist perform coherent development through governed tools;
- validate and promote the candidate;
- request only legitimate owner gates or pairing input;
- verify the real-world effect;
- continue the original goal.

The owner should not need to identify the protocol, choose the package, provide the device IP manually when it is discoverable, write code, install dependencies, run tests, inspect logs, or debug the integration.

That is the architectural direction. Future changes that materially violate this document require an explicit architecture revision rather than an incidental implementation shortcut.

## 18. Implementation status — PR #252

The capability-focused implementation on `feat/development-engine-control-plane`
now covers D0 through the core of D5. This status is intentionally about code on the
draft branch; it is **not** an owner-machine or real-device acceptance claim.

Implemented on the draft branch:

- provider-neutral ticket/result/tool contracts with exact digests;
- governed adapter over JARVIS DEVELOPMENT executors;
- restricted Codex/ChatGPT-plan engineering specialist with long coherent tool batches;
- durable provider-thread identity, canonical progress reconstruction and engine-generation-
  scoped exact-result reuse;
- stable reviewed Codex runtime generation enforcement before provider thread use;
- C6 durable legacy-decision fingerprints plus exact bounded shadow replay snapshots and
  a non-executing optimized decision replay path;
- cumulative engineering usage telemetry;
- one serialized `development_intelligence` resource;
- a process-persistent shared ChatGPT-plan subscription circuit across ordinary Work
  reasoning and DevelopmentEngine sessions;
- subscription/quota pressure parked as resource wait with long bounded cooldown;
- no automatic paid-provider fallback in the production Work composition;
- Phase-9 DEVELOPMENT bypass of micro-step model orchestration;
- deterministic Phase-9 research bookkeeping bypass where no model judgement is needed;
- bounded retrieval of canonical research/discovery/SDK-verification evidence from the
  exact approved architecture source attempt;
- typed re-research / architecture-revision / dependency outcomes;
- exact revised-research-attempt and architecture lineage;
- restart-safe durable Work execution recovery;
- migration of stale model-authored Phase-9 owner waits into governed re-research;
- exact DevelopmentEngine completion binding to the canonical ticket, commit and passing
  test WorkSteps before ordinary candidate verification;
- existing strong Phase-9 candidate verification, promotion, Phase-8 lifecycle and
  external-acceptance control planes remain authoritative.

Still intentionally pending:

- D6 C6 `APPLY` admission. Decision provenance, exact replay reconstruction and the
  bounded owner-machine replay harness are implemented, but production default remains
  `shadow` until owner-machine corpus evidence shows the required safety-field
  equivalence and material context reduction.
- D7 owner-machine Codex proof using the real ChatGPT-plan authorization and actual
  local development sandbox. The proof now shares the persistent production subscription
  circuit, so a known quota cooldown is a zero-inference preflight blocker rather than a
  reason to probe repeatedly. It also reconstructs a fresh WorkStore/session/engine/
  coordinator stack after the first mission and must reuse the durable result before any
  Codex runtime can be created.
- D8 blind natural-goal capability acceptance through promotion, explicit activation,
  real external effect/readback and GICC continuation.
- a direct development static-check tool, only if wrapping the existing source-owned
  verifier substrate proves useful beyond sandbox tests plus CI.

PR #252 must remain draft and unmerged until CI/regression validation and the required
owner-machine acceptance are complete.
