# JARVIS V1 Quality Gates

These are universal completion rules for major product slices **and owner-approved integration/stabilization interludes**. Code existing or unit tests passing is never sufficient by itself.

## 1. Scope Gate

- Implementation matches the approved slice/interlude.
- Explicit non-scope remains out.
- No unrelated future capability is smuggled in.
- No old-JARVIS runtime dependency is introduced.
- Partial foundations are not mislabeled as completion of later roadmap steps.

## 2. Ownership and Architecture Gate

- Every responsibility has one authoritative owner.
- Conversation/context/memory/authority state is not duplicated.
- Provider-specific mechanics remain behind narrow replaceable boundaries where practical.
- Multiple capabilities reuse canonical capability/authority contracts rather than inventing parallel routers or permission systems.
- Development/repair tooling does not silently become normal user-facing authority.
- `CURRENT_ARCHITECTURE.md` reflects only accepted running architecture.

## 3. Automated Test / CI Gate

Tests should cover important contracts, real subsystem boundaries, failure/timeouts, replay/staleness, malformed provider output, unauthorized execution, and previously accepted regressions.

The current repository Code Quality workflow includes:

- Ubuntu Ruff format check;
- Ubuntu Ruff lint;
- Ubuntu Python install with the accepted development/Hands test extras;
- Playwright Chromium provisioning and real headless-launch smoke;
- full repository `pytest` suite on Ubuntu;
- Windows .NET 9 build of `Jarvis.WindowsHelloVerifier`;
- Windows Hello helper JSON contract probe;
- production self-contained Windows Hello helper publish + JSON contract probe;
- Windows unified Hands dependency probe;
- Windows multilingual Hands/grounding/UTF-8 regressions;
- Windows DPAPI smoke/regressions.

A green PR head is necessary but not sufficient when Windows hardware, provider behavior, Pocket 3 transport, audio, UI Automation, or other real-device behavior cannot be proven by CI.

## 4. Truthfulness and Verification Gate

- Never report completion when execution did not complete.
- Failure, partial completion, unavailable providers, stale evidence and unverified results remain explicit.
- Fallbacks preserve the original goal.
- Current/fresh claims have source/freshness evidence when required.
- Mutation success requires authoritative/postcondition evidence where practical.
- Physical behavior alone does not substitute for trusted state evidence; for example, camera movement alone is not Pocket native `LOCKED`.

## 5. Authority and Risk Gate

### Low-risk reads
Bounded scope, policy permission, truthful unavailable state, and no repetitive unnecessary approval.

### Reversible local actions
Clear user intent, bounded semantic executor rather than arbitrary shell, proportional confirmation, and rollback/undo where practical.

### Persistent writes / external communication
Separate read/draft/proposal from commit authority; exact target/content binding; explicit approval where required; preview/draft before irreversible commit where practical.

### Destructive / financial / security / self-modifying actions
Remain blocked until separately governed. They require exact-action binding, strong trust, dry-run/backup/rollback where relevant, and no weakening merely for convenience.

Universal rules:

- capabilities cannot self-authorize;
- provider/model/UI cannot bypass JARVIS authority;
- identity evidence is not execution permission;
- one approval cannot be reused for materially different work;
- unrestricted arbitrary shell/PowerShell is not a general model capability;
- secrets/sensitive payloads are not unnecessarily logged.

### T2 convenience rule

General biometric/voice-derived T2 remains deferred. Any Hands same-session T2 convenience must originate from a successful direct-user Windows Hello/T3 verification, obey its bounded absolute lifetime/session/origin rules, and never replace a required T3 challenge.

## 6. Privacy and Data Lifecycle Gate

- Persist only what accepted behavior requires.
- Separate session context from durable memory.
- Raw audio/full transcripts/provider payloads are not retained by default.
- Durable personal memory has correction/removal paths.
- Secrets/tokens do not enter normal prompts/logs unnecessarily.
- Screenshots sent for visual Computer Use are bounded to the accepted target-window contract.
- Observability records operational evidence without becoming surveillance.
- Provider-side retention limitations are not misrepresented as JARVIS deletion guarantees.

## 7. Resilience Gate

- Provider/network/audio/device failures do not corrupt canonical state.
- Resources are cleaned up on shutdown/cancel/reconnect.
- Recovery remains bounded and does not loop blindly.
- Stale evidence is invalidated after transport/session rebuild.
- Recovery/fallback does not weaken identity, permission or truthfulness boundaries.
- Newly introduced authority has a disable/rollback path.

## 8. Performance Gate

Measure user-critical paths before optimizing. Relevant measures include voice latency, planning/execution latency, startup time, memory retrieval, CPU/RAM/GPU, perception cadence, provider latency and background resource use.

Accepted optimizations must preserve functional/security invariants. Historical optimization branches are not automatically mergeable merely because one experiment performed well; proven pieces may be selectively recovered onto current main.

## 9. Human Acceptance Gate

Major user-facing behavior must be exercised normally on the owner machine when synthetic tests cannot prove the experience.

Acceptance should validate real behavior such as conversation, interruption, authority UX, no duplicate mutations, truthful failures, Pocket tracking/reacquisition/recenter, visual containment, and useful latency—not merely that an API returned success.

## 10. Documentation Reconciliation Gate

Before a step or major integration/stabilization interlude is considered closed:

- `CURRENT_PLAN.md` reflects accepted current state, deferrals, superseded/rejected work and the next active slice;
- `CURRENT_ARCHITECTURE.md` reflects what actually runs;
- `ROADMAP.md` distinguishes complete steps from partial foundations pulled forward;
- `PRODUCT.md` capability statuses match reality (`DONE`, `BOUNDED`, `PARTIAL`, `ACTIVE`, `PLANNED`, `RETIRED`);
- relevant research/acceptance evidence records **why** work was accepted, deferred, superseded or rejected;
- durable architecture decisions receive an ADR when future work could otherwise misunderstand the boundary;
- README-level status is not materially stale;
- historical research files may retain their original experimental status, but a later accepted record must clearly supersede them for current truth.

Git history is the archive; do not create duplicate `FINAL`/`V2` histories merely to preserve old wording.

## 11. Cleanup Gate

- rejected implementations are removed from production paths;
- dead scaffolding/debug artifacts are not retained casually;
- abandoned experiments do not remain active;
- compatibility paths have an explicit purpose;
- stale branches/PRs are labeled/recorded as superseded rather than treated as hidden future integration work.

## 12. Final Goal Coherence Gate

Every slice must preserve one coherent Personal Intelligence Runtime. Ask whether it composes with canonical conversation, memory, truthfulness, authority, observability and capability boundaries; remains understandable to the owner; preserves provider replaceability; and keeps consequential/self-modifying authority governed.

## 13. Git Gate

Normal lifecycle:

```text
requirements/research
-> architecture
-> owner approval
-> implementation
-> automated validation
-> real human validation
-> corrections
-> documentation reconciliation
-> PR/review
-> exact-head required checks
-> explicit merge approval
-> protected-main merge
```

Do not merge merely because a branch is green. Hardware acceptance and explicit owner authorization remain required where the active slice calls for them.

Development supervisors/agents may detect or prepare changes, but they do not weaken repository governance or gain autonomous protected-main merge authority.
