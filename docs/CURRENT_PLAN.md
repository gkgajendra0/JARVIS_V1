# JARVIS V1 Current Plan

## Active Work

**Step 6 — Knowledge, Current Research, and Truthfulness (CAP-014 through CAP-017) — OWNER ACCEPTED / FINAL MERGE GATE.**

After the Step-6 protected-main merge, the next work is a **bounded Step-2 voice-session robustness correction** discovered during Step-6 acceptance. Step 7 remains planned and must not start until that regression is fixed and owner-tested.

## Current Stage

**STEP 4 BOUNDED COMPLETE — STEP 5 BOUNDED COMPLETE — STEP 6 OWNER ACCEPTED — FINAL EXACT-HEAD CI / PROTECTED-MAIN MERGE — THEN STEP-2 LONG-UTTERANCE CORRECTION.**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed research/evidence belongs in `docs/research/`.

---

## Accepted foundations carried forward

Step 4 remains bounded complete with encrypted canonical memory, explicit remember/inspect/correct/forget, accepted FTS5 + Qwen retrieval/reranking, and bounded provider-assisted `recall_memory`. The strict independent 4.5D verifier and Phase-4.5E automatic semantic-memory injection remain deferred.

Step 5 remains bounded complete with deterministic terminal provider-failure diagnosis, Windows-local truthful status speech, safe failed-session closure, and return toward wake/idle. Full local/offline conversation remains deferred.

---

## Step 6 — accepted bounded outcome

Step 6 now provides the accepted source-aware web-research foundation:

```text
latest canonical USER request
        |
        v
active conversational brain
Gemini / OpenAI / future replacement
        |
        | decides research is useful/required
        | forms bounded supporting search queries
        v
JARVIS search_web tool
        |
        v
CurrentResearchService
        |
        v
replaceable live-web retrieval adapter
        |
        +-> accepted first adapter: Exa Search
        |
        v
normalized real source evidence
URLs + titles + domains + excerpts + timestamps
        |
        v
JARVIS truth/source sufficiency policy
        |
        v
active brain synthesizes the spoken answer
```

Accepted boundaries:

- `JARVIS_AI_PROVIDER` remains the conversational-brain selector;
- live-web retrieval is independent of the active brain and replaceable behind a JARVIS contract;
- JARVIS owns canonical turn anchoring, provenance normalization, truth/research status, source sufficiency, privacy-safe logs, and fail-closed behavior;
- retrieved webpages are untrusted evidence and gain no memory/identity/permission/file/device/execution authority;
- stable model-knowledge questions are blocked from unnecessary network research by a deterministic warrant gate;
- explicit search/research/current requests can use live evidence;
- `fact_check` requires multiple source domains before returning success;
- `authoritative` requires a bounded curated official/primary-source signal;
- provider/search failure is reported as unavailable rather than silently presented as freshly verified;
- automatic Phase-4.5E memory injection remains disabled.

Acceptance evidence:

- `docs/research/STEP_6_KNOWLEDGE_TRUTHFULNESS_RESEARCH_AND_ARCHITECTURE.md`
- `docs/research/STEP_6_KNOWLEDGE_TRUTHFULNESS_ACCEPTANCE.md`

Owner-machine evidence on 2026-09-08 included:

- real-network Exa smoke: `multi_source_researched`, 8 real sources, `PASS`;
- stable SQL JOIN question answered without a web-research completion event;
- explicit current Google/Gemini request: Exa `authoritative_source_present`, 8 sources, `explicit_research_request` warrant;
- source follow-up named only observed official Google source families;
- explicit owner acceptance of Step 6 as complete.

Deferred Step-6 extensions remain:

- multi-minute/background Deep Research agents;
- browser automation;
- Step-7 local project/file knowledge;
- universal trusted-domain classification;
- proactive/background recurring research;
- automatic semantic-memory injection;
- simultaneous multi-search-backend routing without measured need.

---

## Reopened Step-2 robustness defect — next bounded work

Step-6 voice acceptance exposed a pre-existing Step-2 defect: long spoken requests can be cut off and the active session can return to wake/idle before the realtime provider commits the user turn.

Fresh research identified the architecture mismatch:

- production `AgentSession` currently passes `vad=None`, explicitly opting out of LiveKit VAD;
- JARVIS inactivity timers rely on `user_state_changed` to know that the user is actively speaking;
- LiveKit documents `user_state_changed` as VAD-driven;
- the initial timer is 8 seconds and follow-up timer is 15 seconds;
- therefore a long utterance can remain invisible to the outer inactivity policy until its final provider commit, allowing the inactivity timer to end the session mid-speech.

Approved correction direction after Step-6 merge:

1. branch from the new protected `main`;
2. retain Gemini/OpenAI realtime-provider native turn completion;
3. restore LiveKit bundled VAD as the local speaking/listening activity signal rather than as a second turn authority;
4. when user state becomes `speaking`, cancel the inactivity shutdown timer instead of arming a 15-second utterance kill timer;
5. when the user becomes inactive/listening, arm the appropriate initial/follow-up inactivity timeout;
6. keep `max_utterance_seconds` only where it is genuinely a bounded diagnostic audio-buffer limit unless a separate evidence-backed user-turn safety policy is later required;
7. add regression tests proving continuous speech is not terminated by the old max-utterance timeout;
8. owner-test a deliberately long research/fact-check sentence plus normal short queries and barge-in behavior.

Research references are the current LiveKit turn/session/VAD documentation and Gemini Live automatic activity-detection documentation reviewed on 2026-09-08.

---

## Immediate Next Action

**FINAL EXACT-HEAD STEP-6 CI -> SQUASH MERGE PR #24 -> CREATE FRESH STEP-2 ROBUSTNESS BRANCH -> IMPLEMENT + TEST THE LONG-UTTERANCE FIX.**
