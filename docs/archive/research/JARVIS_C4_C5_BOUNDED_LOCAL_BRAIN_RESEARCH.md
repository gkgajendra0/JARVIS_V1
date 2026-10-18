# C4 + C5 Deep Research — Bounded Decision Layer and Local Brain

Status: **RESEARCH COMPLETE / BENCHMARK ARCHITECTURE SELECTED / OWNER-MACHINE BENCHMARK NEXT**

Date: 2026-09-29

Parent plans:

- `JARVIS_COST_OPTIMIZATION_MASTER_PLAN.md`
- `JARVIS_COST_OPTIMIZATION_IMPLEMENTATION_PLAN.md`

C3 prerequisite:

- Global Brain Router is implemented and CI accepted.
- Zero-cloud owner acceptance passed on Windows.
- Production machine setting resolves `JARVIS_GLOBAL_BRAIN_ROUTER_MODE=apply`.
- Live production startup proved `brain_router_mode=apply`.

## 1. Research question

C4 and C5 answer two related cost questions:

1. When deterministic C3 policy cannot prove the next path, can a bounded decision model
   cheaply decide whether JARVIS should use local, cheap-cloud, strong-cloud, research,
   retry, or review?
2. Which local model/runtime can safely absorb useful JARVIS reasoning on the owner's
   Windows RTX 5060 Ti 8 GB machine while coexisting with the live voice/vision stack?

The target is not "use local AI everywhere." The target is:

> Use deterministic policy first, then the cheapest **admitted** bounded/local
> intelligence path, then cloud escalation when evidence says local is insufficient.

## 2. Existing JARVIS substrate we should reuse

The repository already has the important contracts:

- C3 `GlobalBrainRouteFacts` and deterministic route provenance;
- Phase-4 `ModelTarget` registry with locality, capabilities, roles, context limits,
  benchmark status and cost profile;
- deterministic eligibility for privacy/locality/capability/benchmark/health;
- target health, cooldown and bounded fallback;
- structured provider invocation;
- durable routing decisions/attempts/outcomes;
- C1 usage, latency and provider/model cost telemetry.

Therefore C4/C5 must **populate** the existing routing substrate. They must not add a
second model router or a local-agent framework beside it.

## 3. C4 finding — Jev is a benchmark candidate, not an automatic dependency

Fresh research on 2026-09-29 confirms TypeSafe AI released Jev as a managed
"System One" decision model on 2026-09-15.

Official TypeSafe material describes:

- state in;
- typed Choice / Noul / Score questions out;
- probabilities/confidence with the typed decisions;
- no free-form text generation;
- model price currently published as USD 0.042 per million input tokens;
- output tokens free;
- company-reported end-to-end latency roughly 70-500 ms;
- early-access service.

Primary sources:

- https://typesafe.ai/blog/introducing-system-one-models-and-jev
- https://typesafe.ai/
- https://api.typesafe.ai/docs

This shape is a strong match for C4 because JARVIS needs bounded branch decisions,
not another prose-producing agent.

### 3.1 Important Jev limitations

TypeSafe's own current limitation guidance says Jev 1.13 is weaker on:

- exact numeric precision;
- counting;
- date/time comparisons;
- multiple levels of indirection;
- large state containing irrelevant detail.

Therefore JARVIS must never ask a bounded decision model to do deterministic work that
ordinary code can do.

Examples that stay in code:

- token/context arithmetic;
- budget arithmetic;
- date/expiry comparisons;
- Authority checks;
- privacy/locality eligibility;
- model health/cooldown;
- whether a deterministic C3 resolver exactly matches;
- capability admission;
- owner permissions.

The bounded layer may only judge fuzzy semantic facts after hard policy has already
constrained the legal choices.

### 3.2 Independent routing evidence is mixed

A fresh public Jev routing experiment using RouterArena/LLMRouterBench reports that its
retrieval-assisted router reduced cost while preserving quality, but the author's own
ablation found the retrieval evidence explained the measured gain and Jev's difficulty
signal added no measurable benefit in that setup.

