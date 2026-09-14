# Step 7A / 9A — Governed Computer Use Research and Bounded Prototype

Status: **HISTORICAL TECHNOLOGY PROTOTYPE — SUPERSEDED BY ACCEPTED JARVIS HANDS PR #30**

Original date: 2026-09-09

## Why this record remains

This bounded interlude validated an early provider-neutral visual computer-use core before the full governed Hands architecture existed. It proved that mature provider Computer Use plus a replaceable local input/screenshot bridge was viable without building custom GUI intelligence from scratch.

It did **not** itself constitute production voice authority, and it should not now be read as the current desktop architecture.

## Historical prototype

The prototype separated:

```text
ComputerUseService
    +-- provider adapter
    |     +-- Gemini computer-use protocol
    |     `-- OpenAI computer-use protocol
    `-- local ComputerExecutor
          `-- bounded screenshot/input bridge
```

The provider owned model-specific computer-use protocol mechanics; JARVIS owned local execution/result normalization.

At that time production voice wiring was intentionally withheld because the final shared Hands transaction/authority/grounding architecture had not yet been designed and accepted.

## Safety lessons retained

The prototype correctly established several constraints that carried forward:

- provider safety signals supplement rather than replace JARVIS Authority;
- safety confirmation/block states are never silently acknowledged;
- visual execution is not permission to create arbitrary shell/deletion/installation/communication/payment/security/account/self-modification authority;
- provider-specific screenshot/action mechanics must remain behind a replaceable JARVIS boundary;
- real computer actions must not be downgraded to routine merely to avoid authority requirements.

## What superseded it

PR #30 replaced the prototype as the production Hands architecture with:

- one canonical voice-facing `use_computer` handoff;
- canonical USER-generation transaction leases and duplicate/supersession protection;
- native Windows semantics first;
- Playwright for browser tasks;
- Microsoft `winapp` UI Automation for generic desktop tasks;
- target-window-scoped visual Computer Use only after structured UI evidence is insufficient;
- canonical `ActionProposal -> AuthorityService -> permit -> verification -> audit`;
- generic multilingual grounding;
- postcondition verification and bounded fast-path execution.

The accepted visual path is therefore narrower and better governed than this early all-monitor screenshot/input smoke design: it is explicit opt-in, target-window scoped, geometry/focus bound, and has a deterministic CRITICAL risk floor.

PR #38 later hardened the accepted Hands path further by fixing canonical empty-transcript reconciliation, app-hint schema normalization and structured-UI stagnation escalation.

## T2 clarification

This prototype was written while T2 was effectively unavailable for production computer actions. Current Hands does **not** solve that by promoting biometric evidence. Instead, a successful direct-user Windows Hello/T3 verification may establish the separately documented bounded same-session T2 convenience window for eligible non-critical work. Turn-specific spoken actor binding/general biometric T2 remain deferred.

## Final disposition

Do not revive or merge this prototype as a parallel desktop-control stack. Keep it as research evidence showing why the mature provider Computer Use route was viable and which safety lessons survived.

Current production truth is in:

- `JARVIS_HANDS_RUNTIME_ARCHITECTURE_PROPOSAL.md` (reconciled accepted architecture record);
- `JARVIS_GENERIC_DESKTOP_AGENT_IMPLEMENTATION.md`;
- `JARVIS_HANDS_H1_H5_OWNER_ACCEPTANCE.md`;
- `POST_STEP_7_INTEGRATION_ACCEPTANCE.md`.
