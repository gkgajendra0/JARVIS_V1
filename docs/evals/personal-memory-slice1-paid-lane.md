# Personal memory slice 1: Paid-lane development acceptance (lab only)

Owner approval: 2026-11-23, up to USD 1 for Paid development acceptance only.
Held-out tests, voice tests and normal Jarvis are excluded. Product code is
unchanged; this is the lab runner (`src/jarvis/voice/paid_acceptance_budget.py`,
`project_memory_lab.py --paid-lane`).

## Lane

- Extraction, resolution and answers use `JARVIS_GEMINI_PAID_API_KEY` only.
  There is no router, and the Free credential is withheld from the process
  for the run. A lab never changes lane, and nothing falls back between lanes.
- Every request is checked before anything is reserved or sent. Anything
  else is refused (`PaidRequestRefused`) and nothing is sent. The check
  requires:
  - model `gemini-3.5-flash-lite`;
  - text input and instruction;
  - a text/JSON response format;
  - `store=False`;
  - `generation_config` exactly `{max_output_tokens}`, in the range 1..8192.

  Refused examples: other models, thinking options, tools, caching, media and
  stored interactions.
- Results: the console, every result row and the summary say `lane: paid`.

## Budget

- One SQLite ledger (`E:\Jarvis\Temp\slice1-paid-budget\ledger.sqlite3`),
  budget `slice1-paid-dev-acceptance-2026-11-23`, ceiling USD 1.00.
  - It is shared by every Paid lab, retry and resume.
  - There is no reset or increase.
- **Prices:** gemini-3.5-flash-lite paid tier (ai.google.dev pricing, checked
  2026-11-23). Input costs $0.30 per 1M tokens; output costs $2.50 per 1M
  tokens, and thinking is billed as output. Cached-input discounts are
  ignored.
- **Reservation before each request** (committed to disk before sending):
  - **input:** UTF-8 bytes of the instruction, input and response schema,
    plus 256. A token is never shorter than a byte.
  - **output:** the request's own `max_output_tokens`. Google documents that
    `max_output_tokens` "applies to the combined total of thinking tokens and
    output tokens" (https://ai.google.dev/gemini-api/docs/thinking), so the
    reservation covers thinking.
  - **typical reservation:** extraction (4,096 output) ≈ USD 0.0137;
    resolution ≈ USD 0.014; answers (2,048 output, 16–40 KB sent) ≈ USD 0.010–0.017.
- **Settlement:**
  - From the reported usage: input plus tool-use tokens at the input price,
    and the larger of output + thinking or total − input at the output price.
  - When usage is unknown, the whole reservation stays charged. That covers
    provider errors, 429s, timeouts, cancellations, crashes and missing usage.
  - A settled cost above its reservation halts the ledger.
- **Retries:** each retry attempt is its own request with its own reservation.

## Checkpoint (owner instruction 2026-11-24)

- **What it runs:** `-PaidCheckpoint` runs the story group to `story-05c` and
  then pauses for review. That covers:
  - learning: story-01 to 04;
  - a lookup and an answer: story-05, "When did I sell it?";
  - the D1-A1, D2 and D5 checks.
- **Cap:** allowance `slice1-paid-checkpoint-1`, at most USD 0.10 of the
  shared USD 1. The allowance's cap is fixed in the ledger.
- **Continuing:** completed steps are kept. Running the checkpoint again
  sends nothing. Continuing with `-ResumeLab` without `-PaidCheckpoint` never
  repeats a completed step.

## Stopping

- **Definite failure:** the Paid lane stops on a definite acceptance failure,
  meaning a case FAIL, or UNTESTED from a broken prerequisite. It writes
  `run_state: stopped_on_failure` and exits with code 3. A resume refuses to
  continue past it.
- **Provider failures:** exhausted bounded retries stop the run as an
  interruption.
- **Answers:** incorrect answers and invalid output are never retried.

## D17 consent recovery (owner instruction 2026-11-24 14:48)

- **When:** only when D17's latest result is a FAIL at stage
  `owner_consent_not_granted` and all of the following hold:
  - the item was listed and read correctly;
  - every forget call aimed at it and was stopped by consent;
  - the item is still stored, which is checked again live before the turn
    runs;
  - no other case has failed;
  - the recovery has not been used before (it is single-use).

  Otherwise the recovery is refused (exit code 4) and nothing is sent.
- **What it does:** `-ResumeLab -RecoverD17Consent` reruns only `story-18`
  ("Forget the Classic 350.") and its check `story-18c`, as attempt 2. It
  then pauses for review before D26 and D21.
  - Windows Hello is still required.
  - The turn starts a new conversation, recorded as a resumed follow-up.
- **Records:**
  - The original attempt's rows stay in every log.
  - New `reopened_for_recovery` rows and a `recovery_started` event mark
    the recovery.
  - The summary lists `recoveries` and `earlier_case_results`.
  - D17's check counts only the latest attempt's consent requests.
- **Cap:** allowance `slice1-paid-d17-recovery-1`, at most USD 0.05 of the
  shared USD 1.
- **After the recovery:**
  - If D17 passes, a normal `-ResumeLab` continues with D26, D21 and the
    remaining groups, without repeating completed steps.
  - If it fails again, the failure lock stays.
