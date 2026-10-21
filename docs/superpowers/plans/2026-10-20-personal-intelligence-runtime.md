# Personal Intelligence Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax for tracking. The owner has explicitly authorized finishing integration before requesting local acceptance; do not request another demo or repeat the approved native architecture decision.

**Goal:** Deliver automatic owner-authorized canonical context in normal `jarvis-voice`.
**Architecture:** Reuse the production session tool bundle, canonical reader and
capability authority. Native model tool calls select current facts after exact
owner consent; a turn-bound audio gate and session retirement prevent stale history
from crossing into a different request.
**Tech Stack:** Existing Python3.11, LiveKit1.8.3, Gemini3.8, SQLCipher/DPAPI, Windows Hello/OPA.
**Spec:** ../specs/2026-10-20-personal-intelligence-runtime-design.md

## Global Constraints
- No new dependencies, parallel memory store, provider fallback or schema.
- OFF default; explicit APPLY works in the normal production entrypoint.
- No microphone/real owner-memory reads or protected promotion during development.
- Preserve shadow biometric status; exact request consent uses existing authority.
- Catalog128/facts4/value1800bytes/question8000bytes; STANDARD owner-explicit/direct/verified only.
- Personal provider history retires after one authorized answer; invalidations fail closed.

## Review Focus
- Late Hello result after interruption/close must not release names, facts or audio.
- Same-text repeated requests must have different turn-bound consent/catalog IDs.
- Correct/delete while authorization waits must not release superseded assertions.
- Provider preamble/tool follow-up cannot accidentally authorize a later utterance.
- OFF and normal startup must work without semantic HTTP availability or new configuration side effects.

### Task 1: Exact-request authority
Files: capabilities/authority_bridge.py, capabilities/runtime.py, tests/test_personal_context_authority.py.
Produces: broker.authorize_fresh_owner(prepared), validate_binding(authorized), invalidate_session(session_id);
runtime.authorize_personal_context(session_id, turn_id, question, operation='read'),
consume_personal_context(authorized), validate_personal_context(authorized), invalidate_personal_context(session_id).
- [ ] RED: trusted T2 still invokes fresh Hello; binding fails on lock/expiry; private scope/input is fixed; no question/value in audit metadata.
- [ ] Implement through existing AuthorityService, risk private_read, OPA, permit; preserve ordinary authorize behavior.
- [ ] GREEN existing authority regressions + new contracts; commit.

### Task 2: Turn-bound personal session and tools
Files: voice/personal_context.py, voice/personal_context_audio.py, tests/test_personal_context_runtime.py.
Consumes Task1 and canonical ConversationSession/SemanticRetrievalService.
Produces PersonalContextSession with catalog(), read(catalog_id, facet_indices),
authorize_mutation(operation,predicate,value), mutation_committed(), observe_turn(), observe_activity(),
allow_audio(), playback_finished(), close(); PersonalContextAgentTools.tools;
PersonalContextAudioOutput wrapping the existing shared device without owning it.
- [ ] RED canonical fixture integration for relevance proposals, bounds, guest/denial, absence/unavailable,
  stale IDs, correction/delete during wait, new/same-text turns, cancellation, timeouts and one-response audio.
- [ ] Implement per-turn authorization dedupe, post-await revalidation, exact-current evidence,
  provider-history retirement, no values in logging, and bounded cleanup.
- [ ] GREEN related tests; commit.

### Task 3: Normal production wiring and real switches
Files: config.py, machine_config.py, voice/production_runtime.py, voice/runtime.py,
voice/canonical_active_speaker_runtime.py, voice/memory_tools.py, voice/agent.py.
Tests: config, startup, production composition and memory-tool regressions.
- [ ] RED normal production session APPLY exposes and calls the real tools/guard;
  explicit mutation approval/reset; pending-consent inactivity is suspended; OFF exposes no path.
- [ ] Implement actual session construction, dynamic instructions only when tools exist,
  audio output hook, mutation hooks, and --personal-context off/apply with no persisted mutation.
- [ ] GREEN existing production/voice/memory/config tests plus full suite; commit.

### Task 4: Integrated acceptance and delivery
Files: normal-runtime integration tests, current plan/product/state documentation and README.
- [ ] Exercise normal session factory and actual tool outputs with temporary canonical fixtures,
  multilingual proposals, restart/correction/deletion/outage/denial; no separate demo reported as activation.
- [ ] Independent whole-branch review, reproduce material findings RED then fix GREEN; final full suite/lint.
- [ ] Commit/push draft integration PR, attach it, verify exact-head CI, publish status/report and
  give the owner the normal-app APPLY command only when the actual runtime path is implemented.
- [ ] Leave protected main and machine settings unchanged; owner performs actual app acceptance.
