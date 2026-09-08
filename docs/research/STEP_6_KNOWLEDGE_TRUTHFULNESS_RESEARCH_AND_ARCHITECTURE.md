# Step 6 — Knowledge, Current Research, and Truthfulness

Date: 2026-09-08

## Status

**RESEARCH COMPLETE — ARCHITECTURE PROPOSED — IMPLEMENTATION REQUIRES OWNER APPROVAL**

Step 6 covers CAP-014 through CAP-017:

- CAP-014 Knowledge and Source Routing;
- CAP-015 Current Information and Deep Research;
- CAP-016 Trusted Domain Knowledge;
- CAP-017 Fact Checking and Truthfulness.

Permanent product intent recovered from `PRODUCT.md`:

- select the appropriate source rather than treating model knowledge as universally sufficient;
- current external information must be source-backed;
- specialist/high-stakes questions should prefer authoritative evidence;
- JARVIS must distinguish known, remembered, current-verified, inferred, stale, uncertain, and unavailable states when relevant;
- capability limitations must be stated plainly;
- commodity search/retrieval should adopt mature existing technology rather than be rebuilt.

Legacy evidence reinforces the same goals but does not authorize the old knowledge-router/composer architecture. V1 keeps one conversation/context authority and rejects a second generic brain.

---

## Research-first technology comparison

### Candidate A — Gemini Live API built-in Google Search

Google officially supports Grounding with Google Search in the Live API. The current Gemini Live API can combine Google Search with normal function tools.

LiveKit's Google plugin also exposes `google.tools.GoogleSearch()` as a provider tool. Importantly, the exact LiveKit `1.7.1` source pinned by JARVIS already contains this provider tool with `exclude_domains`, `blocking_confidence`, and `time_range_filter` support.

**Benefit:**

- lowest-latency path;
- no extra API/provider/account;
- provider chooses when search is useful;
- works naturally inside native-audio conversation.

**Blocking limitation for Step 6 truthfulness:**

Google's Live response schema contains `LiveServerContent.grounding_metadata`, including grounding chunks/supports/search queries. However, the exact LiveKit Google realtime adapter at JARVIS's pinned `1.7.1` does not forward, emit, or retain `grounding_metadata`. Its `_handle_server_content()` processes model content, transcriptions, completion, and interruption but ignores the grounding metadata field.

A check of current LiveKit `main` shows the same omission as of this research date.

Therefore simply enabling `google.tools.GoogleSearch()` would allow the model to use current web information, but JARVIS would not have a stable public LiveKit surface for source URLs/claim provenance. That fails CAP-015/CAP-017's requirement that source-backed current claims be observable and auditable by JARVIS rather than trusted blindly because the realtime model says it searched.

**Decision:** do not modify/subclass LiveKit private realtime internals merely to intercept `grounding_metadata`.

### Candidate B — Gemini Interactions API + Google Search

Google's Interactions API is GA as of June 2026 and is recommended by Google for new Gemini application work.

A normal Interactions API request may use:

```python
client.interactions.create(
    model="gemini-3.7-flash",
    input=question,
    tools=[{"type": "google_search"}],
)
```

The returned interaction provides observable steps:

```text
google_search_call
  -> queries executed

google_search_result
  -> search result metadata / search suggestions

model_output
  -> text
  -> inline url_citation annotations
       url
       title
       start_index
       end_index
```

This is the exact missing provenance surface.

JARVIS already pins `google-genai==2.22.0`, whose Interactions API implementation is current. No new Python dependency or provider account is required.

**Decision: SELECT / ADAPT as Step-6 primary current-information boundary.**

### Candidate C — Gemini Deep Research agent

Google currently exposes `deep-research-preview-04-2026` and `deep-research-max-preview-04-2026` through the Interactions API. Deep Research autonomously plans/searches/reads/synthesizes and runs as a background task because research can take minutes.

This is mature enough to retain as a Step-6 later slice for explicit complex research, but it is inappropriate for every ordinary voice question because of latency, cost, and preview-agent behavior.

**Decision:** retain as a later explicit deep-research path; do not put it on normal realtime conversation.

### Candidate D — Brave Search API

Brave offers a large independent web index, freshness/date filtering, source metadata, and Search Goggles that can boost/downrank/discard domains. It is technically attractive for deterministic trusted-domain search and costs roughly $5/1000 Search requests at the researched pricing.

**Decision:** do not add another external search credential/provider yet. Revisit only if same-provider Gemini search cannot meet the frozen trusted-domain acceptance gates.

### Candidate E — Tavily / other agent-search APIs

Current specialist agent-search products provide domain and freshness controls and can be useful for explicit source-filtered workflows.

**Decision:** not selected for the first slice. Adding another service before testing the source-rich Gemini API already present in JARVIS would violate the project's research-first preference for the smallest mature integration that solves the requirement.

---

## Selected Step-6 architecture

