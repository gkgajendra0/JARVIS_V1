# Step 2 Long-Utterance Activity Correction — Acceptance

Date: 2026-09-08
Branch: `fix/step-2-long-utterance-activity`
Owner acceptance head before documentation reconciliation: `2543e56`
PR: #25

## Defect

During Step-6 owner acceptance, a pre-existing Step-2 lifecycle defect was exposed: after wake, a long first spoken request could be cut off because JARVIS could return to local wake detection before the realtime provider committed the user turn.

Two causes were corrected:

1. production `AgentSession` had opted out of LiveKit local VAD while the outer JARVIS lifecycle depended on `user_state_changed` to know whether the user was actively speaking;
2. the initial inactivity timeout was historically allowed to run across realtime-session startup, so provider/session initialization consumed part of the user's nominal response window.

## Accepted behavior

The corrected production path now keeps provider-native realtime turn completion while using LiveKit local speech activity only as outer-lifecycle evidence:

- local speech activity does not become a second conversational turn authority;
- inactivity timing is suppressed during realtime-session startup;
- the initial inactivity window begins from the first real LiveKit listening state;
- `speaking` cancels JARVIS inactivity shutdown;
- no inactivity timeout is armed while local activity reports that the user is speaking;
- after speech returns to listening, normal initial/follow-up inactivity behavior resumes;
- the historical `max_utterance_seconds` value no longer acts as an outer-session kill timer while the user is actively speaking;
- normal provider-native end-of-turn and interruption behavior remain in place.

## Automated evidence

Exact-head Code Quality run on `2543e56` passed all required jobs:

- Ruff: PASS
- full pytest: PASS
- Windows DPAPI: PASS
- Windows Hello helper: PASS

Regression coverage includes:

- `AgentSession` no longer explicitly receives `vad=None`;
- provider-native turn detection remains selected;
- startup inactivity is not armed before the first real listening state;
- continuous active speech cancels/suppresses inactivity shutdown;
- handler ordering cannot reintroduce the historical max-utterance kill timer while speaking.

## Owner-machine evidence

Owner ran `jarvis-voice` on Windows with Pocket3 microphone and NVIDIA TV output on exact code head `2543e56`.

### Idle behavior

One wake session intentionally/observationally contained no accepted user speech. JARVIS logged:

- `Voice agent state changed: initializing -> listening`
- `Voice session inactivity timeout expired | seconds=8.00 | user_speaking=False | canonical_user_turns=0`
- return to local wake detection

This is accepted: no user speech was active and no canonical user turn existed, so the normal initial idle timeout remained functional.

### Long-utterance behavior

On the following wake session JARVIS logged real local activity transitions:

- `Voice user state changed: listening -> speaking`
- later `Voice user state changed: speaking -> listening`

The complete long request was committed as one canonical user turn:

> Explain in simple terms how SQL join work? Why a primary key and a foreign key matter? How an inner join differ from a left join and give me a small example using employee and department table so I can understand the relationship clearly.

JARVIS remained in the active conversation and answered the request instead of returning to wake mode mid-speech. The committed speaker-shadow capture reached the existing bounded 15-second diagnostic window without the active voice session being killed.

### Interruption / follow-up behavior

The same active session then accepted follow-up/interruption requests including:

- `Jarvis, explain me in short.`
- `Okay, Jarvis. Stop. I don't need it.`

The final stop request was accepted and JARVIS responded `Understood, sir.` This demonstrates that the lifecycle correction did not remove normal barge-in/follow-up usability.

## Acceptance decision

**OWNER ACCEPTED.**

The bounded Step-2 correction is accepted for protected-main merge after documentation reconciliation and final exact-head CI.

This acceptance does not change the separate provider endpointing policy. Gemini's current native silence/end-of-turn configuration remains unchanged because the owner-machine test no longer demonstrated a need to tune it as part of this defect.
