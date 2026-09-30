# Gemini Live 3.8 Migration — 2026-09-30

## Decision

Production realtime voice moves from `gemini-3.1-flash-live-preview` to
`gemini-3.8-live`.

The change is a provider-model migration, not a rollback of JARVIS voice
architecture.

## Evidence

- Gemini 3.1 Live had been used successfully by JARVIS before this incident,
  including owner-machine conversations on 2026-09-08 and earlier on
  2026-09-30.
- Later on 2026-09-30, fresh owner-machine sessions still detected the local
  wake word but the realtime conversation produced no canonical USER turn.
- Failing sessions also produced Gemini Live WebSocket `1011 Internal error`
  events.
- Restoring scripted lifecycle speech did not restore conversation input, so
  the non-conversation lifecycle session design was ruled out.
- On unchanged `main`, with the same microphone, LiveKit 1.8.3 stack, API key,
  audio router and conversation code, overriding only
  `JARVIS_GEMINI_REALTIME_MODEL=gemini-3.8-live` restored:
  - realtime startup speech;
  - wake detection;
  - `listening -> speaking` user activity;
  - final USER transcription;
  - assistant response;
  - semantic standby acknowledgement.

## Why accepted Self-Repair did not autonomously fix this incident

This incident was not a crash/hang failure covered by the accepted automatic R2
production repair policies. The process stayed alive, the local wake path remained
healthy, and the provider could still establish realtime sessions. The failure was
semantic/behavioral: accepted USER turns disappeared under the legacy provider target,
then the new model exposed a different proactive-audio wake/turn contract.

The accepted autonomous-engineering stack already contains the governed path needed
*after* such a weakness becomes canonical evidence, but automatic weakness discovery is
a later boundary:

- automatic production Self-Repair is currently bounded R2 crash/hang recovery;
- Phase 6 can investigate an unknown canonical incident and prepare source repair;
- Phase 10 learning is advisory and learns only from verified canonical outcomes;
- Phase 10A production autonomy remains SHADOW;
- Phase 11 autonomous capability-gap/weakness detection is not yet implemented;
- Phase 14 governed self-evolution is not yet implemented.

Recoverable realtime provider errors are now also mirrored into canonical provider
health as DEGRADED evidence before recovery, so a Gemini 1011/server-side failure can
reach Self-Awareness/Incidents even when LiveKit keeps the session alive.

This migration candidate now closes the first deterministic semantic-observation gap:
three consecutive wake-triggered realtime sessions that end without a committed owner
turn degrade `runtime.voice` through Self-Awareness. A subsequent committed owner turn
resets the streak and publishes recovery when degradation had been reached. A single
wake with no follow-up remains normal and does not create an incident.

Broader Phase-11 weakness detection is still required for additional behavioral SLOs
such as sustained latency, repeated immediate response interruption and other semantic
quality regressions. Those signals must create canonical health/incident evidence and
reuse the governed engineering path; they do not self-authorize arbitrary source
changes or promotion.

## Automatic provider-model lifecycle reconciliation

The owner requirement is that routine provider model retirement must not depend on the
owner noticing it manually. The migration candidate therefore adds a bounded Gemini
Live lifecycle controller:

- first-party lifecycle evidence is read from Google's Gemini deprecations page;
- only rows under the Live API model section are eligible;
- no replacement model is guessed and no moving `latest` alias is used;
- automatic migration requires Google's explicit recommended replacement;
- the candidate replacement must remain a Live model;
- before persistence, the candidate must complete a real Gemini Live setup handshake
  with the current credentials and installed SDK stack;
- only the persisted `JARVIS_GEMINI_REALTIME_MODEL` setting is changed;
- startup reconciles lifecycle before preflight;
- a six-hour safety sweep rechecks lifecycle while JARVIS runs;
- a strong `MODEL_UNAVAILABLE` provider failure triggers the same reconciliation
  immediately instead of waiting for the periodic sweep;
- after a successful runtime migration, the active voice runtime shuts down cleanly,
  reloads machine configuration in-process and starts on the replacement model without
  consuming crash/hang Self-Repair budget.

