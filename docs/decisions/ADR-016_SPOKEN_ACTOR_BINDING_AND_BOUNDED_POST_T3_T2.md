# ADR-016 — Defer Spoken Actor Binding; Allow Only Bounded Post-T3 T2 Convenience

- **Status:** Accepted
- **Date:** 2026-09-14
- **Scope:** Identity/authority reconciliation after JARVIS Hands

## Context

Step 3 established OWNER visual context, Windows-session binding, Windows Hello/T3 strong verification, CAM++ speaker similarity and LR-ASD active-speaker evidence. The unresolved problem is **turn-specific spoken actor binding**: proving that a particular spoken command was issued by the OWNER rather than merely occurring while the OWNER is present.

Historical Step-3 work explored promoting combined face/speaker/ASD evidence into T2 `CORROBORATED_OWNER`. That work never reached the production acceptance required to let biometric/voice evidence independently authorize consequential work.

Later JARVIS Hands owner testing exposed a separate UX problem: requiring a fresh Windows Hello prompt for every ordinary governed local action was unnecessarily disruptive after the owner had just strongly verified.

These are different problems and must not be conflated.

## Decision

### 1. Turn-specific spoken actor binding remains deferred

CAM++, LR-ASD, visual OWNER presence, or their combination do **not** independently mint execution authority or establish that the OWNER spoke the current turn.

General biometric/voice-derived T2 promotion remains disabled until a future actor-binding package is researched, calibrated, attack/degraded tested, and owner accepted.

### 2. Hands may use a bounded post-T3 T2 convenience window

A successful **direct-user Windows Hello/T3 verification** may establish an in-memory T2 `CORROBORATED_OWNER` convenience window for eligible non-critical direct-user work.

Constraints:

- absolute 30-minute lifetime;
- non-sliding;
- same authority-broker/session only;
- cleared when the broker/session closes;
- direct-user origin only;
- proactive/model-suggested work cannot inherit it;
- every action still receives a fresh proposal, deterministic risk classification, policy evaluation, one-time permit, execution verification and audit;
- CRITICAL and RESTRICTED_DEV_ONLY work never treats cached T2 as a substitute for required T3;
- exact-action strong verification remains required whenever canonical policy/risk demands T3.

This T2 state derives from a prior accepted T3 event plus bounded session state, **not from probabilistic biometric confidence**.

## Why

This preserves both safety and usable daily control:

- unfinished speaker/active-speaker evidence does not gain authority merely to reduce prompts;
- ordinary owner-requested non-critical work can avoid repetitive Windows Hello after a recent strong verification;
- critical actions retain strong exact-action verification;
- future actor-binding research still has a clear place to plug in without creating a second authorization system.

## Deferred actor-binding package

When resumed, treat spoken actor binding as one bounded research/acceptance package:

1. define the turn-specific multi-signal binding rule;
2. calibrate speaker evidence with realistic OWNER/non-OWNER data;
3. use active-speaker evidence as corroborative/negative evidence rather than sole authority;
4. evaluate overlap/speaker-change and replay/off-camera cases;
5. add anti-spoof only if current research shows material benefit;
6. validate OWNER, non-OWNER, overlap, replay, lost visual binding and stale evidence;
7. only then consider deriving `actor_unambiguous=true` or biometric-origin T2.

## Consequences

Positive:

- no false claim that face presence proves speech authorship;
- Hands UX is practical after real strong verification;
- authority remains deterministic and auditable;
- future actor binding can be added behind existing `InteractionContext`/Authority boundaries.

Tradeoff:

- JARVIS still cannot treat normal voice alone as proof of OWNER authorship for actions whose policy explicitly requires actor-unambiguous spoken authority.

## Historical branch disposition

Open PR #18 contains useful historical Step-3 hardening/actor-binding evidence, but it is not the production source of truth and must not be merged wholesale into current main. Main has evolved substantially through memory, research, capability runtime, Hands and Pocket/stability work.

Future actor-binding implementation should be rebuilt/rebased from current main after fresh research rather than reviving that branch as-is.
