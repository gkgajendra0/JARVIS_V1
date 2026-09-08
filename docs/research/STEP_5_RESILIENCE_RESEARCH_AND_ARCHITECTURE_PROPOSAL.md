# Step 5 — Local/Offline Survival and Provider Resilience Research + Architecture Proposal

Date: 2026-09-08

## Status

**RESEARCH COMPLETE / ARCHITECTURE PROPOSED — OWNER APPROVAL REQUIRED BEFORE PRODUCTION IMPLEMENTATION**

Step 5 owns CAP-048 Local/Offline Survival and CAP-049 Provider/Model Replaceability. The owner explicitly authorized moving forward after Phase 4.5E automatic memory influence was deliberately deferred rather than allowed to block the roadmap.

This document selects an architecture direction. It does not install a local model, change the production provider path, or claim outage survival is already implemented.

## Required JARVIS behaviour

Step 5 must make provider/network failure a controlled degraded state rather than an architecture failure.

Minimum requirements:

1. canonical conversation, memory, identity, authority, and audit state remain JARVIS-owned during provider failure;
2. a fallback must preserve the user's request instead of silently answering a different question;
3. no retry/fallback may cause a duplicate substantive answer after partial output without an explicit policy decision;
4. unavailable cloud-only capabilities must be stated truthfully;
5. local wake/audio/vision/identity/memory foundations should remain usable where practical even when cloud intelligence is unavailable;
6. provider health/fallback/recovery decisions are deterministic JARVIS policy, never prompt-owned model decisions;
7. Step 5 should create one reusable resilience boundary for later capabilities rather than a second provider router;
8. complete offline voice survival is a later Step-5 slice, not a prerequisite for the first resilience contract.

## Repository findings

Protected-main code already gives Step 5 a useful seam:

- `src/jarvis/ai_provider.py` owns the single production `JARVIS_AI_PROVIDER` switch for Gemini/OpenAI;
- `src/jarvis/voice/livekit_session.py` creates the provider realtime model inside one `AgentSession` and translates committed provider items into a JARVIS-owned `ConversationSession`;
- `src/jarvis/voice/runtime.py` already owns wake/active/recovering lifecycle truth and returns to local wake detection when an activation fails;
- `JarvisVoiceAgent` owns instructions/tools but does not own canonical conversation truth;
- `src/jarvis/preflight.py` currently makes missing cloud credentials fatal, so complete cloud-key loss blocks startup even though local wake/vision/etc. could otherwise run;
- no accepted provider-resilience state machine or local conversational fallback exists today.

The key architectural rule is therefore: **extend the existing single provider/session boundary; do not introduce a second conversation owner or generic router.**

## Current technology research

### LiveKit public runtime handoff — ADAPT

Current LiveKit documentation exposes `AgentSession.update_agent()` as the public mechanism for handing a running session to another agent. The documentation explicitly says realtime models cannot be swapped in-place with `Agent.update_options()`; changing away from a realtime model requires an agent handoff with `update_agent()`.

This is a strong match for JARVIS because a cloud-native realtime agent can remain the primary experience while a separately configured local STT/LLM/TTS pipeline agent becomes a degraded-mode target without replacing the outer JARVIS audio/wake/session owner.

Important context rule: LiveKit agent handoffs do not make provider history canonical for us. JARVIS should construct a bounded handoff context from its own accepted `ConversationSession` / `ContextAssembler`, rather than blindly carrying arbitrary provider-native history/tool state.

References:

- https://docs.livekit.io/agents/logic/agents-handoffs/
- https://docs.livekit.io/agents/logic/sessions/

Decision: **ADAPT** public `AgentSession.update_agent()` as the controlled realtime-to-pipeline handoff mechanism.

### LiveKit fallback adapters — ADOPT inside pipeline mode, not as the top-level JARVIS authority

LiveKit now provides agent-side `stt.FallbackAdapter`, `llm.FallbackAdapter`, and `tts.FallbackAdapter`. They react to connection failures, timeouts, 4xx/5xx errors, and some mid-stream failures; unhealthy providers are skipped and probed for recovery.

The framework also documents partial-output guards: an LLM fallback normally does not restart a response after text/tool output has already been streamed unless explicitly configured to do so, and TTS does not restart after audio has reached the speaker.

These are valuable mature mechanics for a pipeline mode, but JARVIS still needs its own top-level mode/capability policy because switching between native realtime and a local pipeline changes capabilities, latency, voice, tool support, and context mechanics.

Reference:

- https://docs.livekit.io/agents/logic/fallback-strategies/

Decision: **ADOPT later inside a pipeline where useful; do not make the adapters the JARVIS resilience authority.**

