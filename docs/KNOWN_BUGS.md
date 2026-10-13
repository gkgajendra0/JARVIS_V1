# Known Bugs

## BUG-001 — Background owner-input session captures unrelated live speech

**Status:** Logged / deferred  
**Severity:** High  
**First observed:** 2026-10-01  
**Do not start remediation yet.**

### Symptom

While a background capability-acquisition work item was waiting for owner input about the movie/source for *The Transporter*, the owner was on an unrelated HR call discussing email. JARVIS captured the HR-call speech as the answer to the pending background work item and replied about *The Transporter*.

Observed transcript:

- Owner speech: "email I think yes yesterday or day before yesterday I got an email."
- JARVIS reply: "I am afraid that does not clarify the film or source. Do you mean The Transporter from 2002, and which streaming service or source would you like to use?"

### Confirmed runtime facts

- Production runtime was running the configured microphone, Lenovo camera, RF-DETR/person tracking, CAM++ speaker shadow, and LR-ASD active-speaker processing.
- The LR-ASD / owner-speaker path is currently **shadow/diagnostic only** and has no authority effect.
- During the observed turn, logs reported:
  - `live_owner_context=False`
  - `active_speaker_confirmed=False`
  - `owner_classification=False`
  - `authority_effect=False`
- The pending WorkItem repeatedly reopened an owner-input realtime interaction after delivery/generation failures and durable backoff.
- `_run_owner_input_interaction()` intentionally keeps the microphone open without requiring the wake word so the owner can answer the exact pending question.

### Root-cause hypothesis to validate before implementation

This is not evidence of a random model hallucination. The *Transporter* context was real pending-work context. The failure appears to involve two separate control gaps:

1. **Active-speaker authority is not promoted yet.** Audio + video identity/active-speaker processing runs, but its result does not gate conversation admission.
2. **Foreground/background intent arbitration is missing or insufficient.** Once a background owner-input interaction is active, unrelated owner speech can be interpreted as an answer to that background question.

Speaker confirmation alone is not enough: even correctly identified owner speech can belong to an unrelated phone call or foreground conversation.

### Required future investigation

Before changing production behavior:

1. Reproduce with a pending `WAITING_FOR_OWNER` WorkItem while the owner speaks unrelated content nearby/on a call.
2. Verify the exact session-ownership path through `_deliver_pending_work()`, `_run_owner_input_interaction()`, and the LiveKit session.
3. Define explicit foreground/background conversational arbitration.
4. Add semantic relevance/admission handling for pending owner-input prompts.
5. Complete owner-machine calibration/acceptance before promoting CAM++/LR-ASD from shadow diagnostics to authority.
6. Decide how background owner-input should behave when the owner is visibly/actively engaged in another conversation.
7. Add regression tests covering stale durable retries and unrelated speech.

### Non-goals for this bug entry

- Do not disable durable Work/DBOS.
- Do not remove proactive owner-input capability.
- Do not simply enable the current LR-ASD threshold as a quick fix.
- Do not change provider/model solely to address this symptom.
- Do not begin implementation until the current capability-acquisition validation is completed or the owner explicitly reprioritizes this bug.

## BUG-002 — Startup greeting can contradict deterministic local time

**Status:** Logged / deferred  
**Severity:** Low  
**First observed:** 2026-10-01  
**Do not start remediation yet.**

### Symptom

JARVIS started during the local afternoon but said, "Good morning, sir. All systems are online."

### Confirmed implementation behavior

- `select_startup_greeting()` deterministically selects a time-of-day greeting family from the local machine clock.
- The selected sentence is not spoken directly. `VoiceRuntimeController._speak_startup_greeting()` sends it to the realtime conversation model as a contextual cue and asks the model to vary the wording naturally.
- The realtime model therefore has enough freedom to change a deterministic fact such as morning/afternoon/evening.

### Expected behavior

Machine-owned facts such as local time-of-day must remain authoritative. The realtime model may vary style around that fact, but must not replace or contradict it.

### Required future investigation

1. Preserve the deterministic time-of-day token or greeting as a non-negotiable fact in lifecycle speech.
2. Decide whether to speak the exact machine-selected greeting or constrain realtime generation so only non-factual wording varies.
3. Add tests proving morning/afternoon/evening/late-night output cannot cross time buckets.
4. Preserve the current shared realtime voice path unless a separate design decision changes it.

### Non-goals for this bug entry

- Do not replace Gemini/realtime voice solely for this issue.
- Do not begin implementation until the owner explicitly reprioritizes this bug.
