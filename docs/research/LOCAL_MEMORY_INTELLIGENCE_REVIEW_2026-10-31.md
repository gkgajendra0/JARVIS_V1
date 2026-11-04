# Local intelligence for Jarvis memory

**DEFERRED alternative; no local model or fine-tuning selected for initial delivery.** The owner chose [Gemini with existing local memory](../PROJECT_CONVERSATION_MEMORY.md). Preserve this research for a later measured interpretation/cost limitation; it is not the active build plan.

Date: 2026-10-31 (owner timezone). Status: primary-source/model-card research; no model installed, inference benchmark, fine-tuning, provider switch or owner-data migration performed.

## Conclusion

A small pretrained local LLM can interpret memory requests, choose project/search tools, and propose source-grounded updates. This can replace some cloud memory-specific reasoning. It is not a replacement for a durable archive, retrieval index or the application-controlled context-before-response boundary. Do not train a foundation model from scratch or train nightly merely to memorize changing personal facts.

The most directly relevant discovery is Dria's existing `mem-agent` model and `firstbatchxyz/mem-agent-mcp` scaffold. It has already been trained for memory retrieval, updates and clarification. Qualify it as a bounded local memory specialist against a general 4B instruction baseline before considering any Jarvis-specific fine-tuning. Neither candidate is a verified improvement over current Gemini or prior Jarvis experiments.

## Candidates verified from primary sources

### Dria mem-agent: an already trained memory specialist

- Weights/model card: https://huggingface.co/driaforall/mem-agent
- First-party integration: https://github.com/firstbatchxyz/mem-agent-mcp
- The model card says it is based on Qwen3-4B-Thinking-2507 and trained with GSPO over retrieval, updates, clarification and optional filtering.
- Its learned scaffold uses `user.md`, linked entity Markdown files and file/directory tools. It emits thinking, Python tool code, and a final reply, with tool results returned to the agent loop. This is an actual learned memory-management policy, not a vector database advertised as intelligent.
- The publisher recommends exposing it through MCP to a larger model. This matches a local memory specialist behind Jarvis/Gemini conceptually.
- Its own md-memory-bench reports 0.75 overall and approximately 0.36 clarification performance. These are author-reported scaffold-specific results, not evidence of superior general intelligence, reliable Hindi/Hinglish, complete project isolation or Jarvis speech quality. Do not use a comparison to older Gemini versions as a current model ranking.
- README supports macOS/Metal and Linux/GPU/vLLM. Native Windows is not established. Quantized variants exist, but MLX is an Apple path; NVIDIA needs a compatible CUDA/GGUF serving route and parser verification. Some scaffold defaults can use remote OpenAI/OpenRouter-compatible services: selecting it does not automatically guarantee local-only inference.
- It assumes Markdown memory and executable tool code. Do not put unrestricted generated Python or plaintext owner memory into Jarvis. A scoped bridge to canonical encrypted reads and proposed writes is required; changing the trained tool surface can change its accuracy and requires qualification.

### Qwen general instruction baseline

- https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- https://huggingface.co/Qwen/Qwen3.5-4B
- Qwen3-4B-Instruct-2507 is a 4B non-thinking instruction model with documented tool use and support in local serving applications. This is a practical short-output routing/extraction baseline; the non-thinking format simplifies latency control.
- Qwen3.5-4B adds a newer multimodal/hybrid architecture and broad multilingual coverage. Its card documents tool use and disabling default thinking through the serving parameters. Runtime/version compatibility must be checked; advertised maximum context is not an appropriate default for a small consumer GPU.
- Both are candidates, not established winners for Jarvis memory decisions. Prior Qwen/classifier experiments remain valid within their recorded tasks and are not erased by choosing a newer checkpoint.

### FunctionGemma: a small future fine-tuning target

- https://ai.google.dev/gemma/docs/functiongemma
- https://huggingface.co/google/functiongemma-270m-it
- Google describes a 270M model specialized for function calling and as a base for further task-specific training. It is directly relevant to a fixed memory API such as select project, search, read and propose update.
- It is not a general replacement for Gemini's answering. Its small size does not establish free-form memory extraction or Hindi/Hinglish accuracy. Hugging Face metadata reports manual-gated access, and an anonymous README fetch returned 401; the public Google overview was read instead. No gate was bypassed.

