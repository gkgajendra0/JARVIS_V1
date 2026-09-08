# Step 4 — Phase 4.4 Owner-PC Production Acceptance

Date: 2026-09-05

## Result

**PASS.**

Phase 4.4 structured extraction and session-local candidate quarantine passed the real owner-PC production voice path with Gemini as the one active cloud-AI provider and `gemini-3.5-flash-lite` as the selected extraction model.

Implicit durable admission remained OFF throughout acceptance.

## Accepted production configuration

- active cloud provider: `gemini`;
- realtime conversation: existing Gemini Live production path;
- extraction model: `gemini-3.5-flash-lite`;
- `JARVIS_MEMORY_ENABLED=true`;
- `JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED=true` for the acceptance run;
- candidate quarantine: session/process-local only;
- durable candidate admission: disabled.

## Hardware/runtime preflight

Initial startup correctly failed closed when Windows did not enumerate the configured Pocket3 WASAPI input. No fallback to a random microphone or Voicemeeter index was introduced. After the Pocket3 was restored in Webcam mode, production preflight passed with:

- wake model available;
- active Gemini credential available;
- Pocket3 input resolved by stable WASAPI identity at 48 kHz;
- NVIDIA `24'TV` output resolved at 48 kHz;
- LR-ASD dependency present;
- vision + speaker-shadow dependency intact.

JARVIS then started normally with integrated vision, wake detection, CAM++ shadow, LR-ASD shadow, Gemini realtime conversation, and Phase-4.4 extraction configured simultaneously.

## Owner acceptance sequence

### 1. Implicit fact — quarantine only

Owner said an ordinary declarative fact equivalent to:

`My favorite wild bird is falcon.`

Final accepted runtime behavior:

- realtime JARVIS responded conversationally;
- no `remember_memory` mutation tool was called;
- no memory-confirmation question was asked for the ordinary fact;
- Gemini Interactions extraction call returned HTTP 200;
- Phase-4.4 logged `outcome=quarantined`;
- reason was `structurally_eligible_candidate`;
- quarantine was `session_local`;
- `durable_admission=False`.

This proves the implicit statement was recognized as candidate evidence without gaining durable-memory authority.

### 2. Session close — physical quarantine disposal

On normal return to local wake detection, Phase 4.4 logged:

- `disposed_candidates=1`;
- `cancelled_tasks=0`;
- `quarantine_disposed=True`;
- `durable_admission=False`.

This proves the candidate was physically discarded with the session and was not retained as a hidden durable candidate table.

### 3. Fresh session — no durable resurrection

Owner then woke JARVIS again and explicitly asked what it remembered about the favorite wild bird.

Accepted behavior:

- the Phase-4.4 extractor skipped the turn because it was an explicit Phase-4.3 memory-control query;
- reason: `phase_4_3_explicit_memory_control`;
- exact canonical memory lookup returned no current memory for `favorite_wild_bird`;
- JARVIS answered that it had no record of the fact;
- it did **not** recall `falcon` from durable memory.

This is the decisive proof that quarantine evidence did not become SQLCipher canonical memory and did not resurrect across sessions.

The realtime assistant subsequently offered to remember the fact. This occurred only after an explicit memory-inspection query had already returned a miss; it did not invoke a mutation or create durable memory and is not an implicit-candidate leakage. It is therefore non-blocking for Phase 4.4.

## Routing hardening discovered during acceptance

Two model-facing routing issues were found and corrected research-first without weakening deterministic authorization:

1. An early implicit-fact run caused Gemini realtime to attempt `remember_memory`. The deterministic Phase-4.3 guard rejected it because the user had not explicitly authorized a remember operation. The model-facing system instruction/tool description was then tightened with explicit positive/negative examples.
2. A subsequent run no longer called the tool but asked whether the owner wanted the fact remembered. The conversational instruction was tightened so ordinary implicit facts are handled naturally and candidate extraction remains invisible.

Final run passed both routing conditions: no mutation tool call and no memory-confirmation question for the ordinary fact.

The deterministic memory authorization/grounding/database implementation was not loosened or bypassed by either fix.

## Step-3 regression observations

During the accepted run:

- Pocket3 remained the one physical conversation microphone owner;
- wake detection worked and returned after session close;
- Gemini realtime conversation worked;
- TV output remained the selected production output;
- Vision remained active;
- CAM++ remained diagnostic/shadow only;
- LR-ASD remained diagnostic/shadow only;
- prototype admission remained disabled;
- no authority behavior changed.

Non-blocking existing runtime messages such as AudioMixer timeouts and Gemini 3.1 limited mid-session update support did not prevent accepted conversation or Phase-4.4 behavior.

## Acceptance conclusion

Phase 4.4 has proved the intended boundary end to end:

```text
accepted canonical USER turn
 -> deterministic source / explicit-control / secret gates
 -> Gemini 3.5 Flash-Lite structured proposal
 -> deterministic JARVIS proposal policy
 -> session-local quarantine
 -> physical disposal on session close
 -> NO MemoryService durable mutation
 -> NO SQLCipher canonical assertion
 -> NO cross-session resurrection
```

**Owner-PC Phase-4.4 acceptance: PASS.**

No further Phase-4.4 owner repetition is required.
