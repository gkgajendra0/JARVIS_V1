# Next personal-assistant gap inspection —22October2026

## Verified North Star priority

The owner clarified that the next milestone must follow the personal-intelligence North Star rather than the numbered Step8roadmap. Source: [North Star17.9](../AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md#179-prioritized-capability-delivery-and-gono-go-tests): PI-1dependable memory use, PI-2governed natural learning, **PI-3contextual assistance across life domains**, then PI-4situated/proactive intelligence and PI-5continual adaptation. [Section17.5](../AUTONOMOUS_SELF_MANAGEMENT_MASTER_PLAN.md#175-automatic-context-use--the-defining-capability) requires relevant current/source-backed context AND demonstrably useful answers. [Product](../PRODUCT.md#owner-centered-personal-intelligence-contract) gives concrete food/vehicle/decision examples.

Direction is established; the exact next code change is not yet justified. PI-1has bounded accepted saved-preference use. PI-2is implemented/software-verified in the candidate, with full qualification/owner acceptance deferred/open. That status is not a claim that all PI-2gates passed. PI-3is partially implemented already; complete its observed gaps before proposing another layer.

## Existing implementation to reuse

`src/jarvis/voice/agent.py` already has context catalog/read instructions: choose relevant current facts, omit irrelevant context, avoid invented motives/restrictions and clarify missing evidence. Learning-mode instructions are integrated, not a proposed new brain. `voice/production_runtime.py` composes normal-app context/learning; `voice/personal_context.py` owns guarded release. Canonical memory and conversation retain state/authority ownership. The earlier [normal-runtime design](../superpowers/specs/2026-10-20-personal-intelligence-runtime-design.md) explicitly chooses the actual voice model for relevance and a bounded tool path, not another HTTP model on each conversation.

## Next bounded behavior to investigate

Inspect normal-app answers that combine multiple permitted facts with the current question, preserve corrections/unknowns, and resolve supported conversational references. Use general fictional examples without requiring owner-written scenarios. Determine which requirement is already satisfied and which reproducible gap needs code. A retrieved fact is not proof of a useful answer; an unrun scenario is not a failure or pass. Existing qualified/deferred outcomes remain unchanged. Respect fresh-wake/private-history retirement and the private-session authority model; seamless follow-ups or durable episode retention cannot be smuggled in as simple prompt changes.

Relevant Work/Hands decisions belong to PI-3after ordinary contextual assistance is understood. Reuse existing Work/Authority when a measured use case reaches actions. No new memory store, incompatible personal brain, new durable episode category, model switch or proactive authority is approved by this inspection.

## Correction of the earlier reminder candidate

The earlier task/reminder recommendation in this file is SUPERSEDED as the immediate personal-intelligence priority. Source inspection still stands: WorkRuntime is optional; WorkType.REMINDERis only a type name; CAP-027notes/CAP-028tasks/reminders are PLANNED in Step8. These facts do not make reminders the next North Star milestone. They may be useful later within an explicitly chosen scope. Preserve the numbered roadmap; do not silently redirect current work to it.

Next deliverable: an existing-path gap map and a concrete research/design decision for the smallest PI-3behavior still missing. Technology research follows the actual gap and compares credible approaches broadly before narrowing. No product code is changed by this note.


## First concrete PI-3inspection

The [contextual-assistance gap map](PI3_CONTEXTUAL_ASSISTANCE_GAP_MAP_2026-10-22.md) records the current opaque-item catalog limitation, separates forced-index research reads from actual model selection, compares native bounded tools/standing profiles/external engines and proposes a narrowly scoped PI-3Aselection-and-grounded-use slice. This is inspected information flow and proposed design scope, not reproduced normal-model failure, approved architecture or new implementation. No provider call was sent.
