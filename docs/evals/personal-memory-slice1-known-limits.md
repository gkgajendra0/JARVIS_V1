# Personal memory slice 1: known limits (recorded, not defects)

Recorded 2026-11-23 with owner approval of frozen implementation `5f57de48`
(product code at PR C `d0a9acd5`). These limits are part of what slice 1
delivers. No result may claim them as working.

## Removing a single plan detail is unsupported

- Example: "Correction: we're not taking the Jimny on the Spiti trip."
- The slice-1 proposal schema has no removal marker. An empty detail means
  "not said", so a correction can never delete a detail.
- Outcome: nothing is changed (the vehicle stays Jimny). The turn is recorded
  as skipped, reason `correction_unclear`. Test:
  `test_a_stated_removal_cannot_delete_a_detail_and_is_recorded`.
- No successful-removal claim. The reply model never sees the learning
  result. The voice instructions forbid saying "saved", "updated my memory" or
  equivalent wording unless a successful canonical tool result confirms it.
  Explicit memory tools return their own results, and those are authoritative.
- Not covered: whole-plan cancellation (a status change) and retraction of a
  whole fact, which work as before.

## Purchase/disposal date evidence is a closed word list

- English and Hinglish acquisition words (bought, got, purchased, since,
  liya, kharida, …) and disposal words (sold, gave, lost, scrapped, traded,
  stolen, becha) are recognised. Other phrasings ("2021 se mere paas hai")
  save the item without the date and record `date_evidence_missing`. Nothing
  is invented.
- "have … from <time>" never sets a purchase date (amendment 1, D1-R).

## Unfamiliar categories are assessed in code only

- Person and routine facts go through the shared create/refine/change/
  correct/retract path, matching, provenance and forget. That was assessed
  by reading the code, not in any live or lab run. They are not acceptance
  evidence.
