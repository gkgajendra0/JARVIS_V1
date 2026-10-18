# Phase 6 Unknown-Incident Investigation + Source Repair — Research

Status: **RESEARCH COMPLETE / ARCHITECTURE PROPOSED — OWNER APPROVAL REQUIRED BEFORE IMPLEMENTATION**

Date: 2026-09-27

## 1. Goal

Phase 6 must let JARVIS take an unknown incident that has no accepted deterministic repair, investigate it from bounded evidence, reproduce it where practical, identify and test hypotheses, and—only after the existing architecture gate is approved—produce an isolated, tested source-repair candidate.

Phase 6 must reuse the accepted platform:

- Incident truth;
- EngineeringKnowledge;
- EngineeringChange;
- WorkItem/DBOS;
- Research + Diagnostic Model Router;
- Phase-5 dependency/sandbox/provenance primitives;
- isolated development worktrees;
- Authority and exact owner gates.

It must not introduce a second autonomous coding/runtime authority.

## 2. Repository findings

The current codebase already contains most prerequisites:

- `WorkType.DIAGNOSTICS` exists.
- The Phase-4 `engineering_stage.v1` router already treats unknown diagnostic work as requiring a capable target unless progress evidence shows the task has settled.
- EngineeringChange already owns durable research -> architecture -> approval -> development -> verification gates.
- DEVELOPMENT work already has bounded actions for worktree preparation, file listing/reading/search, writes, sandboxed pytest, diff inspection, clean local commit, and status.
- Development completion already fails closed unless the latest edit is followed by passing sandboxed tests, final diff inspection and a clean commit.
- EngineeringKnowledge already provides provenance-linked retrieval.
- Phase 5 provides least-privilege sandbox profiles, dependency provenance, secret boundaries and digest-bound capability metadata.
- Incident records already hold evidence, affected components, root-cause/fix fields and repair provenance.

The actual Phase-6 gaps are therefore orchestration and diagnostic contracts rather than basic tooling.

## 3. External research

### 3.1 Agentless

Agentless uses a deliberately structured software-repair pipeline:

1. hierarchical fault localization;
2. repair generation;
3. patch validation, including regression/reproduction tests.

Its core lesson for JARVIS is that fault localization and validation should be explicit pipeline stages rather than leaving the whole process to an unconstrained agent loop.

Disposition: **ADOPT THE PIPELINE PATTERN, NOT THE FRAMEWORK.**

Source:
- https://github.com/OpenAutoCoder/Agentless

### 3.2 SWE-agent / Agent-Computer Interface

SWE-agent shows that narrow software-engineering tools and concise feedback are materially important. Its ACI research emphasizes bounded file viewing/search/editing and immediate syntax/lint feedback instead of generic shell access.

Disposition: **ADOPT NARROW TOOL/FEEDBACK PRINCIPLES. DO NOT ADD GENERAL SHELL AUTHORITY.**

Source:
- https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md

### 3.3 OpenHands

OpenHands uses an event-driven reasoning/action architecture with explicit tool orchestration and security analysis. The useful lesson is separation between agent reasoning and the execution/security boundary.

JARVIS already has WorkItems, EngineeringChange, routing, Authority and sandboxing, so importing OpenHands as another orchestration owner would duplicate canonical state.

Disposition: **ADOPT EVENT/TOOL-BOUNDARY IDEAS ONLY. DO NOT EMBED OPENHANDS AS THE CONTROL PLANE.**

Source:
- https://github.com/OpenHands/docs/blob/main/sdk/arch/agent.mdx

### 3.4 Codex safety patterns

OpenAI's production guidance for coding agents combines workspace sandboxing, constrained network access, explicit approval boundaries and auditable agent telemetry.

This aligns with JARVIS's existing design and supports preserving:
- workspace-only writes;
- no open network during code execution;
- explicit gate crossings;
- durable action evidence.

Disposition: **CONFIRMS EXISTING JARVIS SECURITY DIRECTION.**

Sources:
- https://openai.com/index/running-codex-safely/
- https://openai.com/index/building-codex-windows-sandbox/

