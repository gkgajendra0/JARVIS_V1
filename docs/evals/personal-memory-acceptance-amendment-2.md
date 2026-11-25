# Personal memory slice 1: acceptance amendment 2 (plan alternatives)

**Status: APPROVED — active.** Behaviour approved by the owner 2026-11-25
13:40 IST. This file records it.

This file is separate from the frozen case files. Neither
`docs/evals/personal-memory-acceptance.md` (sha256
`ed249d688826a18263fd578ff7980a2619057845a674c28d94763bbd5cb3823b`) nor
`docs/evals/personal-memory-heldout.md` (sha256
`fb2c36a4f29eb4638b863d9e1db142599b3c7b265ffbab6db360195dd21d08a1`, sealed,
not read) is edited. Amendment 1 stays active. Recorded results of labs 1–8
and Paid labs 1–6 stand as they were.

## Reason

Plan alternatives ("Ladakh or winter Spiti", "Thar or no Thar") are the
model's reading of the owner's words. Paid labs 4 and 6 recorded the model
proposing an idiom of indifference ("Thar or no Thar") as alternatives; code
cannot tell such a reading from a real choice without sentence rules. By
owner decision, alternatives are therefore not stored on the model's reading
alone.

## Approved behaviour

- Clear facts and final decisions are saved as before.
- A plan detail proposed as alternatives (two or more options, no value) is
  **not stored**, whatever certainty the model gives it. It stays pending in
  the conversation. The clear parts of the same statement are saved
  independently.
- Jarvis asks one brief question about only that detail (whether the owner is
  still choosing between those options), without repeating known
  information. One question per detail; never asked twice.
- The owner's next answer, as read by the extractor; code decides what it
  allows:
  - **confirmation**: the alternatives are saved as undecided on the same
    plan (evidence: the owner's original words and the confirming turn;
    history kept);
  - **final choice**: the decision is saved on the same plan;
  - **"doesn't matter"**: the pending detail is discarded;
  - **unrelated reply, or the conversation ends**: nothing is saved.
- No sentence-specific rules and no additional model. Permissions, evidence,
  history and unrelated details are unchanged.

## Amended and added cases

### D6-A2 (replaces D6 in the story): alternatives confirmed

| ID | Area | Conversation (fictional) | Must hold (a / b / c) |
|---|---|---|---|
| D6-A2 | Slot-only uncertainty, confirmed | "I'm planning a Ladakh or winter Spiti trip in January." then, in the same conversation, "Yes, still deciding between those." | (a) after the first statement: one plan, status planned, when January, **no destination options stored**; (b) one open question about the destination choices reached the reply; (a) after the confirmation: the same plan (superseding row), status planned, destination options [Ladakh, winter Spiti] with no value, when January; (c) the first reply asks once whether they are still choosing, without claiming anything was saved |

The frozen D6 expectation "destination options [Ladakh, winter Spiti]"
immediately after the single statement is reported as **SUPERSEDED** (by
amendment 2) with the observed value. SUPERSEDED is neither PASS nor FAIL and
does not affect any verdict.

### D10 (unchanged)

D10 runs after D6-A2's confirmation turn and is graded exactly as frozen: the
same plan changes to destination winter Spiti and vehicle Jimny; owned items
unchanged; the history row keeps the options (the confirmed row).

### D9 (unchanged checks, one clarification)

D9's frozen checks are graded as frozen. D9 does **not** require a question:
when the meaning is understood (no vehicle proposed), none is asked. If the
model proposes the vehicle as alternatives or leaves it unclear, Jarvis may ask
once, about the vehicle only; "Either way, January." leaves no vehicle saved.
Added check (b): at most one question, and only about the vehicle.

### D28–D30 (added): the other answers

Own isolated memory (group `alternatives`), one conversation each.

| ID | Area | Conversation (fictional) | Must hold (a / b / c) |
|---|---|---|---|
| D28 | Final choice | "We're going to Spiti in January, Thar or Jimny." then "We'll take the Jimny." | (a) after the first statement no vehicle stored; (b) one question about the vehicle; (a) after the answer: the same plan with vehicle Jimny decided, destination Spiti and January kept, no vehicle options |
| D29 | Doesn't matter | "We're going to Kerala in March, train or flight." then "Doesn't matter, either is fine." | (a) one Kerala plan, March kept; no travel mode or vehicle options and no value stored at any point |
| D30 | Unrelated reply, then conversation end | "We're going to Goa in April, Airbnb or hotel." then "What's the weather like there in April?" then, in a new conversation, "Yes, still deciding between those." | (a) one Goa plan, April kept; no stay options or value stored at any point; the new conversation's reply carries no open question from the old one |

## How it runs

- Story: `story-07` (case D6-A2) is followed by `story-07b`, "Yes, still
  deciding between those.", in the same conversation; `story-07c` grades
  D6-A2 and reports the superseded frozen D6 expectation.
- Group `idiom`: unchanged steps; D9 adds the (b) check above.
- Group `alternatives`: D28, D29, D30.
- Every result row and the summary record this file's sha256 and "amendment 2:
  active". The lab refuses to start if this file differs from the approved
  version.
- Earlier results (graded against the frozen D6 wording and expectation) are
  preserved unchanged.
