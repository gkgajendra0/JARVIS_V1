# Personal memory slice 1: development acceptance set

Frozen on 2026-11-20 before any slice-1 implementation (design revision 2,
owner-approved 2026-11-20 12:47 IST). Fictional data only. Do not edit the cases;
record results below them. Clarifications approved with the freeze:
"last week" = the previous Monday-Sunday calendar week in the owner's timezone
(expression and anchor preserved; ask when ambiguity materially affects an
action); up to 3 extra pages per question (provisional), then say more exist and
offer continuation or narrowing, with question-bound permissions on every page.


**Rules:**
- Fictional data; isolated labs.
- **Text acceptance first**, then one short voice check in a quiet room (D10, D11, D16, D20).
- **Grading levels:**
  - (a) stored record, via a read-only check script on the lab database;
  - (b) the release (scope results, `complete`, `total`, `date_status`);
  - (c) the answer, manual grade (owner for voice).
- A case where no lookup or no learning happened is **untested**, never passed.
- **Dev (D)** is used during development. **Held-out (H)** is sealed in `docs/evals/personal-memory-heldout.md` and run once after code freeze. Owner-written private cases are optional.

### D: development set

| ID | Area | Conversation (fictional) | Must hold (a / b / c) |
|---|---|---|---|
| D1 | Multiple items, partial dates | "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in March 2017, and last month I got a Jimny." (told 2026-11-17) | 3 rows, 3 sources; acquired year 2021 [2021-01-01..12-31], month 2017-03, month 2026-10; `valid_from` NULL on all; each evidence text names only its own item where separable |
| D2 | Refine | Later: "I bought the Tigor in March 2017, it's the diesel one." | Tigor A superseded by B via `refine`; A not retracted, A's validity unchanged; no new item |
| D3 | Explicit list split | "Remember my devices are a Dell XPS and an iPad Air." (one Hello) | 2 device rows, 2 sources; no plural record; an existing combined record (seeded) unchanged |
| D4 | Ambiguous reference | Two bikes saved; "Should I service my bike before the trip?" | `clarification_required` or both named; never one silently |
| D5 | Selling, week precision | "I sold the Tigor last week." (told Wed 2026-11-18) | historical_change with unknown effective time: old row superseded, `valid_to` NULL; new state sold, disposed week [2026-11-09..15]; `observed_at` 2026-11-18; "when did I sell it?" gives "last week, around 9–15 Nov; you told me on 18 Nov" |
| D6 | Slot-only uncertainty | "I'm planning a Ladakh or winter Spiti trip in January." | status planned; destination options [Ladakh, winter Spiti]; when January |
| D7 | Trip-level uncertainty | "Maybe we'll do Goa this winter." | status considering |
| D8 | Negative: question | "Kaza or Manali, which has better fuel stations?" | no plan written |
| D9 | Negative: idiom / either | "We're going to Spiti in January, Thar or no Thar." then "Either way, January." | planned, destination Spiti; no vehicle options; when January confirmed |
| D10 | Decision + trip vehicle | "We're going with winter Spiti, and we'll take the Jimny." | the same plan changes: destination winter Spiti, vehicle slot Jimny; owned items unchanged; history row keeps the options |
| D11 | Cancellation | "Cancel the Goa plan." | Goa status cancelled; advice doesn't assume it |
| D12 | Correction vs change | "I misspoke, the Jimny is from September, not October." | acquired corrected (old retracted), not refine and not change |
| D13 | Elapsed plan date | Plan "Rishikesh in October 2026" stored; asked on 2026-11-20 "what's coming up?" | release `date_status: passed_outcome_unknown`; answer doesn't call it done, cancelled or upcoming |
| D14 | Restart recall | Restart, fresh wake: "Which vehicles do I own and since when?" | Classic 350 (2021), Jimny (Sept 2026); Tigor shown as sold or omitted per question; precision kept |
| D15 | Useful advice | "Which of my vehicles is best for a snowy Spiti trip?" | uses the owned vehicles and the decided plan; no re-asking |
| D16 | Evidence + told time | "How do you know I have a Jimny, and when did I tell you?" | owner's words quoted or paraphrased from the evidence; told date distinct from the purchase month |
| D17 | Forget one item | "Forget the Classic 350." (Hello) | its lineage and sources gone; no remaining evidence text contains "Classic 350"; Tigor and Jimny facts and evidence intact; project-history whole-row redaction recorded as a known limitation |
| D18 | Scale beyond page | 11 vehicles saved; "Which vehicles do I own?" | `total` 11, `released` ≤8, `complete` false; the answer says the list is partial or pages on; with paging, all 11 named |
| D19 | Scale beyond 32 | 45 plans plus 45 other facts (90 standard rows); learning a new fact plus a lookup | no overflow; the learning candidate resolves; the lookup is correct and complete-or-partial truthfully |
| D20 | Byte budget | 6 vehicles with long details (more than 3,000 bytes total) | page ends by bytes; `complete` false; no truncated item |
| D21 | History integrity | After D1–D17: read-only check | refine predecessors superseded, not retracted, validity untouched; corrections retracted; changes superseded with correct unknown or known effective times; no orphan sources; every current row has evidence |


**Pass bar:**
- every (a) and (b) check passes;
- (c) correct on every D case and on at least 10 of 11 H cases;
- **absolute failures:** an invented date or finer precision; a slot alternative or tentative plan stored or spoken as decided; a forgotten item or its evidence recoverable from personal memory; a partial list presented as complete; a refine stored as retracted;
- existing personal-context, learning, forget and migration suites still pass.


### Added at freeze (clarifications 2026-11-20)

| ID | Area | Conversation (fictional) | Must hold (a / b / c) |
|---|---|---|---|
| D22 | Sale with uncertain date leaves current ownership | After D5: "Which vehicles do I own?" and a read-only check | old owned row superseded (not current) with `valid_to` NULL; new row state sold, `valid_from` NULL, disposed week [2026-11-09..15]; current owned list excludes the Tigor; no row claims an exact sale day |
| D23 | Month-only sale | "I sold the Classic 350 in October." (told 2026-11-20) | sold, disposed month 2026-10 [10-01..10-31]; effective time unknown; not currently owned |
| D24 | Skipped candidate recorded, never claimed | 40 near-identical "trip" plans saved; "Add Bir to the paragliding trip." is ambiguous | candidate skipped with a recorded reason (`catalog_page_ambiguous` or `ambiguous_existing_fact`) in the content-free outcome record; no new or changed fact; the answer does not claim it was saved |
| D25 | Pages run out | 40 vehicles; "List all my vehicles." | first page plus 3 extra pages (32 items) released; the answer says more exist (total 40) and offers to continue or narrow; each page bound to the same question permit |
| D26 | Forget residual scan | After D17 and H10-style forget | no occurrence of the forgotten label or aliases in any personal-memory text: `value_json` (label, aliases, details, slots), `normalized_text`, FTS index content, embeddings rows, `memory_source.evidence_text`, learning outcome records, topic checkpoints; diagnostic logs and backups listed as retained (known limits) |
| D27 | Migration integrity | Isolated copy of the installed database (schema 7) migrated to 8 | integrity and foreign-key checks pass; row counts and per-table content digests unchanged except `memory_operation`'s definition; all operation rows preserved; old code (29714335) refuses the migrated copy with `MemorySchemaTooNewError` (documents rollback) |
