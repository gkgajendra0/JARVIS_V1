# Step 6 — Knowledge, Current Research, and Truthfulness Acceptance

Date: 2026-09-08

## Status

**OWNER ACCEPTED — READY FOR FINAL DOCUMENTATION/CI/MERGE**

This evidence closes the bounded Step-6 source-aware research foundation for CAP-014 through CAP-017. It does not claim the deferred multi-minute/background Deep Research lifecycle, browser automation, local project/file intelligence, universal trusted-domain classification, or automatic memory injection.

## Accepted architecture

- The active conversational brain remains selected by `JARVIS_AI_PROVIDER` and performs semantic research planning and final synthesis.
- Live-web retrieval is behind a JARVIS-owned replaceable evidence boundary.
- The first accepted retrieval adapter is Exa Search.
- JARVIS owns canonical user-turn anchoring, source/provenance normalization, bounded truth/research status, deterministic source-sufficiency policy, privacy-safe logging, and failure behavior.
- Retrieved webpage text is untrusted evidence only and has no memory, identity, permission, file, device, or execution authority.
- Changing the conversational brain does not require rewriting the research/evidence domain contract.

## Real-network owner smoke

Owner machine executed:

`python tools\research\step6_current_research_owner_smoke.py`

Observed result:

- provider: `exa`
- mode: `current`
- status: `multi_source_researched`
- source count: `8`
- smoke status: `PASS`
- real source titles, domains, URLs, excerpts, and publication metadata were returned
- official Google documentation and Google-owned sources were among the returned evidence

This proved that JARVIS captured real web evidence rather than merely allowing the model to claim that research occurred.

## Integrated voice acceptance

Owner-machine `jarvis-voice` use demonstrated:

1. Stable knowledge routing
   - Request: `Jarvis, what is a SQL join?`
   - JARVIS answered directly from model knowledge.
   - No `Web research completed` event occurred for that accepted turn.

2. Explicit fresh research
   - Request: `Search the web and tell me what Google currently recommends as the main Gemini API interface for new applications.`
   - Observed research event:
     - provider: `exa`
     - mode: `authoritative`
     - status: `authoritative_source_present`
     - source count: `8`
     - warrant: `explicit_research_request`
   - JARVIS answered that Google recommends the Interactions API for new applications and distinguished the older `generateContent` interface as supported but legacy.

3. Source provenance follow-up
   - Request: `Tell me which sources did you use for that?`
   - JARVIS named only source families actually present in retrieved evidence: official `ai.google.dev` documentation and the Google blog.
   - It did not invent unrelated sources.

4. Authoritative-source behavior
   - The explicit current research request was automatically issued in `authoritative` mode and passed the deterministic authoritative-source gate with real official Google evidence.

The owner explicitly accepted Step 6 as complete after reviewing these results.

## Separate Step-2 issue discovered during acceptance

While attempting a longer spoken fact-check sentence, the active voice session returned to wake/idle before the long utterance was committed. This is **not a Step-6 research failure**. The already accepted Step-6 research path had independently passed real-network and integrated authoritative voice evidence.

The long-utterance problem is tracked as a reopened Step-2 voice-session robustness defect. Research on 2026-09-08 identified that the production realtime `AgentSession` explicitly opted out of LiveKit VAD while the outer JARVIS inactivity timers depended on `user_state_changed`, which LiveKit documents as VAD-driven. The Step-2 correction will be implemented and accepted separately after the Step-6 protected-main merge.

## Automated validation

Exact implementation head before this acceptance-document commit:

`1f5257979ef3f5bfcaf2fadd8222b16cff98dbec`

Code Quality run `34255625106` passed:

- Ruff format/lint
- full pytest
- Windows DPAPI
- Windows Hello helper

A final exact-head CI run is required after documentation reconciliation before squash merge.

## Deferred Step-6 work

Still deferred:

- multi-minute/background Deep Research agents and lifecycle;
- browser automation;
- Step-7 local project/file intelligence;
- universal trusted-domain registry;
- proactive/background recurring research;
- automatic semantic-memory influence/injection;
- simultaneous multi-search-backend routing without measured need.

These deferrals are not claimed implemented by this acceptance.