If authoritative lifecycle evidence is unavailable, no replacement is guessed. If the
recommended replacement fails its Live handshake, the current configuration is retained
and the failure remains evidence for investigation.

The durable self-management contract is
`PROVIDER_MODEL_LIFECYCLE_SELF_EVOLUTION.md`. Provider migrations that require source
or Authority/security changes remain governed EngineeringChanges rather than silent
configuration updates.

## Production guardrails

- `JarvisConfig` defaults Gemini realtime voice to `gemini-3.8-live`.
- Startup preflight rejects the known legacy
  `gemini-3.1-flash-live-preview` target.
- The tested production adapter floor remains
  `livekit-plugins-google>=1.8.3`.
- `jarvis-setup` migrates the exact persisted 3.1 legacy model value to 3.8
  while preserving other explicitly configured custom model IDs.

## Gemini 3.8 proactive-audio wake contract

A second-wake owner test exposed a model-specific conversational edge after the
migration. Gemini 3.8 Live has proactive audio permanently enabled, while the prior
JARVIS voice prompt instructed the model to acknowledge a wake-name-only turn. In the
owner log, short wake/greeting turns triggered acknowledgements that overlapped the
next owner utterance and produced interrupted replies.

The voice contract now treats a standalone wake-name utterance as activation residue:
JARVIS remains silent and waits for the actual owner request, including when the wake
name is imperfectly transcribed. Genuine greetings may still receive one short
acknowledgement.

## Deterministic wake-boundary handoff

Prompt-level silence was not sufficient for Gemini 3.8. Owner acceptance showed that
the recognized wake name itself was still present in the audio ring pre-roll handed to
the realtime session. Gemini therefore created a real turn for `Jarvis`/nearby
transcriptions even when the agent instructions requested silence, producing silent or
near-silent generations that could still disturb turn timing.

The wake detector now records the monotonic end timestamp of the exact audio window that
triggered detection. Wake-triggered conversation activation trims pre-roll through that
boundary and preserves only frames observed afterward. This removes already-consumed
wake audio from Gemini while retaining speech that follows immediately after the wake
word, including commands spoken without waiting for session startup. Non-wake sessions
retain the previous pre-roll behavior.

## Conditional wake acknowledgement

The deterministic wake-boundary handoff deliberately removes the recognized wake name
from Gemini input, but JARVIS should still feel responsive when the owner invokes only
the wake word. Wake-triggered sessions now use a short grace window:

- if owner speech arrives during the grace window, no acknowledgement is generated and
  the real request proceeds directly;
- if the owner pauses after waking JARVIS, the already-open realtime session generates
  exactly one brief natural acknowledgement in the established JARVIS voice;
- if owner speech begins while that acknowledgement is starting, the acknowledgement is
  interruptible so the owner request wins;
- startup greetings, standby acknowledgements, update prompts, and non-wake sessions are
  unchanged.

This restores the familiar wake acknowledgement without re-injecting the wake word into
the conversational audio stream.

## Independent standby race found during acceptance

The successful 3.8 owner-machine run exposed a separate existing standby cleanup
race: realtime playback could finish before the committed assistant acknowledgement
item arrived. In that ordering, the acknowledgement flag was set too late, while
post-standby agent state could also cancel the fail-closed standby timeout. JARVIS
could therefore speak "Standing by" without returning to local wake mode.

The acceptance branch hardens this bounded lifecycle edge:

- standby timeout is not cancelled by later thinking/speaking state;
- acknowledgement and playback completion are tracked independently;
- either event order closes the realtime session exactly once;
- physical microphone cutoff at standby acceptance remains unchanged.

## Scope otherwise unchanged

This work does not change:

- wake-word detection;
- MediaDevices microphone routing;
- SessionAudioInput/ObservedSessionAudioInput;
- ChatGPT plan routing;
- DBOS Work orchestration;
- capability acquisition or Hands.

Google did not publish a JARVIS-specific root-cause analysis for the provider
failure. The owner-machine A/B result isolates the failing variable to the
legacy 3.1 realtime target strongly enough to migrate production without
reverting accepted JARVIS architecture.
