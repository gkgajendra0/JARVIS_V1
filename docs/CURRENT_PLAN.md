# JARVIS V1 Current Plan

## Active Work

**Step 2 long-utterance robustness correction — OWNER ACCEPTED / FINAL MERGE GATE.**

After this correction is squash-merged to protected `main`, **Step 7 — Governed Capability Runtime + Local Files/System/Project Safe Reads (CAP-018, CAP-021, CAP-022, CAP-032)** becomes the next roadmap slice. Step 7 implementation is not yet authorized; it must begin with fresh requirements recovery and research.

## Current Stage

**STEP 4 BOUNDED COMPLETE — STEP 5 BOUNDED COMPLETE — STEP 6 BOUNDED COMPLETE — STEP-2 LONG-UTTERANCE CORRECTION OWNER ACCEPTED — FINAL EXACT-HEAD CI / PROTECTED-MAIN MERGE — THEN STEP 7 REQUIREMENTS + RESEARCH.**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed research/evidence belongs in `docs/research/`.

---

## Accepted foundations carried forward

Step 4 remains bounded complete with encrypted canonical memory, explicit remember/inspect/correct/forget, accepted FTS5 + Qwen retrieval/reranking, and bounded provider-assisted `recall_memory`. The strict independent 4.5D verifier and Phase-4.5E automatic semantic-memory injection remain deferred.

Step 5 remains bounded complete with deterministic terminal provider-failure diagnosis, Windows-local truthful status speech, safe failed-session closure, and return toward wake/idle. Full local/offline conversation remains deferred.

Step 6 is bounded complete with provider-neutral source-aware web research, accepted Exa retrieval, JARVIS-owned evidence/provenance/truth status, deterministic research-warrant gating, and fail-closed source sufficiency behavior.

---

## Step 6 — accepted bounded outcome

The accepted source-aware research path is:

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
- stable SQL JOIN question did not require successful web research;
- explicit current Google/Gemini request returned 8 sources including official Google documentation;
- source follow-up remained grounded to observed source families;
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

## Reopened Step-2 robustness correction — OWNER ACCEPTED

Step-6 voice acceptance exposed a pre-existing Step-2 defect: a long first spoken request could be cut off because the outer voice lifecycle could return to wake/idle before the realtime provider committed the user turn.

Fresh research and owner-machine evidence established two lifecycle causes:

1. production `AgentSession` had explicitly opted out of LiveKit local VAD while outer inactivity policy depended on user speech-state events;
2. the initial inactivity timeout could run across realtime-session startup, consuming part of the user's response window before the session reached its first real listening state.

Accepted correction:

```text
wake detected
    |
    v
AgentSession + realtime provider initialize
    |
    | no outer inactivity countdown during startup
    v
first real LiveKit listening state
    |
    +-> initial inactivity window becomes eligible
    |
    v
local speech activity: speaking
    |
    +-> cancel/suppress outer inactivity shutdown
    |
    | provider-native Gemini/OpenAI turn completion remains authoritative
    v
local speech activity: listening
    |
    +-> normal initial/follow-up inactivity timing resumes
```

Accepted invariants:

- local speech activity is lifecycle evidence only, not a second conversational turn authority;
- Gemini/OpenAI native realtime turn completion remains unchanged;
- active speech cannot be killed by the historical outer `max_utterance_seconds` timeout path;
- no initial inactivity timer runs while the realtime session is still initializing;
- an actually idle wake session still expires normally after the configured initial timeout;
- follow-up conversation and interruption/barge-in remain usable.

Owner-machine acceptance on exact code head `2543e56` proved:

- an idle wake with no user turn correctly expired after 8 seconds;
- a long SQL explanation request was committed in full as one canonical USER turn and JARVIS stayed active to answer it;
- subsequent `Jarvis, explain me in short.` was accepted in the same session;
- `Okay, Jarvis. Stop. I don't need it.` interrupted/stopped the longer interaction and JARVIS responded `Understood, sir.`

Acceptance evidence:

- `docs/research/STEP_2_LONG_UTTERANCE_ACTIVITY_ACCEPTANCE.md`

Gemini's provider-native silence/end-of-turn tuning remains unchanged because this owner-machine acceptance no longer demonstrated a need to alter it as part of the defect.

---

## Next roadmap slice after merge

**Step 7 — Governed Capability Runtime + Local Files/System/Project Safe Reads**

The next chat/work slice must start research-first. Before implementation:

1. recover CAP-018, CAP-021, CAP-022 and CAP-032 requirements from `PRODUCT.md` and accepted decisions;
2. inspect the merged repository and existing authority/tool boundaries;
3. research current mature capability-runtime, local-file/project indexing, sandbox/read-only system integration, and tool-contract options;
4. prefer proven mature technology over custom infrastructure where it satisfies JARVIS requirements;
5. propose the smallest provider-neutral governed capability contract needed by real Step-7 reads;
6. obtain owner architecture approval before implementation.

Step 7 must not create a second authority system, bypass canonical conversation/truth provenance, or quietly expand into browser automation, file writes, device control, or Step-12 coding operations.

---

## Immediate Next Action

**FINAL EXACT-HEAD CI FOR PR #25 -> SQUASH MERGE STEP-2 CORRECTION TO PROTECTED `main` -> START STEP 7 REQUIREMENTS / RESEARCH FROM THE NEW `main`.**
