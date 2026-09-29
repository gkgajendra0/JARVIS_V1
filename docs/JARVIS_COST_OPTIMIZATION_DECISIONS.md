# JARVIS Cost Optimization Decisions

Status: **DESIGN DISCUSSION / NO RUNTIME IMPLEMENTATION AUTHORIZED**

Date: 2026-09-29

## Purpose

Record owner-approved cost assumptions and the next optimization topics before enabling broader paid API use.

The target operating envelope remains approximately **₹3,000–₹4,000 per month for the whole JARVIS system**, not for one subsystem.

## Decision 1 — Keep TTS outside the paid-brain budget for now

The owner currently uses Gemini Developer API Free Tier successfully for TTS and has not observed the TTS quota exhausting in normal use.

Current planning therefore treats routine JARVIS TTS as **₹0 incremental paid-brain cost while legitimate Free Tier quota remains available**.

Planned separation:

- one Gemini project/API key for free-tier TTS / voice-output use;
- a separate paid project/API key for paid reasoning and autonomous work;
- initial paid-brain experiment budget approximately ₹500;
- no runtime change is authorized by this document;
- do not design the product around free TTS being permanent;
- retain a local TTS fallback so JARVIS can continue operating if free-tier availability, limits, pricing, or model availability change.

This decision does **not** authorize account/project rotation to evade service limits.

## Decision 2 — Optimize intelligence usage before replacing good voice UX

Because current TTS is effectively free to the owner, do not degrade the current voice experience merely to reduce a cost that is not presently being paid.

Near-term cost work should focus on paid reasoning and autonomous-intelligence paths instead.

## Next optimization topics

Discuss and design, before implementation:

1. **Global Brain Router**
   - extend routing beyond background engineering work;
   - first decide whether any paid model is needed;
   - prefer deterministic execution, existing capabilities, cached/verified knowledge and local models before cloud reasoning;
   - select the cheapest sufficient cloud target only when needed.

2. **Realtime cloud-brain activation**
   - understand when a cloud realtime session is actually required;
   - avoid paid reasoning for trivial lifecycle or already-known capability execution where possible without damaging UX.

3. **Background work / capability acquisition**
   - measure and reduce repeated research, architecture, coding, debugging and retry calls;
   - reuse verified engineering knowledge and prior solutions;
   - escalate model strength only on evidence of need.

4. **Hands / computer planning**
   - known reliable operations should become direct capability execution;
   - model planning should be reserved for ambiguous or novel actions.

5. **Memory model calls**
   - evaluate candidate extraction, semantic-recall planning and release verification for value versus API cost;
   - move suitable work to local/deterministic paths.

6. **Context/token size**
   - avoid repeatedly sending large conversation histories, logs, repository state or WorkStep evidence when bounded retrieval/summaries are sufficient.

7. **Research-provider usage**
   - measure search/research calls separately from reasoning-model calls and avoid repeated searches for already verified/current evidence.

8. **Cost observability and governor**
   - attribute provider usage by subsystem/mission;
   - track tokens, calls, retries and estimated currency cost;
   - later enforce daily/monthly/per-mission limits after routing economics are understood.

## Architectural principle

> JARVIS should use the cheapest sufficient intelligence path while preserving the desired UX, correctness, safety, owner authority and autonomy.

Cost optimization must not mean making JARVIS noticeably slower, less natural, less capable, or less reliable merely to minimize API spend.


## Decision 3 — Optimize minimally before buying paid brain credits

Do **not** buy paid API credits and immediately run capability-acquisition experiments against the known current routing inefficiencies.

Also do **not** wait for every possible cost optimization to be complete before testing.

The agreed sequence is:

1. separate TTS/voice-output billing from the paid-brain project so routine free-tier TTS does not consume the paid experiment budget;
2. evolve the existing Phase-4 Model Router toward the first Global Brain Router slice, with deterministic/local/cheap-model-first routing and stronger-model escalation only when justified;
3. add enough usage telemetry to attribute provider, model, calls, tokens, retries, stage and estimated cost to a mission;
4. then purchase approximately **₹400–₹500** of paid brain capacity;
5. run a controlled blind real-world capability-acquisition experiment;
6. inspect actual stage-by-stage cost and optimize the components demonstrated to be expensive.

The initial ₹400–₹500 purchase is therefore an **instrumented experiment budget**, not a general authorization for unrestricted paid autonomous operation.

The experiment should answer both:
- did JARVIS complete the capability autonomously within the existing owner/governance gates?;
- what did the successful or failed attempt actually cost, by stage and model path?

A later Cost Governor should enforce hard budgets after these real measurements exist.