### Gemma 4 E2B: additional small-model alternative

- https://huggingface.co/google/gemma-4-E2B-it
- Its current card documents function calling, local/edge deployment and multilingual support. The E2B name is not the full resident weight count: the card lists 2.3B effective and 5.1B including embeddings. Do not calculate VRAM as a literal 2B model or assume every local runtime supports the checkpoint identically.
- Keep as an alternative if the first bounded local qualification reveals a concrete model-quality/compatibility gap; avoid an endless model sweep.

## Local execution and machine fit

User-reported machine: RTX 5060 Ti and 16 GB system RAM. The exact VRAM variant is unknown here. NVIDIA lists both 8 GB and 16 GB variants:
https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5060-family/

Quantized roughly 4B-class inference with short, bounded context is a plausible starting point, not a measured fit/latency guarantee. Weight format, KV cache, runtime buffers, display/other workloads and available system RAM all matter. Do not configure a 128K/256K context merely because a model advertises it. Record actual `nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv` output from the owner machine before choosing the profile. Larger VRAM improves room for adapters and sequence/batch lengths; do not promise a training configuration based only on GPU product name.

Ollama and llama.cpp already implement local tool-serving machinery; Ollama also supports JSON-schema constrained outputs:
- https://docs.ollama.com/capabilities/tool-calling
- https://docs.ollama.com/capabilities/structured-outputs
- https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md

Schema-constrained output only proves format, not correct topic choice, factual support or permission. Dria's custom Python-tag scaffold is not automatically equivalent to standard function calling.

## Training choices

1. Pretrained model plus existing memory tools: first choice, no training required.
2. LoRA/QLoRA fine-tuning: possible if measured errors are about routing, query formulation or update proposals and a curated labelled dataset exists. Train the desired behavior, exact source use, corrections, negatives and ambiguity handling. Hold out conversations/projects and Hindi/English variants. Do not train on evaluation answers.
3. Full continued pretraining/from-scratch personal LLM: not justified for the small memory-controller task. The cost and data requirements do not address the current missing archive/voice boundary.

PEFT documents training adapters on 4-bit quantized bases with QLoRA. Unsloth supplies existing fine-tuning/export tooling. Actual memory use depends on architecture, sequence length, optimizer, batch and checkpointing; no fixed training-VRAM claim is made here.
- https://huggingface.co/docs/peft/developer_guides/quantization
- https://github.com/unslothai/unsloth

Changing facts such as departure dates, permits and decisions must remain in the database, not solely in model weights. Weight updates do not provide source-level correction, deletion, provenance or exact current-state reads. Daily raw transcripts are not automatically a high-quality supervised dataset.

## Placement in Jarvis

Accepted transcript -> automatic canonical archive -> bounded local memory-controller request -> source/project validated local retrieval -> relevant context -> existing Gemini answer. Local extraction can propose structured memory updates asynchronously; record original turns regardless of extraction success. Current canonical authority remains the write/read owner. A model's chosen tool is not permission.

Use the local specialist for project selection proposals, search query construction, candidate fact extraction and optional summaries. Reuse existing retrieval for actual matching and storage for durability. Keep task execution permission and critical correction/forget semantics deterministic and source-bound. This adds local interpretation; it does not resolve the delayed-realtime-transcript race by itself.

Cost benefit must be measured: a local memory controller can avoid cloud extraction/search-planning calls and potentially reduce prompt size. It does not remove Gemini Live audio/model charges. If the current topic proposal already arrives inside the existing answer turn, moving that proposal locally may save less than expected. No inference is literally free of compute/electricity, but local execution need not incur per-token provider fees when configured without remote fallback.

## Qualification boundary

Reuse synthetic Jarvis failure cases for a narrowly new local-model test: named/unnamed Nepal continuation, project switch, two similar trips, current corrections versus old facts, unsupported ownership inference, questions/negation, repeated turns, unknown facts and Hindi/Hinglish/ASR ambiguity. Compare source-supported decisions, clarification, invalid writes, query results, latency and end-to-end provider usage. Preserve original source capture and require zero cross-project or unauthorized release in the tested cases.

Start without fine-tuning. Consider a small adapter only after the baseline exhibits repeated, labelled, task-specific errors. Do not extrapolate publisher benchmarks into a promised Jarvis improvement or train overnight as an automatic first step.
