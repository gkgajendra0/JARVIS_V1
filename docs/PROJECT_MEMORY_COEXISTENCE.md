# Project memory with Gemini paid fallback and personal context / learning APPLY

This document describes how B2 (Gemini fallback and transport handoff) and B3
(personal context and learning APPLY) were resolved. It builds on PR #308. The
owner's installed configuration is the target: Gemini free by default, paid
fallback ON with automatic admission (`JARVIS_GEMINI_PAID_BUDGET_ENABLED=false`),
and personal context and learning in APPLY.

## What actually broke (from the code, not from assumptions)

### B2: provider handoff

`GeminiLiveHandoff._switch` replaces the realtime model mid-wake in three
cases: a quota failure moving to the paid key, free recovery from paid back to
free, and fresh-session recovery after a 1011/1008 transport fault. It builds
the new `_TransportAgent` from `bridge.project_accepted_context()`, which
holds the canonical USER/ASSISTANT turns, plus tool receipts.

1. **No blocking tools on the new model.** `_create_realtime_model` makes a
   new plugin `RealtimeModel` whose Gemini 3.8 default is NON_BLOCKING. Project
   memory requires BLOCKING (`require_blocking_realtime_tools`).
2. **The first model could not be configured either.** With fallback ON,
   every model is wrapped in `GuardedGeminiRealtimeModel`. That wrapper had no
   model-level `update_options`, so `configure_realtime_model(session.llm)`
   raised `TypeError` at the first wake. This was a latent crash, hidden only
   because activation refused fallback.
3. **The project context is lost and the gate stays wrong.** The session
   preload, `prepare_project_turn` results, searches and repair deliveries are
   not canonical turns, so the new model never receives them. The project
   response gate still records them as given (`_delivered_ids`, fast-path
   state), so it would let answers through that were made *without* project
   context, and it would not resend rows the new model never saw.

Duplicate tool runs and duplicate writes were already prevented: the handoff
refuses while a tool is pending, and turns are saved once from canonical
accepted turns, which a handoff never re-emits. Tests confirm both.

### B3: personal context / learning APPLY

The two response gates were already stacked: `ProjectAudioGate` sits outside
`PersonalContextAudioOutput`. Two interactions remained wrong:

1. **A withheld response retired the personal session.** When the project
   gate withholds a response (the model answered before getting project
   context), it interrupts that speech. The personal session saw an
   interrupted, or finished-without-audio, response for a *protected* answer,
   so it closed and retired the wake. The project repair that should answer
   the same utterance was then never heard.
2. **Personal facts leaked across an authorization boundary.** Facts released
   under a personal-context permit are question-bound: the session retires
   after the answer so they do not stay in the model. Saving that answer as
   project history would bring the facts back in later wakes (preload and
   search) with no permit. It would also outlive a correction or a forget of
   the canonical fact.

## Alternatives considered

**B2**

| Option | Why not |
| --- | --- |
| Keep refusing fallback (the old blocker) | Loses a working production capability. |
| Re-run the preload on the new model and reset the gate | Rows delivered by tool or search during the wake are lost. The in-flight answer would be withheld and repaired (an extra generation and latency), and "continue the request" would no longer be a single generation. |
| Put the project context into canonical turns | Pollutes the canonical conversation, transcripts and project history with system text. The bridge would have to tell such "turns" apart forever. |
| Gemini session resumption across the switch | Resumption handles are bound to the client and session. The handoff deliberately opens a fresh session on a different key, and reusing a handle collides with Google's old client (see `_recover_fresh_session`). |
| **Chosen: re-give exactly what this session was given** | See below. No extra model calls, the gate stays truthful, and it is bounded. |

**B3**

| Option | Why not |
| --- | --- |
| Keep refusing APPLY | Loses personal intelligence, a core goal. |
| Replace both gates with one merged gate | Rewrites two working, separately tested components without need. Composition already works except for two interactions. |
| Save personal answers and purge them when canonical memory changes | Couples two stores. It still re-releases question-bound facts without a permit between the save and the purge. |
| **Chosen: fix the two interactions** | See below. |

## The design

**B2**
- `GeminiLiveHandoff.add_model_configurer(fn)`: every new model is configured
  before it opens a session. Project memory registers
  `configure_realtime_model`, which sets BLOCKING tools. A model that cannot be
  configured is retired and the switch fails closed (`handoff_unavailable`);
  it never runs unconfigured.
- `GuardedGeminiRealtimeModel.update_options` forwards to the wrapped model.
  `ControlledGeminiLiveModel` (the budgeted paid path) accepts only BLOCKING,
  which its sessions already declare.
- `GeminiLiveHandoff.add_context_provider(provide, observe)`: inert items are
  appended to the replayed context, and the provider is told when a switch
  succeeds. `VoiceProjectTurns` keeps a session-scoped ledger: each history row
  given to the model (by preload, tool, repair or search) and the exact line it
  was given as. `handoff_context_items()` returns that ledger as one completed
  exchange (a labelled memory message plus a Jarvis "Noted."), the same form
  as the preload. That form keeps generate_reply from treating it as an open
  request.
  - **Bounded:** at most 6,000 characters, newest rows first. Rows left out are
    also dropped from `_delivered_ids`, so the gate resends them if needed: the
    gate never believes the model holds something it does not.
  - **Forgotten rows** are removed from the ledger at forget time and are never
    re-given.
  - **Deterministic item ids** (a content hash) mean a transport that replays
    the context again presents items the bridge already knows.

**B3**
- `personal_speech_finished(personal, project_turns, handle)`: a response the
  project gate withheld is ignored by the personal session. It is neither
  finished nor barged in; the repair answers under the same permit. A real
  barge-in, or a heard answer, retires as before.
- `PersonalContextSession.add_release_observer(fn)`: called whenever owner
  facts are released, or a canonical change is committed, for the current
  utterance. `VoiceProjectTurns.observe_personal_release` marks that
  utterance; its reply is not saved to project history
  (`personal_replies_not_saved`). The owner's question is saved as usual, and
  canonical memory stays the only store of personal facts. Corrections and
  forgetting therefore have one place to act, and the existing canonical →
  history forget coupling covers what the owner said.

`project_voice_production.activation_blockers` no longer refuses fallback or
APPLY. Memory enabled and the Gemini provider are still required.

## Cost

- **No additional model calls.**
- **Per handoff:** at most 6,000 characters of context, sent once with the new
  session's setup. Handoffs are rare (quota, recovery).
- **Per protected personal answer:** the personal session retires the wake as
  before, and the follow-up session preloads once. That is a local archive read
  (about 50 ms) and about 0.8 kB of context.
- **Gate checks:** O(1) membership tests per response.

## Verified by

- `tests/learning/test_project_memory_coexistence.py`. It uses the real
  `GeminiLiveHandoff`, LiveKit `AgentSession` and bridge, the real archive and
  the real `PersonalContextSession`; only the provider transport is fake.
- The updated activation tests in `test_project_voice_production.py` and
  `test_project_memory_release_gate.py`.
- The existing `tests/gemini_fallback`, `tests/gemini_live` and
  `tests/gemini_operational` suites, unchanged.

## Not verifiable without the live provider

- A real Gemini quota event (429) during a wake, and a real 1011 recovery.
- How Gemini answers from the restored context.
- That BLOCKING tools on the paid model behave like on the free model.
- Personal-answer retirement timing with real audio.

These are covered by the first production activation smoke test.