### Ollama as the first local LLM runtime — ADOPT for benchmark/integration candidate

LiveKit has an official Python Ollama integration using its existing OpenAI plugin:

```python
openai.LLM.with_ollama(
    model="...",
    base_url="http://localhost:11434/v1",
)
```

This avoids a custom Ollama SDK/HTTP layer and keeps model mechanics behind the existing LiveKit abstraction.

Ollama runs natively on Windows and serves a localhost API. Its hardware documentation explicitly lists RTX 5060 Ti under NVIDIA compute capability 12.0 support. Ollama also exposes VRAM-aware model scheduling controls, which matters because the JARVIS owner machine has 8 GB dedicated VRAM shared with vision/identity/Qwen workloads.

References:

- https://docs.livekit.io/agents/models/llm/ollama/
- https://docs.ollama.com/windows
- https://docs.ollama.com/gpu
- https://docs.ollama.com/faq

Compared with `llama.cpp`: `llama.cpp` is mature, Windows-capable, GPU-accelerated, and exposes an OpenAI-compatible server. It remains a credible lower-level fallback runtime, but Ollama gets the first bake-off because LiveKit documents the integration directly, Windows/RTX support is explicit, model lifecycle is simpler, and it reduces custom JARVIS mechanics.

`llama.cpp` references:

- https://github.com/ggml-org/llama.cpp
- https://github.com/ggml-org/llama.cpp/blob/master/docs/install.md

Decision: **ADOPT Ollama as the first local runtime candidate; keep llama.cpp as fallback technology if Ollama proves unsuitable.**

### First local LLM model candidates — BENCHMARK, NOT YET SELECTED

#### Candidate A — Qwen3.5 4B Q4_K_M

Ollama currently publishes `qwen3.5:4b-q4_K_M` at about 3.4 GB with a 256K advertised context window and text/image input. The family exposes tools/thinking/vision variants. The size is materially more realistic than 7–10 GB alternatives on an 8 GB GPU that must coexist with other JARVIS workloads.

Reference:

- https://ollama.com/library/qwen3.5/tags

#### Candidate B — Gemma 4 E2B instruction QAT

Ollama currently publishes `gemma4:e2b-it-qat` at about 4.3 GB. Standard E2B Q4_K_M is about 7.2 GB and E4B Q4_K_M about 9.6 GB, so those larger variants are poor first choices for an 8 GB coexistence target. The QAT E2B variant is the sensible Gemma comparator.

Reference:

- https://ollama.com/library/gemma4/tags

No model wins by reputation. The owner-machine bake-off must measure English/Hindi/Hinglish behavior, instruction adherence, tool-schema behavior where applicable, TTFT, tokens/sec, RAM/VRAM, and coexistence with accepted local JARVIS workloads.

Decision: **benchmark Qwen3.5 4B Q4_K_M first and Gemma 4 E2B QAT second, sequentially; select neither before evidence.**

### Full-offline STT candidate — Qwen3-ASR 0.6B, later slice only

Qwen3-ASR-0.6B is Apache-2.0 and explicitly supports Hindi among 52 languages/dialects. Its official family supports batch, asynchronous serving, streaming inference, and timestamps.

This makes it a strong future full-offline STT candidate, especially for JARVIS's English/Hindi/Hinglish requirement. It is **not** selected for immediate installation. Its serving/dependency stack should be isolated from the accepted JARVIS Python/Torch environment during evaluation instead of casually changing the production venv.

Reference:

- https://huggingface.co/Qwen/Qwen3-ASR-0.6B

Decision: **RESEARCH/benchmark later in Step 5; no production dependency yet.**

### Full-offline TTS candidate — Kokoro local endpoint, later slice only

LiveKit has an official local Kokoro integration guide. Kokoro-FastAPI exposes an OpenAI-compatible localhost endpoint and the existing LiveKit OpenAI TTS plugin connects to it directly. Kokoro is small and has Hindi voices, although public voice documentation warns that non-English support can be thinner, so JARVIS must owner-benchmark Hindi/Hinglish voice quality before selection.

References:

- https://docs.livekit.io/agents/models/tts/kokoro/
- https://huggingface.co/Codobo/Kokoro-82M/blob/main/VOICES.md

Decision: **first local-TTS candidate for a later full-offline voice slice; no install yet.**

## Technology decisions

