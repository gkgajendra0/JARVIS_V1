# Provider Model Lifecycle Self-Evolution

## Status

**OWNER-DIRECTED PERMANENT SELF-MANAGEMENT REQUIREMENT — 2026-09-30**

This document records the provider/model lifecycle obligation discovered during the
Gemini Live 3.1 -> 3.8 migration incident.

It is subordinate to:

- `AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md`;
- `GOVERNED_AUTONOMOUS_ENGINEERING_MASTER_PLAN.md`;
- accepted Authority, Self-Awareness, Incident, EngineeringChange, verification,
  promotion and rollback contracts.

## 1. Owner intent

The owner must not be required to notice that a cloud model has become legacy,
deprecated, retired, unavailable, or behaviorally incompatible and then manually tell
JARVIS which replacement to use.

Provider model lifecycle is a JARVIS self-management responsibility.

The target behavior is:

```text
provider lifecycle signal OR runtime/model-health regression
        |
        v
canonical lifecycle / behavioral evidence
        |
        v
is an accepted deterministic replacement already known?
       / \
     yes  no
     |     |
     v     v
compatibility   authoritative provider research
probe            + recommended replacement evidence
     \           /
      v         v
      candidate replacement
             |
             v
adapter/config compatibility
             |
             v
isolated handshake + synthetic behavior smoke
             |
             v
persist replacement configuration
             |
             v
controlled runtime restart/reconciliation
             |
             v
post-migration voice/provider SLO observation
        /                    \
      pass                   fail
       |                      |
       v                      v
accept lifecycle         automatic rollback
migration               + engineering incident
                              |
                              v
                    governed autonomous engineering
```

## 2. Authoritative lifecycle evidence

Provider lifecycle decisions must be based on first-party provider evidence whenever it
exists. For Gemini, accepted lifecycle evidence includes:

- Gemini API model-status/lifecycle metadata where exposed;
- Gemini API deprecations documentation;
- Gemini API release notes;
- a provider terminal `model unavailable` response.

Search-engine summaries, model guesses, forum posts, and model confidence are not
sufficient to authorize a replacement.

The lifecycle vocabulary should preserve provider facts such as:

- STABLE;
- PREVIEW;
- LEGACY;
- DEPRECATED;
- RETIRED;
- announced retirement/shutdown time;
- provider-recommended replacement.

## 3. Production selection rule

Production should prefer a **specific stable model ID**, not a moving `latest` alias.

A moving alias may be useful for evaluation but must not silently hot-swap the production
voice brain because that bypasses JARVIS compatibility and behavioral acceptance.

## 4. Narrow pre-authorized automatic migration

The owner pre-authorizes JARVIS to perform a model-lifecycle migration without asking
for manual approval only when **all** of the following are true:

1. the current provider/model is observed as LEGACY, DEPRECATED, RETIRED, unavailable,
   or has an explicit first-party recommended replacement;
2. the replacement identity comes from authoritative provider evidence;
3. the replacement serves the same required product surface (for example Live
   audio-to-audio realtime conversation);
4. the replacement does not require broader credentials, Authority, filesystem,
   network, device, or security scope;
5. the installed provider adapter is compatible with the replacement;
6. an isolated provider handshake/synthetic smoke succeeds;
7. required deterministic and regression tests pass;
8. the previous model/configuration remains available as a rollback target when the
   provider has not retired it completely;
9. production observation confirms accepted provider/voice behavioral SLOs after the
   switch.

This exception authorizes **configuration lifecycle maintenance**, not unrestricted
source evolution.


### 4.1 Pending migration acceptance and rollback

A replacement is not accepted merely because its setup websocket opens. Every automatic
migration is durably journaled as `pending` with the previous and candidate model IDs.

The pending migration becomes `accepted` only after production receives a real owner
turn and completes a non-interrupted assistant playback. An assistant message that is
immediately interrupted is not sufficient acceptance evidence.

While a migration is pending, any of the following request rollback evaluation:

- startup/preflight failure;
- provider `MODEL_UNAVAILABLE`;
- the deterministic repeated-wake / zero-committed-turn degradation threshold.

Rollback itself is fail-closed: JARVIS first performs a Live handshake against the
previous model. Only a still-usable previous model may be restored automatically. If
that rollback probe fails, JARVIS keeps canonical degraded/incident evidence and
escalates rather than blindly restoring a retired or unavailable model.

A candidate that was automatically rolled back is blocked from immediate automatic
retry. The current bounded policy applies a six-hour cooldown before the same
provider-recommended candidate may be evaluated again. Every retry must repeat the
authoritative lifecycle lookup and Live handshake, so a transient production regression
cannot create a tight migration/rollback loop. A governed engineering change may also
supersede the candidate or policy before that cooldown expires.

## 5. When source changes are required

If the provider-recommended replacement changes API/session semantics enough that source
changes are required, the event becomes an EngineeringChange backed by the canonical
incident and provider evidence.

JARVIS should autonomously perform research, diagnosis, architecture comparison,
isolated implementation, tests, CI, hardware/synthetic acceptance where possible,
rollback preparation, documentation, and promotion preparation.

For this specific provider-lifecycle maintenance class, the owner intent is to remove
routine manual intervention. A future bounded autonomous-promotion policy may
auto-promote only when its separately reviewed deterministic conditions prove that:

- no Authority/security boundary changed;
- the change is limited to provider compatibility/lifecycle adaptation;
- independent CI and behavior acceptance pass;
- rollback is executable;
- protected production health is observed after promotion.

Until that bounded promotion policy exists in production, the existing protected-main
governance remains the execution boundary; this document is the permanent requirement
that the missing automation be implemented rather than forgotten.

## 6. Behavioral health obligations

Provider connectivity alone is not proof that voice is healthy.

JARVIS must observe behavior-level evidence including at least:

- repeated successful wake detections followed by zero committed USER turns;
- recurrent provider internal/server errors such as Live websocket 1011;
- abnormal wake-to-turn latency;
- repeated immediate interruption of valid responses;
- wake audio leaking into conversational USER turns;
- persistent session timeouts despite healthy physical microphone capture.

A single owner wake followed by no request is normal and must not create an incident.
Detection requires a bounded repeated pattern or stronger provider evidence.

When a deterministic threshold is crossed, JARVIS must:

1. publish `runtime.voice` or `runtime.provider` degraded health;
2. persist/correlate an Incident;
3. prefer a registered deterministic recovery if one exists;
4. otherwise admit the incident to the governed unknown-incident engineering path.

## 7. Learning and self-evolution

Verified lifecycle migrations and failed migration attempts are EngineeringKnowledge.

The system must retain:

- old model and replacement identities;
- provider lifecycle evidence;
- adapter/plugin versions;
- behavioral differences discovered during migration;
- verification and acceptance results;
- rollback outcome;
- exact source/config revision.

Future model changes should retrieve and reuse this evidence before experimentation.

The long-term definition of self-evolution for provider models is therefore not
"automatically choose whatever model is newest." It is:

> **observe lifecycle change, establish authoritative evidence, adapt safely, verify
> behavior, migrate or repair, learn the result, and continue operating without making
> the owner discover routine provider churn.**

## 8. 2026-09-30 incident lessons

The Gemini 3.1 -> 3.8 incident exposed two missing sensors:

1. recoverable realtime provider errors were logged without canonical degraded provider
   health;
2. repeated wake-triggered sessions with zero committed user turns were logged but were
   not canonical voice-health evidence.

The migration branch closes both observability gaps:

- recoverable provider errors are mirrored into Self-Awareness as degraded health;
- three consecutive wake-triggered sessions without a committed user turn degrade
  `runtime.voice`, while a committed user turn resets/recoveries the condition.

The incident also proved that provider-native barge-in must own realtime interruption
for Gemini Live; JARVIS must not add a duplicate programmatic interruption that races
the new owner turn.
