# Project memory transport contract

Implementation evidence, 2026-10-30 UTC. This document qualifies a dispatch
boundary; it does not qualify microphone input, real Gemini answers or playback.

## Pinned native adapter finding

The repository pins `livekit-agents[google,openai]==1.8.3`,
`livekit-plugins-google==1.8.3`, and `google-genai==2.22.0`.
The installed Google `realtime/realtime_api.py` has these behaviors:

- `RealtimeSession._start_new_generation` emits `generation_created`.
- `_handle_server_content` requires an existing generation and processes model
  text/audio before input transcription in the same server message.
- Input transcription at that point is emitted with `is_final=False`.

`test_pinned_google_adapter_can_emit_generation_before_final_transcript` invokes
those installed production handlers with a server-content fixture. It opens no
socket. This demonstrates a permitted ordering, rather than claiming to measure
frequency on the service. Accepted-transcript observers and audio buffering alone
cannot establish context-before-generation for this path. Mid-session context
mutability is insufficient evidence of that ordering.

## Selected implementation seam

`ProjectReplyDispatcher.reply(request_id, prepare)` awaits the required archive
commit and context-preparation callback. Only a matching immutable
`PreparedProjectReply` that passes currentness validation can reach the provider.
The provider receives that packet, including request identity, selected project,
source IDs, context revision and bounded text. It must put that context into the
actual generation request; attaching a production provider remains a later step.

The dispatcher validates again before each synchronous audio release and after
completion. New speech, project switch and transport recreation invalidate the
local epoch. Source/personal revisions and owner authority belong to the supplied
canonical validator. Cancellation closes the provider generator. A failed archive
write propagates rather than being reported as a successful save.

Audio release here means admission to a synchronous playback boundary. A future
player must also flush already queued audio on invalidation; these tests do not
prove device playback cancellation. The dispatcher does not itself cancel an
in-flight network request on invalidation; it suppresses later output. Provider
cancellation and usage accounting still need integration.

## Voice fallback and credential constraint

Use the approved controlled transcript -> existing Gemini text answer -> existing
TTS architecture when native ordering cannot be established. The pinned Google
STT class uses Google Cloud Speech credentials (ADC or explicit service-account
credentials), rather than the existing Gemini API key. Do not silently activate
that separate service, select another account, upgrade SDKs, or download a local
speech/model stack. The current seam can be exercised with accepted text without
any provider request; native microphone qualification remains open.

## Evidence and limits

The scoped tests exercise the actual dispatcher and installed adapter handlers,
with provider and playback boundaries replaced. They check archive waiting/failure,
exact packet delivery, invalidation during preparation/generation, authorization
revocation and cancellation. They establish local ordering only. No real provider
request, billing measurement, STT accuracy, Windows SQLCipher, microphone or
end-to-end voice acceptance has run for this replacement path.
