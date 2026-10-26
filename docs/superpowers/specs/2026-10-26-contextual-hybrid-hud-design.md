# Contextual Hybrid JARVIS HUD — Approved Direction

## Intent

Keep the original voice-first JARVIS runtime, Authority boundary, and Mark I arc reactor. Make the existing hybrid HUD a truthful operational display which expands around real missions, research, tool executions, diagnostics and owner attention. GK selected the contextual hybrid from the ambient/console/hybrid alternatives on 2026-10-26 and asked to proceed with all integration work.

## Approaches considered

1. Ambient-only: easy to secure and visually minimal, but hides real Work, research and recovery.
2. Full desktop control console: useful for typing and executing, but duplicates voice UX, introduces authentication and Windows owner-verification work, and overcrowds the reactor.
3. **Contextual hybrid (selected):** voice-first reactor with compact status rails and event/mission detail revealed only as needed. Stage read-only operational truth before interactive commands.

## Goals

- Preserve the reactor and original single-microphone voice lifecycle. It reflects real listening/thinking/speaking/recovering states, not fabricated amplitude.
- Surface canonical Work IDs, state, approximate progress, milestones and available ETA; show explicit `waiting_for_owner` attention and blockers without disclosing task payloads.
- Show research/provider/action activity from canonical observer callbacks, with finite trusted presentation labels rather than raw query, result, prompt, transcript, source URL or secret.
- Show voice/research model roles, system health, vision detection/target freshness, and configured versus disabled features.
- Keep the UI working when voice is offline but Work/health telemetry is available. Distinguish lost transport from a legitimately idle subsystem.
- Preserve resilience: a failing UI adapter cannot fail voice or Work.
- Add an accessible, responsive activity timeline and contextual attention surface, with keyboard/low-GPU/reduced-motion support.
- Test producer projections, sanitization, schema parsing and built React bundle. Retain loopback, read-only HTTP, security headers and no command authority.

## Non-goals and boundaries

- Never create a second conversation, microphone, task queue, owner identity, model router or permission service.
- No raw voice transcripts, private memory values, capability result data, research query/excerpts or OS paths over the existing unauthenticated localhost endpoint.
- No browser-authorized action/approve/pause/cancel/typing on the existing loopback server. A separate owner-bound authenticated command gateway, CSRF defense, interaction-currentness and Windows Hello integration must be built and accepted on the owner Windows machine before those actions become enabled. Its required contract will be documented, not impersonated by disabled-but-functional buttons.
- Future calendar/email/reminders/full autonomy remain visibly unsupported until existing capability truth says otherwise. WorkType `reminder` alone does not prove scheduling exists.

## Architecture

The current Python `UISnapshotHub` stays a read-only projection. Its schema upgrades to v2 with independent link/voice states, bounded feature/provider/vision/work summaries and bounded sanitized activity events. A thread-safe, in-memory `HUDActivityFeed` receives existing accepted-turn, research-result and capability-result observers; no raw content or durable duplicate store. Read-only Work/health/model status is derived from canonical stores on snapshot.

The frontend uses a strict v2 parser and 2-second snapshot polling with stale detection, adapting UI cards when work/attention/research status exists. A 3D reactor remains central, with no synthetic audio or complexity input. Browser inspection must show only actual projected state; preview remains visibly unlinked.

## Delivery order

1. V2 safe projection and truthful feature/voice/vision/Work status with tests.
2. Observer-fed bounded operational activity, producer wiring and test isolation.
3. Contextual React HUD rails, attention, source/provider status, event timeline and parsing tests.
4. Production frontend bundle, documentation, regression tests and security review.

## Future interaction gateway contract

Commands must originate from an authenticated, owner-bound local UI session and materialize an existing JARVIS `ActionProposal` or governed Work action, not direct executor invocation. Permit consumption remains in JARVIS with fresh session/currentness verification, audit and Windows Hello where policy requires. No POST endpoints are added in this delivery, so read-only displays remain truthful.