### Principle

**Realtime Gemini remains the conversational brain. A JARVIS-owned research adapter becomes an evidence service, not a second conversation brain.**

```text
user speaks
   |
   v
existing Gemini Live realtime conversation
   |
   | when current/external verification is needed
   v
JARVIS function tool: research_current
   |
   | exact latest accepted canonical USER question
   v
CurrentResearchService
   |
   v
same active Gemini provider/account
Interactions API + Google Search
   |
   +-> synthesized research answer
   +-> executed search queries
   +-> URL citation annotations
   +-> source titles / URLs
   +-> retrieval timestamp
   |
   v
JARVIS ResearchResult / EvidenceSource
   |
   +-> bounded tool result to realtime Gemini
   +-> privacy-safe provenance/diagnostics for future HUD
   |
   v
spoken answer
```

### Why this is not a second brain

- the canonical conversation remains `ConversationSession`;
- the realtime model remains the user-facing conversational model;
- research requests are stateless with respect to canonical JARVIS conversation unless JARVIS explicitly supplies bounded context;
- Interactions server history is never canonical JARVIS history;
- the research adapter cannot mutate memory, identity, authority, files, devices, or conversation truth;
- it returns evidence + a bounded synthesis only;
- `ContextAssembler` remains the ordinary Step-4 context owner;
- Phase-4.5E automatic memory injection stays disabled.

---

## JARVIS-owned evidence contract

Provider-specific interaction objects must not leak into core JARVIS state.

Proposed provider-independent types:

```text
EvidenceSource
  source_id
  url
  title
  domain
  retrieved_at
  cited_text/span metadata when available

ResearchResult
  status
  answer
  sources[]
  executed_queries[]
  researched_at
  freshness intent/window
  source_policy result
  failure reason if unavailable
```

Suggested result status vocabulary:

```text
CURRENT_VERIFIED
GROUNDED_GENERAL
TRUSTED_SOURCE_VERIFIED
CONFLICTING_EVIDENCE
INSUFFICIENT_EVIDENCE
RESEARCH_UNAVAILABLE
```

The provider can supply evidence, but JARVIS owns these result states.

---

## Query authority

The realtime model should **not** be permitted to silently rewrite the user's question into an unrelated research task.

The first `research_current` tool should therefore be zero-argument or semantically bounded from the realtime model's perspective, following the successful Step-4.5D pattern:

```text
latest accepted canonical USER turn
 -> JARVIS research policy
 -> exact/bounded research request
 -> external evidence
```

The research model may generate Google search queries internally as part of Google's grounded-search workflow, but JARVIS retains the original canonical user question and records the executed queries returned by the API.

---

## Source-routing policy

Step 6 must not search the web for every sentence.

Initial intended routing classes:

```text
MODEL_OK
CURRENT_WEB_REQUIRED
TRUSTED_DOMAIN_REQUIRED
DEEP_RESEARCH_REQUESTED
UNSUPPORTED_SOURCE
```

### Mandatory-search examples

The acceptance corpus must include:

- explicit requests to search/check/verify online;
- latest/current/today/recent developments;
- rapidly changing prices, availability, schedules, product/service status, software/API behavior;
- claims whose truth materially depends on fresh external evidence.

### Model-only examples

- stable explanations where freshness is irrelevant;
- writing/rephrasing/brainstorming;
- reasoning from user-provided text;
- conversational follow-ups that require no external fact.

### Trusted-domain examples

High-stakes/specialist requests should not be declared verified merely because a random web page was cited. The source policy must be JARVIS-owned and evaluated after retrieval.

The first implementation must **not hardcode a giant universal domain allowlist**. Step 6.3 will freeze a small task/domain corpus and source-class policy first. If Gemini Google Search cannot reliably return acceptable authoritative citations under that policy, then a raw search adapter with stronger deterministic domain filtering (Brave Goggles/site filters or another mature search API) becomes justified.

---

## Truthfulness rules

1. No search result => no claim that the web was checked successfully.
2. No citations => no `CURRENT_VERIFIED` status.
3. A citation proves only that a source was used; source quality is a separate JARVIS policy decision.
4. Search/model synthesis is evidence, not canonical personal memory.
5. Conflicting credible sources must remain visibly conflicting; JARVIS must not silently pick a preferred story.
6. If a claim is time-sensitive, the response should carry a research timestamp/freshness meaning internally.
7. Stable model-knowledge answers should not pretend they were live-verified.
8. Provider/search failure must produce `RESEARCH_UNAVAILABLE` rather than a confident stale answer where current verification was required.
9. Tool arguments/results must never grant execution or memory-write authority.
10. Ordinary spoken answers stay concise; source details remain available for “what are your sources?” and later HUD presentation.

---

## Important implementation roadblocks discovered

### 1. LiveKit realtime grounding metadata is currently not surfaced

