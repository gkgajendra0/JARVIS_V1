# Shared voice activity handling

Every normal Jarvis voice session explicitly supplies the bundled local Silero
VAD to LiveKit, regardless of personal-context mode. This separates physical
speech activity from provider-generated speech-start events during tool replies.
Provider-native turn completion and genuine interruptions remain enabled.

Hands continues to require the final canonical USER instruction for the current
activity and to reject superseded or duplicate commands. If that instruction
does not arrive within the existing deadline, Hands returns one clarification
request. Further calls for that activity suppress automatic responses through
LiveKit's `StopResponse`; new speech activity is required to try again. A late
transcript alone does not reactivate a timed-out request.

## Manual acceptance after restart

1. Ask to open Calculator and wait for completion.
2. Ask to maximize Calculator and report the open windows. Remain silent until
   it finishes; the request must not be superseded by a tool continuation.
3. Ask for a longer ordinary answer, then interrupt with a new request. Real
   interruption should still stop the old response and accept the new one.
4. Inspect the log for repeated canonical-transcript timeouts. Any remaining
   failure needs investigation; automated coverage does not certify the live
   microphone, speaker echo, or provider event timing.

This change does not enable personal memory, change authorization policy, or
request Priority inference.