| Area | Decision | Reason |
| --- | --- | --- |
| Existing JARVIS provider owner | **KEEP_OURS** | `JARVIS_AI_PROVIDER` remains the one cloud-provider policy/config owner. |
| Cloud native realtime | **KEEP** | Best current primary conversational experience; Step 5 adds resilience, not a forced downgrade. |
| Realtime -> fallback mode switch | **ADAPT LiveKit `AgentSession.update_agent()`** | Public supported handoff mechanism; avoids private realtime fallback internals. |
| Pipeline component retry/fallback | **ADOPT LiveKit fallback adapters where needed** | Mature connection/health/recovery mechanics; keep JARVIS policy above them. |
| First local LLM runtime | **ADOPT Ollama for bake-off** | Official LiveKit integration, native Windows, explicit RTX 5060 Ti support, OpenAI-compatible localhost boundary. |
| llama.cpp | **RETAIN AS ALTERNATIVE** | Mature lower-level OpenAI-compatible server if Ollama fails requirements. |
| First local model | **BAKE OFF Qwen3.5 4B Q4_K_M vs Gemma 4 E2B QAT** | Sizes are plausible on 8 GB; no preselection without owner evidence. |
| Local STT | **DEFER selection to full-offline slice** | Qwen3-ASR 0.6B is promising; dependency/runtime and resources still need measurement. |
| Local TTS | **DEFER selection to full-offline slice** | Kokoro has excellent integration mechanics but Hindi/Hinglish quality needs owner evidence. |
| Private/young realtime fallback adapter as foundation | **REJECT** | JARVIS needs explicit mode/capability/context policy and should build on public handoff APIs. |
| Custom provider router/agent framework | **REJECT** | Would duplicate existing provider/session ownership and violate V1 architecture rules. |

## Proposed Step-5 architecture

### One authoritative resilience owner

Introduce a small JARVIS-owned resilience layer. Names are implementation details, but responsibilities are fixed:

```text
Provider / network / session evidence
             |
             v
      ResiliencePolicy
             |
             v
     RuntimeMode decision
             |
      +------+------+----------------+
      |             |                |
 PRIMARY_CLOUD   DEGRADED       LOCAL_FALLBACK
      |             |                |
      +-------------+----------------+
                    |
                    v
        one VoiceRuntimeController
        one AgentSession lifecycle
        one canonical ConversationSession
        one authority/memory/context truth
```

Suggested observable states:

- `PRIMARY_CLOUD`;
- `DEGRADED_CLOUD`;
- `LOCAL_FALLBACK`;
- `RECOVERING`;
- `INTELLIGENCE_UNAVAILABLE`.

The state machine is deterministic infrastructure. Models may not select their own fallback or grant themselves tools.

### Controlled handoff contract

Cloud-native realtime remains the default active agent.

When the active realtime provider becomes unrecoverable and a validated local fallback is available:

1. freeze any in-flight turn according to partial-output policy;
2. capture only canonical accepted JARVIS history/context needed for continuation;
3. build a new local pipeline agent with the same JARVIS identity but a capability set appropriate to local mode;
4. use public `AgentSession.update_agent()` to hand off;
5. expose the mode transition in privacy-safe runtime observability;
6. never replay a completed/partially delivered answer unless policy explicitly permits it;
7. remain in local fallback until deterministic recovery policy authorizes a return.

The local agent does **not** inherit provider-native hidden history as truth.

### Capability-aware degradation

Fallback cannot pretend parity with the cloud-native realtime agent.

Examples:

- local conversation/reasoning may remain available;
- local wake, vision status, approved deterministic tools, and canonical memory operations may remain available if integration contracts are proven;
- provider-only semantic memory recall may abstain/unavailable when the cloud provider is down;
- future web/current-information capabilities cannot work without network and must say so;
- local fallback must not silently invoke a different cloud provider unless a separately configured cloud-failover policy allows it.

### Preflight evolution

Today, missing active cloud credentials block startup. Step 5 should change this only after a local fallback health contract exists:

```text
cloud primary credential healthy -> normal startup
cloud primary unavailable + local fallback healthy -> start DEGRADED / local-survival capable
cloud primary unavailable + no validated fallback -> fail/idle truthfully according to frozen product policy
```

This prevents a false "offline capable" mode before local inference has actually been accepted.

### Resource arbitration

The 8 GB RTX 5060 Ti is a hard design constraint.

Step 5 must measure rather than assume concurrent residency. Ollama documentation notes that concurrent model loads require available VRAM and that context/parallelism increase memory requirements.

Initial rule:

- benchmark models sequentially;
- use conservative local-model context for fallback rather than advertised maximum context;
- avoid intentionally keeping multiple fallback LLMs loaded;
- measure coexistence with vision, speaker/active-speaker diagnostics, and accepted Qwen retrieval;
- if necessary, local-fallback mode may explicitly suspend nonessential shadow diagnostics or unload derived-memory models, but only after owner evidence identifies a real conflict.

