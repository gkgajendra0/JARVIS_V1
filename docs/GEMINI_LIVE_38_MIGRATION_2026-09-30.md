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