### 3.5 SWE-bench / SWE-bench Verified

SWE-bench evaluates patches by applying them in reproducible environments and running tests. SWE-bench Verified further constrains evaluation to engineer-verified solvable cases.

The direct benchmark is not a release gate for JARVIS, but the evaluation pattern is relevant:
- real issue/evidence;
- fixed source revision;
- isolated environment;
- patch;
- deterministic tests;
- reproducible outcome.

Disposition: **ADOPT THE EVALUATION SHAPE FOR A JARVIS-SPECIFIC INCIDENT REPLAY SET.**

Source:
- https://www.swebench.com/SWE-bench/faq/

### 3.6 SWE-smith

SWE-smith creates software-engineering tasks from repositories for training/evaluation.

This is relevant later for Phase 13 curriculum/specialist evaluation, not for live Phase 6 repair authority.

Disposition: **DEFER TO PHASE 13.**

Source:
- https://github.com/SWE-bench/SWE-smith

## 3.7 AutoCodeRover / program-structure-aware repair

AutoCodeRover combines LLM reasoning with program-analysis/debugging capabilities. Its most useful ideas for JARVIS are:

- AST/program-structure-aware code search rather than only raw text search;
- statistical fault localization when tests are available;
- specification/intent inference before patch generation;
- explicit reviewer/self-correction stages in later variants.

Disposition: **ADAPT THESE CAPABILITIES BEHIND JARVIS-OWNED TYPED TOOLS. DO NOT EMBED ITS ORCHESTRATOR.**

For Phase 6, add a program-structure index and coverage-backed suspicious-location evidence before asking the model to inspect arbitrary files.

Source:
- https://github.com/AutoCodeRoverSG/auto-code-rover

## 3.8 Aider repository map + Tree-sitter

Aider builds a compact repository map from important symbols and dependency relationships so the model sees architecture-level context without loading the full repository. Its map is built with Tree-sitter.

Tree-sitter provides fast concrete syntax trees and remains useful even when code has syntax errors.

Disposition: **ADAPT THE REPOSITORY-MAP PATTERN AND USE TREE-SITTER DIRECTLY OR THROUGH A SMALL JARVIS WRAPPER. DO NOT ADD AIDER AS THE CONTROL PLANE.**

Phase-6 use:
- symbol definitions and signatures;
- reference/dependency graph;
- bounded architecture context;
- AST-aware search/localization;
- changed-symbol analysis after candidate edits.

Sources:
- https://aider.chat/docs/repomap.html
- https://tree-sitter.github.io/tree-sitter/

## 3.9 Deterministic history localization

Git already provides high-value diagnosis primitives:

- `git bisect` can binary-search the commit that introduced a reproducible regression;
- `git blame`/history queries can identify the revision that last changed suspicious lines.

Disposition: **WRAP AS READ-ONLY DIAGNOSTIC ACTIONS WHEN A GOOD/ BAD REVISION BOUNDARY EXISTS.**

Do not expose raw Git shell. Add typed, bounded history queries through the diagnostic workspace manager.

Sources:
- https://git-scm.com/docs/git-bisect
- https://git-scm.com/docs/git-blame

## 3.10 Coverage-guided localization and incremental tests

Coverage.py supports statement and branch coverage, making execution evidence available at line/branch granularity. pytest preserves last-failed state; pytest-testmon can select tests affected by changed methods/files using coverage-derived dependencies.

Disposition:
- **ADOPT COVERAGE.PY AS CORE PHASE-6 DIAGNOSTIC EVIDENCE** for reproducible incidents;
- use pytest last-failed as a cheap deterministic retry accelerator;
- **EVALUATE TESTMON LATER** as an optimization after correctness is established.

Sources:
- https://coverage.readthedocs.io/
- https://docs.pytest.org/en/9.0.x/how-to/cache.html
- https://www.testmon.org/

## 3.11 Static analysis and type intelligence

Pyright is a high-performance standards-based Python type checker. CodeQL can model code as data and run deterministic queries for errors/security findings.