Do not pre-optimise by disabling accepted capabilities before measuring.

## Phased implementation plan

### Step 5.1 — Resilience contracts + simulated handoff

**First implementation slice after owner approval. No local model install required.**

Implement:

- deterministic resilience/runtime-mode domain types;
- provider/session failure observations -> resilience policy transitions;
- explicit partial-output/retry semantics;
- a provider-independent agent-factory/handoff contract around the existing LiveKit session boundary;
- canonical bounded handoff-context construction;
- truthful local-fallback capability descriptor;
- test-only fake fallback agents/providers;
- preflight policy seam without yet declaring local fallback healthy;
- privacy-safe state-transition logs/tests.

Acceptance for 5.1 is automated/simulated. It must prove no duplicated conversation owner, no provider prompt authority, no duplicate answer on simulated mid-turn failure, and deterministic recovery transitions.

### Step 5.2 — Owner-machine local LLM bake-off + bounded local text brain

After 5.1 is accepted:

1. install/evaluate Ollama separately from the JARVIS Python dependency set;
2. benchmark Qwen3.5 4B Q4_K_M and Gemma 4 E2B QAT sequentially on the owner RTX 5060 Ti;
3. freeze multilingual/persona/tool/latency/resource gates before scoring;
4. select a winner only from measured evidence;
5. integrate the winner through LiveKit `openai.LLM.with_ollama`;
6. validate controlled handoff from primary realtime to a local pipeline under simulated provider failure.

A local LLM alone does not yet mean complete network-offline voice, because STT/TTS may still require cloud mechanics depending on the pipeline used.

### Step 5.3 — Full network-offline spoken conversation

Only after 5.2:

- benchmark/select local STT, with Qwen3-ASR-0.6B as the first researched candidate;
- benchmark/select local TTS, with Kokoro-FastAPI as the first integration candidate;
- integrate through LiveKit pipeline contracts;
- test English, Hindi, Hinglish, interruption/turn behavior, resource coexistence, and recovery;
- change preflight so a proven healthy local stack can start JARVIS even when cloud credentials/network are unavailable.

### Step 5.4 — Cloud-to-cloud resilience, only if still valuable

Gemini <-> OpenAI automatic/approved cloud failover is not the first Step-5 problem. If later added, it must reuse the same resilience policy and capability/handoff contracts rather than introducing another router. Provider cost/privacy/tool differences require explicit policy.

## Acceptance scenarios to freeze before implementation

At minimum Step 5 ultimately needs owner-machine scenarios for:

1. normal healthy primary cloud startup;
2. provider unavailable before wake/session activation;
3. network loss before first user response;
4. provider error before any assistant output;
5. provider failure after partial assistant audio/text;
6. local fallback unavailable/failed;
7. successful cloud -> local handoff with canonical conversation continuity;
8. local-mode question requiring a cloud-only capability -> truthful unavailable response;
9. network/provider recovery without duplicate answer or state corruption;
10. repeated wake/sleep cycles after failure/recovery;
11. memory/authority state remains intact across mode changes;
12. resource coexistence on RTX 5060 Ti 8 GB;
13. complete internet-off owner conversation once local STT+LLM+TTS are accepted.

## Architecture invariants

- `ConversationSession` remains canonical conversation truth.
- `ContextAssembler` remains ordinary provider-context owner.
- `MemoryService` remains durable memory mutation owner.
- `JARVIS_AI_PROVIDER` remains the configured primary cloud provider.
- `VoiceRuntimeController` remains outer wake/session lifecycle owner.
- resilience policy decides mechanics/state, not substantive answers.
- a model/provider cannot declare itself healthy, grant tools, or switch authority.
- local fallback does not imply cloud capability parity.
- no Step-6 source routing or Step-7 generic capability runtime is pulled forward unnecessarily.

## Final research decision

**ADAPT the existing LiveKit/JARVIS architecture rather than replacing it.**

The selected direction is:

```text
Gemini/OpenAI native realtime primary
        |
        | deterministic JARVIS resilience policy
        v
public LiveKit AgentSession handoff
        |
        v
validated local pipeline fallback
  STT -> local LLM -> TTS
        |
        v
same JARVIS canonical conversation/authority/memory owners
```

Ollama is the first local LLM runtime candidate because it has direct LiveKit integration and explicit Windows/RTX 5060 Ti support. Qwen3.5 4B Q4_K_M and Gemma 4 E2B QAT are benchmark candidates, not selected production models. Full-offline STT/TTS remains a later Step-5 slice.

**Next gate: owner approval of this architecture, then Step 5.1 implementation only.**