Reference:

- https://github.com/TokenTrim/jev-routing-experiment

This is useful negative evidence: JARVIS should not adopt Jev because it is fashionable
or cheap. It must beat simpler JARVIS-owned alternatives on JARVIS cases.

## 4. C4 selected architecture

C4 occupies only the reserved bounded-decision slot created by C3:

```text
trusted JARVIS state
    -> hard deterministic policy / C3 resolver
    -> if exact match: deterministic BrainDecision
    -> otherwise optional bounded-decision evaluation
    -> existing ModelRouter for admitted local/cloud target
    -> governed executor / Authority / verification unchanged
```

The bounded layer:

- does not execute a tool;
- does not grant Authority;
- cannot add a model/capability to eligibility;
- cannot weaken privacy/locality;
- cannot override a deterministic C3 match;
- may choose only from a list JARVIS supplies;
- must expose confidence/probabilities when the candidate supports them;
- must abstain below calibrated thresholds;
- must be disableable without changing Phase-4/C3 behavior.

## 5. C4 benchmark questions

Build one JARVIS-specific benchmark rather than a generic classification benchmark.

Decision families:

1. **reasoning tier**
   - local_sufficient
   - cloud_standard
   - cloud_strong

2. **research need**
   - no_external_research
   - external_research_needed
   - insufficient_state

3. **retry/escalation**
   - retry_same_tier
   - escalate_tier
   - request_owner_review

4. **task class**
   - classification/extraction
   - summarization
   - bounded planning
   - code generation
   - debugging
   - architecture/research synthesis

5. **quality risk**
   - routine
   - material
   - high

The benchmark must compare:

- deterministic/code-only baseline;
- Jev;
- small local model;
- existing strong cloud reasoner as a reference, not as automatic ground truth.

## 6. C4 scoring

Accuracy alone is insufficient because routing errors are asymmetric.

Record:

- exact decision accuracy;
- confusion matrix;
- **unsafe downgrade rate**: chose a cheaper/weaker path when the case required a
  stronger path;
- conservative over-escalation rate;
- coverage at each confidence threshold;
- Brier score / calibration where probabilities exist;
- p50/p95 latency;
- input tokens;
- monetary cost;
- downstream cloud calls avoided;
- fallback/outage behavior.

Admission should optimize for very low unsafe-downgrade rate, not maximum automation
coverage.

Thresholds are intentionally **not hard-coded by research**. They must be calibrated
from the owner's benchmark results.

## 7. C5 runtime research

### 7.1 Selected first runtime: Ollama

Ollama is the first benchmark runtime because current official documentation provides:

- native Windows support;
- NVIDIA GPU support;
- explicit RTX 50-series / RTX 5060 Ti support;
- localhost HTTP API;
- structured outputs constrained by JSON schema;
- model/VRAM visibility through `ollama ps`;
- configurable context and K/V cache behavior.

Sources:

- https://github.com/ollama/ollama/blob/main/docs/windows.mdx
- https://github.com/ollama/ollama/blob/main/docs/gpu.mdx
- https://ollama.com/blog/structured-outputs
- https://github.com/ollama/ollama/blob/main/docs/faq.mdx
- https://github.com/ollama/ollama/blob/main/docs/context-length.mdx

This is an implementation choice for the first benchmark, not a permanent model-runtime
lock-in. The JARVIS adapter should remain a local structured-output interface so
llama.cpp or another runtime can replace Ollama later.

### 7.2 llama.cpp remains the lower-level fallback

Current llama.cpp supports JSON-schema/grammar constrained generation and an
OpenAI-compatible server, so it remains a good future lower-level option.

However, fresh issue history also shows schema-enforcement compatibility edge cases.
JARVIS would therefore continue to validate every returned object with Pydantic even
when the local runtime claims constrained output.

References:

- https://github.com/ggml-org/llama.cpp/blob/master/docs/development/parsing.md
- https://github.com/ggml-org/llama.cpp/blob/master/scripts/server-test-structured.py