Disposition:
- **WRAP PYRIGHT AS AN OPTIONAL PHASE-6 STATIC DIAGNOSTIC/POST-PATCH CHECK** where the repository is type-checkable;
- **KEEP CODEQL/SEMGREP AS OPTIONAL SPECIALIST ANALYZERS**, not mandatory Phase-6 dependencies. Invoke them for security/data-flow incidents or when a registered diagnostic profile requests them.

This keeps routine source repair lightweight while allowing deeper analyzers for the incidents that justify them.

Sources:
- https://github.com/microsoft/pyright
- https://docs.github.com/en/code-security/concepts/code-scanning/codeql/codeql-code-scanning

## 3.12 Python runtime fault evidence

Python's built-in `faulthandler` can dump thread tracebacks on faults/timeouts and integrates with Windows fault handling.

Disposition: **ADAPT AS A REGISTERED EVIDENCE SOURCE FOR HANG/CRASH DIAGNOSTICS**, not as a repair executor.

Source:
- https://docs.python.org/3/library/faulthandler.html

## 3.13 Final build-vs-adopt stack decision

The deeper pre-implementation sweep confirms that JARVIS should own orchestration and provenance, but should **not** reimplement mature code-analysis engines.

Adopt behind Phase-5 DependencyBroker / typed adapters:

- **ast-grep-py** — structural/AST search API. Current release observed during research: 0.44.1, with Windows CPython wheels and Trusted Publishing on PyPI. It already solves fast Tree-sitter-powered structural search, so JARVIS should not invent a second generic structural matcher.
- **Grimp** — Python import/dependency graph. Current release observed: 3.17 (2026-09-04), with CPython 3.11 Windows wheels. Use it for deterministic package/module dependency edges rather than writing an import graph engine.
- **Coverage.py** — execution, branch and per-test dynamic-context evidence. Current stable observed: 7.16.1. Dynamic contexts can answer which test executed which line, which is directly useful for spectrum-based fault localization.
- **Pyright** — optional type/static diagnostic verifier, not a mandatory repair dependency. Current Python wrapper observed: 1.1.414.
- **Git native bisect/blame/log** — wrap through typed read-only adapters; do not recreate version-history algorithms.

For ranking a compact repository map, use the mature graph/evidence outputs above and a small deterministic JARVIS ranking policy. The ranking policy is JARVIS-specific because it must combine incident evidence, component scope, accepted EngineeringKnowledge and bounded token budgets; adopting a second coding-agent runtime solely for repo-map ranking would add far more control-plane surface than value.

Do not make AFLuent/fault-localization pytest plugins a hard dependency in the first implementation. Their formulas are useful, but they introduce pytest-plugin coupling and Coverage.py interaction constraints. Phase 6 should first capture canonical per-test coverage evidence, then compute versioned suspiciousness scores inside a small deterministic evaluator. This evaluator is not a parser/test runner replacement; it is a transparent policy over already-verified evidence.

## 4. Technology decisions

### 4.1 No new agent framework

Decision: keep JARVIS-owned orchestration.

Reason:
- WorkItem/DBOS already gives durable execution;
- EngineeringChange already owns gates;
- Model Router already owns provider/model selection;
- Phase 5 already owns sandbox/dependencies/secrets;
- adding another agent runtime would duplicate state, retries and authority.

### 4.2 Deterministic outer loop, model-assisted inner reasoning

The Phase-6 outer lifecycle should be JARVIS-controlled:

```text
unknown incident
-> bind exact source revision
-> bounded evidence package
-> retrieve accepted EngineeringKnowledge
-> reproduce / observe
-> localize
-> record hypotheses
-> controlled experiment(s)
-> finalize diagnosis
-> architecture artifact
-> owner approval
-> isolated source repair
-> targeted + regression verification
-> protected-surface check
-> diff inspection
-> clean candidate commit
-> owner-reviewable candidate
```

The model may choose hypotheses, source locations and candidate edits inside registered actions. It does not choose whether evidence is sufficient to bypass a gate.

### 4.3 Read-only diagnostic workspace before approval

Unknown investigation needs source inspection and reproduction before implementation approval.

