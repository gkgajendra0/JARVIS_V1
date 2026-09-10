# JARVIS Hands H1 owner acceptance

Status: acceptance runbook for draft PR #30. This document does not mark H1 DONE.

## Gate order

1. `jarvis-hands-smoke --readiness`
   - read-only
   - zero mutations
   - zero cloud model calls
   - no Windows Hello prompt
2. `jarvis-hands-smoke`
   - structured Microsoft `winapp` Notepad acceptance
   - exact text write + readback verification
   - one exact Windows Hello approval
3. `jarvis-hands-smoke --native --volume 30`
   - approved Calculator launch
   - Calculator maximize
   - Windows master volume set to 30%
   - clipboard set to `JARVIS native clipboard acceptance`
   - each reversible action is separately proposed, approved, consumed and verified
   - Calculator is intentionally left open/maximized, volume remains at the test value, and the clipboard marker remains present
4. `jarvis-hands-smoke --media`
   - requires one active Windows media session
   - reads current media state through the governed runtime
   - changes playback state once and restores the original state
   - does not skip tracks
5. Live `jarvis-voice` acceptance
   - natural-language semantic native actions
   - natural-language structured app UI control
   - no authority from unrelated/ambient meeting speech
   - success must match verified tool state

## Approval rule

Every non-routine action remains an immutable `ActionProposal` routed through the canonical `AuthorityService`. The current H1 owner machine still uses exact-action Windows Hello/T3 for reversible local changes while T2 admission remains intentionally disabled. One permit cannot authorize a different action or different material parameters.

Human-facing Windows Hello summaries must identify the material action being approved. Examples include the target volume percentage, target application/window, media transition, or a bounded clipboard-text preview. The proposal fingerprint remains bound to the complete exact parameters even when a long clipboard value is previewed rather than fully displayed.

## Completion rule

H1 is not owner accepted until readiness, structured UI, native core, media, and live voice tests all pass on the owner Windows machine. PR #30 stays draft and unmerged until owner acceptance, documentation reconciliation, and final exact-head CI are complete.
