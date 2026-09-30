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

## Scope intentionally unchanged

This migration does not change:

- wake-word detection;
- MediaDevices microphone routing;
- SessionAudioInput/ObservedSessionAudioInput;
- lifecycle/session ownership;
- semantic standby behavior;
- ChatGPT plan routing;
- DBOS Work orchestration;
- capability acquisition or Hands.

Google did not publish a JARVIS-specific root-cause analysis for the provider
failure. The owner-machine A/B result isolates the failing variable to the
legacy 3.1 realtime target strongly enough to migrate production without
reverting accepted JARVIS architecture.