Use a new diagnostic worktree pinned to the incident's exact source revision. Expose only read/search/list and sandboxed test/reproduction operations. No source-write or commit action is registered for `WorkType.DIAGNOSTICS`.

### 4.4 Reuse existing DEVELOPMENT work after approval

Do not build a second repair editor.

After the diagnosis/architecture gate is approved, Phase 6 creates the ordinary DEVELOPMENT stage and reuses:
- isolated branch/worktree;
- bounded read/search/write;
- network-disabled sandbox tests;
- final diff;
- local clean commit;
- existing completion guard.

### 4.5 Diagnosis must be a typed artifact

Free-form completion text is not sufficient.

A finalized diagnosis should include:
- incident ID;
- EngineeringChange ID;
- diagnostic WorkItem ID;
- exact source revision;
- bounded evidence IDs;
- retrieved knowledge revision IDs;
- reproduction status/evidence;
- hypotheses with supported/refuted evidence;
- selected root-cause hypothesis or INCONCLUSIVE;
- affected paths/components;
- proposed repair scope;
- verification targets;
- uncertainty/reason codes;
- canonical digest.

### 4.6 Protected surfaces fail closed

A normal unknown-incident repair must not silently edit protected governance/security surfaces.

The final candidate verifier should classify changed paths against a registered protected-surface policy. If the repair touches Authority, governance, CI/rulesets, secret policy, sandbox policy or equivalent R5 surfaces, the ordinary Phase-6 candidate is blocked and a separately authorized architecture/security change is required.

### 4.7 External research is optional, not mandatory

Diagnostics may use current web research when the incident depends on an external API/library/protocol. A local source bug should not require web access just to satisfy a completion rule.

## 5. Proposed verification philosophy

A diagnosis is not `CONFIRMED` merely because the model is confident.

Acceptable evidence includes:
- deterministic reproduction;
- failing test;
- traceback or structured incident evidence;
- source/runtime correlation;
- experiment that distinguishes competing hypotheses;
- accepted EngineeringKnowledge provenance.

A repair candidate is not ready merely because tests pass once. It also needs:
- tests after the latest edit;
- reproduction/regression target where feasible;
- no protected-surface violation;
- final diff inspection;
- clean commit;
- exact incident/diagnosis provenance.

## 6. Evaluation matrix for Phase 6

At minimum:

1. unknown incident -> diagnostic WorkItem created;
2. known accepted deterministic repair -> Phase 6 does not steal the incident;
3. diagnostic restart -> same WorkItem and EngineeringChange;
4. provider unavailable -> WAITING_RESOURCE, no unsafe execution fallback;
5. evidence package is bounded/redacted;
6. accepted EngineeringKnowledge is retrieved but cannot execute repair;
7. successful reproduction -> evidence persisted;
8. non-reproducible incident -> truthful INCONCLUSIVE;
9. competing hypotheses -> refuted/supporting evidence persists;
10. premature diagnostic completion -> blocked;
11. owner architecture rejection -> no development WorkItem;
12. approved diagnosis -> development WorkItem tied to exact architecture revision;
13. source edit without post-edit tests -> blocked;
14. failing tests -> no candidate completion;
15. protected-surface diff -> fail closed/escalate;
16. successful repair -> clean candidate commit with provenance;
17. restart during development -> same branch/worktree lineage;
18. production/protected main remains unchanged;
19. secret-bearing evidence cannot reach model context;
20. Phase-6 output does not merge or deploy.

## 7. Research conclusion

The strongest Phase-6 design is not a new coding-agent framework. It is a new JARVIS-owned unknown-incident process contract that composes the primitives already accepted in Phases 2–5.

The key new work is:
- typed diagnosis evidence;
- diagnostic read-only workspace/actions;
- diagnostic completion rules;
- incident-to-EngineeringChange admission;
- diagnosis-to-approved-development handoff;
- protected-surface verification;
- replay/evaluation and owner-machine acceptance.

This preserves the whole-JARVIS north star: increasing autonomous engineering ability without transferring Authority to the model.
