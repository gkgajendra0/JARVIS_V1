# Personal memory slice 1: acceptance amendment 1 (D1 wording)

**Status: PROPOSED — not approved, not in force.** Proposed 2026-11-23.

This file is separate from the frozen case files. Neither
`docs/evals/personal-memory-acceptance.md` (sha256
`ed249d688826a18263fd578ff7980a2619057845a674c28d94763bbd5cb3823b`) nor
`docs/evals/personal-memory-heldout.md` (sha256
`fb2c36a4f29eb4638b863d9e1db142599b3c7b265ffbab6db360195dd21d08a1`, sealed,
not read) is edited. Recorded results for labs 1–7 stand as they were.

## Reason

The frozen D1 wording is ambiguous:

> "I have a Royal Enfield Classic 350 **from 2021**, a Tata Tigor I bought in
> March 2017, and last month I got a Jimny."

"have … from 2021" can mean "I've had it since 2021" (a purchase date) or
"it's a 2021 model" (a model year). The frozen expectation reads it as the
purchase year (acquired year 2021). By owner decision (2026-11-23 17:27 IST),
the conservative reading applies: "have … from 2021" must not establish a
purchase date by itself. Only acquisition wording ("bought", "got", "since", …)
linked to the item does.

So the frozen D1 check `acquired classic 350` tests an interpretation the
owner has rejected. It is **not** reported as passed. It is kept and reported
as it is: expected to FAIL.

## Amendment

### D1 (amended): multiple items, explicit purchase dates

| ID | Area | Conversation (fictional) | Must hold (a / b / c) |
|---|---|---|---|
| D1-A1 | Multiple items, partial dates | "I have a Royal Enfield Classic 350 I bought in 2021, a Tata Tigor I bought in March 2017, and last month I got a Jimny." (told 2026-11-17) | 3 rows, 3 sources; acquired year 2021 [2021-01-01..12-31], month 2017-03, month 2026-10; `valid_from` NULL on all; each evidence text names only its own item where separable |

Only the Classic clause changes ("from 2021" → "I bought in 2021"). The
expectations are the frozen D1 expectations, unchanged.

### D1-R (regression): the original ambiguous wording

| ID | Area | Conversation (fictional) | Must hold (a) |
|---|---|---|---|
| D1-R | Ambiguous date role | The frozen D1 wording, verbatim (told 2026-11-17) | 3 rows, 3 sources; Classic 350 stored **without** an acquisition date (no year invented); Tigor month 2017-03 and Jimny month 2026-10 as frozen; `valid_from` NULL on all |

D1-R keeps the original ambiguity as a permanent regression: the system must
never invent a purchase date from it.

### Dependent case: D14 (restart recall)

The frozen D14 expects "Classic 350 (2021)". That depends on D1 storing a
Classic purchase year:

- With **D1-A1** in force, D14 is graded exactly as frozen.
- In a run that uses the **original** wording (D1-R), "2021" for the Classic
  can only come from the released owner quote, not from a stored purchase
  date. D14's frozen "Classic 2021" check is then graded as frozen and reported
  as it comes out, with this dependency noted; it is not adjusted.

No other case depends on the Classic's purchase date (D17 forgets the Classic;
D23 sells it in October and keeps its stored acquisition as it is).

## How it would run (if approved)

- The lab uses D1-A1 for the story step and adds D1-R as a separate step on
  its own isolated memory, both recorded in separate result files with this
  file's sha256 next to the frozen hashes.
- The frozen D1 check stays in the harness unchanged and keeps reporting its
  result against the original wording.

## Current evidence (assessed in code, not live-verified)

- `test_proposed_amended_d1_wording_establishes_all_three_dates`: lab 7's
  recorded D1 proposals replayed against the D1-A1 text give year 2021,
  month 2017-03 and month 2026-10.
- `test_d1_original_ambiguous_from_2021_never_becomes_a_purchase_date` and the
  lab harness check `regression: ambiguous 'from 2021' stores no Classic
  purchase date`: the original wording stores no Classic acquisition date;
  Tigor and Jimny keep theirs.
- The scripted harness run reports D1 as FAIL on exactly the frozen
  `acquired classic 350` check, with the regression check PASS.