## 8. C5 hardware constraint — benchmark the real production environment

The owner machine has an RTX 5060 Ti with 8 GB VRAM and 16 GB system RAM.

C5 admission must test coexistence with live JARVIS because production already uses GPU
resources for vision/active-speaker processing. A model that works only when JARVIS is
stopped is not automatically useful as JARVIS's normal local brain.

Ollama currently defaults systems below 24 GiB VRAM to a 4K context because context
memory scales quickly. Its docs also note:

- larger context increases memory;
- parallel requests multiply context allocation;
- Flash Attention can reduce memory;
- q8 K/V cache uses roughly half the memory of f16 with small quality loss;
- q4 K/V uses roughly one quarter with greater quality risk.

For C5 v1:

- benchmark one local request at a time;
- start at 4K context;
- optionally test 8K only after full GPU residency succeeds;
- do not use model-advertised 128K/256K context as a production target on 8 GB VRAM;
- do not accept CPU offload as "good local performance" unless latency evidence later
  justifies a deliberate hybrid tier.

## 9. C5 model shortlist

### Tier A — benchmark first

#### Qwen 3.5 4B Q4_K_M

Current Ollama package:

- model: `qwen3.5:4b`
- approximately 4.66B parameters;
- Q4_K_M;
- package about 3.4 GB;
- tool/thinking support advertised;
- model family advertises 256K context, but C5 will intentionally start at 4K.

Why first:

- enough headroom relative to 8 GB VRAM for JARVIS coexistence;
- modern general reasoning/agent orientation;
- structured-output path available through Ollama.

Source:

- https://ollama.com/library/qwen3.5:4b

#### Phi-4-mini 3.8B Q4_K_M

Current Ollama package:

- model: `phi4-mini`
- approximately 3.84B parameters;
- Q4_K_M;
- package about 2.5 GB;
- 128K model context advertised;
- function/tool calling support advertised.

Why first:

- smaller VRAM footprint;
- useful comparator for bounded classification/routing and routine reasoning;
- likely stronger coexistence margin for the live vision stack.

Source:

- https://ollama.com/library/phi4-mini

### Tier B — stretch candidates only after Tier A

#### Qwen 3.5 9B

Current Ollama Q4-class package is about 6.6 GB.

This is too close to an 8 GB card to assume live coexistence with JARVIS, K/V cache,
CUDA graphs and vision workloads. Benchmark only if Tier A quality is insufficient.

Source:

- https://ollama.com/library/qwen3.5/tags

#### Ministral 3 8B

Current Ollama package is about 6.0 GB and is explicitly positioned for edge
deployment. It is another useful 8B-class stretch comparator if needed.

Source:

- https://ollama.com/library/ministral-3:8b

### Comparators, not first production targets

- Gemma 3 4B: useful general/multimodal comparator, about 3.3 GB in Ollama.
- DeepSeek-R1 8B: useful reasoning comparator, about 5.2 GB, but reasoning latency and
  production GPU coexistence make it a lower-priority first target for frequent JARVIS
  routing.

## 10. C5 benchmark task classes

Do not judge a local model by one aggregate score.

Corpus categories:

1. bounded route/classification;
2. structured extraction;
3. concise summarization;
4. next Work action from canonical state;
5. simple code transformation;
6. bounded debugging diagnosis;
7. research-query formulation;
8. architecture/complex engineering reasoning.

Each case stores:

- case id/version;
- sanitized input state;
- allowed answer/action set;
- expected answer or accepted answer set;
- severity if wrong;
- maximum acceptable latency;
- whether local admission is allowed for the class.

No API keys, owner secrets, hidden prompts, or sensitive Work payloads go into the
committed corpus.

## 11. C5 owner-machine measurements

For each candidate/configuration record:

- model digest/version;
- quantization;
- context allocation;
- whether JARVIS voice/vision is running;
- `nvidia-smi` baseline and loaded VRAM;
- `ollama ps` processor split;
- CPU/RAM;
- load time;
- p50/p95 first-token/total latency where observable;
- prompt/eval token counts;
- structured-output validity;
- exact task score;
- unsafe errors;
- GPU/CPU offload state;
- runtime failure/recovery behavior.