This is the main reason not to implement Step 6 by merely adding `google.tools.GoogleSearch()` to the realtime model.

### 2. `on_user_turn_completed()` is not usable with the current accepted turn-detection architecture

LiveKit documents that `Agent.on_user_turn_completed()` can be used for RAG before a reply, **but with realtime models it requires agent-side turn detection instead of provider-side realtime turn detection**.

JARVIS deliberately uses Gemini provider-native activity/turn completion in the currently accepted voice path. Changing this just to implement research would reopen Step-2 audio/turn behavior and is not justified.

Therefore Step 6 should use a normal function-tool call instead of replacing the accepted voice-turn architecture.

### 3. Gemini Live tool configuration is not freely mutable

The pinned realtime adapter reports `mutable_tools=False`; tools should be attached at session startup rather than dynamically swapped per turn. Step 6 should add one stable bounded research tool, not dynamic tool churn.

---

## Proposed Step-6 slices

### 6.1 — Source-rich current research foundation

Implement:

- provider-independent `EvidenceSource` / `ResearchResult` contract;
- Gemini Interactions + Google Search adapter using existing active-provider credentials;
- claim-linked citation extraction;
- exact latest canonical USER question grounding;
- bounded `research_current` realtime function tool;
- `RESEARCH_UNAVAILABLE` fail-closed behavior;
- privacy-safe diagnostics;
- frozen English/Hinglish/Hindi current-vs-stable evaluation corpus.

No Deep Research yet.

### 6.2 — Source routing + truthfulness acceptance

Freeze/evaluate routing behavior for:

- stable/model-only questions;
- explicit web/search requests;
- current/latest/rapidly changing facts;
- unavailable research;
- conflicting sources;
- “what are your sources?” follow-ups;
- no fake `CURRENT_VERIFIED` claims without citations.

Do not guess routing thresholds from anecdotes; use a frozen corpus and real owner voice tests.

### 6.3 — Trusted-domain verification

Research/freeze a small source-class policy for specialist/high-stakes categories.

First attempt:

- same Gemini research adapter;
- post-retrieval deterministic source-policy validation;
- abstain/research-unavailable if authoritative evidence is absent.

Only if evidence shows native Google Search cannot satisfy source constraints should Step 6 add a separate raw-search adapter such as Brave with Goggles/site filtering.

### 6.4 — Explicit deep research

Optional later slice:

- explicit deep-research request only;
- Gemini Deep Research agent through Interactions API;
- background task/progress/cancel/result contract;
- cited final report;
- no blocking normal realtime voice session for several minutes.

This slice is not required before 6.1–6.3 prove the normal source-aware foundation.

---

## Acceptance direction

The first Step-6 implementation should be accepted only if owner-machine evidence demonstrates at minimum:

1. a stable question can be answered without unnecessary web research;
2. an explicit current/latest question invokes research and returns real citations;
3. the research tool is grounded to the user's actual accepted question;
4. source URLs/titles are captured by JARVIS, not merely spoken by the model;
5. a simulated/search-provider failure does not become a stale confident answer;
6. a current claim without citations cannot be labeled current-verified;
7. English, Hindi, and Hinglish work;
8. normal wake/barge-in/conversation behavior remains intact;
9. memory/identity/authority state is unaffected;
10. no raw provider payload logging or uncontrolled server-side conversation history becomes canonical JARVIS state.

---

## Primary research sources

Official / primary sources consulted:

- Google AI — Grounding with Google Search: https://ai.google.dev/gemini-api/docs/google-search
- Google AI — Live API tool use: https://ai.google.dev/gemini-api/docs/live-api/tools
- Google AI — Interactions API overview: https://ai.google.dev/gemini-api/docs/interactions-overview
- Google AI — Interactions API reference: https://ai.google.dev/api/interactions-api-v1
- Google AI — URL Context: https://ai.google.dev/gemini-api/docs/url-context
- Google AI — Deep Research agent: https://ai.google.dev/gemini-api/docs/deep-research
- Google Gen AI SDK docs: https://googleapis.github.io/python-genai/
- LiveKit — Tool definition and use: https://docs.livekit.io/agents/logic/tools/
- LiveKit — Pipeline nodes and hooks: https://docs.livekit.io/agents/logic/nodes/
- LiveKit Google plugin/source at exact JARVIS pinned `livekit-agents@1.7.1`
- Brave Search API: https://brave.com/search/api/
- Brave Goggles docs: https://api-dashboard.search.brave.com/documentation/resources/goggles

## Technology decision

**ADAPT the existing provider stack rather than introducing a new search framework.**

For normal current-information work, use a thin JARVIS-owned research service over the already-installed Gemini Interactions API + Google Search because it exposes the source/citation surface that LiveKit realtime currently hides.

Keep realtime conversation native and unchanged. Keep Deep Research and a second raw-search provider as later evidence-driven options, not default architecture.