Production admission requires repeatable full-GPU or deliberately accepted hybrid
execution without destabilizing voice/vision.

## 12. Local adapter design

Do not expose Ollama as a new high-level agent.

Add one local structured-output adapter behind the existing `ModelInvoker` contract.

Responsibilities:

- localhost-only endpoint by default;
- target/model identity check;
- JSON schema supplied to local runtime;
- Pydantic validation remains authoritative;
- provider-neutral usage/latency telemetry;
- report prompt/eval token counts when the runtime exposes them;
- explicit local locality;
- no cloud credentials;
- local API cost is known zero, while compute/latency remains observable;
- runtime unavailable -> target health/fallback through existing Phase-4 machinery.

The adapter should not own model routing, retry policy, Authority, or tool execution.

## 13. Model admission policy

A local model is admitted **per capability/task class**, never globally.

Examples:

- a 4B model may be ACCEPTED for classification, extraction and summarization;
- the same model may be REJECTED for architecture or difficult debugging;
- an 8B model may be accepted only when enough GPU headroom exists;
- a local target with failing/unknown benchmark status stays ineligible automatically.

This reuses `ModelTarget.benchmark_status` instead of inventing another gate.

## 14. Recommended execution sequence

### C4/C5.1 — committed benchmark specification

Create:

- versioned case schema;
- sanitized benchmark corpus;
- deterministic/code baseline;
- scorer with asymmetric unsafe-downgrade metrics;
- local runtime probe;
- optional Jev runner disabled unless a credential is explicitly provided.

### C4/C5.2 — owner-machine local runtime preflight

Check:

- Ollama installed/version;
- RTX 5060 Ti visible;
- current JARVIS VRAM baseline;
- localhost endpoint;
- no cloud Ollama features required.

No model purchase/API spend.

### C4/C5.3 — Tier A local benchmark

Pull and test:

1. `phi4-mini`
2. `qwen3.5:4b`

Benchmark 4K context, one request at a time, both:

- with JARVIS stopped for isolated ceiling;
- with production JARVIS running for real coexistence.

### C4/C5.4 — decide whether stretch model is justified

Only if Tier A quality is below admission thresholds, test:

- `qwen3.5:9b` first;
- optionally `ministral-3:8b`.

### C4/C5.5 — Jev comparison

Run the exact same bounded-decision subset through Jev only after:

- corpus/scorer is frozen;
- current API access/pricing is rechecked;
- a Jev credential is explicitly configured;
- a tiny benchmark spend is approved.

Jev is adopted only if its quality/calibration/cost improves expected whole-mission
economics relative to deterministic + local.

### C4/C5.6 — integrate admitted local target(s)

After benchmark evidence:

- add local adapter;
- register accepted `ModelTarget`;
- use `ModelLocality.LOCAL`;
- attach only proven capabilities;
- set benchmark status from accepted evidence;
- shadow route before production apply where semantic routing is involved;
- preserve cloud escalation.

## 15. Acceptance criteria

C4 complete when:

- JARVIS-specific decision corpus exists;
- deterministic/local/Jev candidates can be compared with one scorer;
- thresholds are calibrated from evidence;
- Jev is either admitted for explicit bounded decisions or explicitly deferred;
- no Authority/privacy/locality rule can be weakened by the bounded layer.

C5 complete when:

- at least one local target passes an owner-machine benchmark;
- local target is registered with task-specific capabilities;
- local invocation telemetry is durable;
- structured-output failures fail closed;
- cloud fallback still works;
- production JARVIS voice/vision remains acceptable;
- owner-machine restart/replay acceptance passes.

## 16. Current recommendation

Proceed without buying any cloud credits.

The next engineering work should create the benchmark corpus/scorer and owner-machine
local-runtime probe. Then test Phi-4-mini and Qwen 3.5 4B locally.

Do **not** integrate Jev or a 9B local model before those benchmark results exist.
