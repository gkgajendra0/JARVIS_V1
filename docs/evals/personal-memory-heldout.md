# Personal memory slice 1: held-out set (sealed; do not tune on it)

Frozen on 2026-11-20 before any slice-1 implementation (design revision 2,
owner-approved 2026-11-20 12:47 IST). Fictional data only. Do not edit the cases;
record results below them. Clarifications approved with the freeze:
"last week" = the previous Monday-Sunday calendar week in the owner's timezone
(expression and anchor preserved; ask when ambiguity materially affects an
action); up to 3 extra pages per question (provisional), then say more exist and
offer continuation or narrowing, with question-bound permissions on every page.

Run once, after code freeze, unchanged. Do not adjust the implementation to these cases afterwards.

### H: held-out set (sealed, not used for development)

| ID | Area | Conversation (fictional) | Must hold |
|---|---|---|---|
| H1 | Devices, mixed precision | "My laptop is a ThinkPad X1 I got in 2023, and my phone is a Pixel 8 since this August." | 2 rows; year 2023; month August (current year); validity NULL |
| H2 | Hinglish possession | "Mere paas ek Activa hai, 2019 mein li thi." | 1 vehicle; year 2019; original-script label |
| H3 | Gift, not sale | "I gave my old Activa to my cousin." | state gave_away; effective time unknown; excluded from current owned list |
| H4 | Tentative purchase | "Maybe I'll buy an e-bike next year." | no owned item; at most a considering plan |
| H5 | Date options only | "Diwali trip to Jaipur, either the first or second week of November." | planned; destination Jaipur; when options |
| H6 | Negative: comparison question | "Udaipur or Jodhpur, which is hotter in May?" | no plan |
| H7 | Rescheduled | "The Jaipur trip moved to December." | historical_change; history keeps the November options; when December |
| H8 | Exact day refine | "I bought the ThinkPad on 14 March 2023." | refine; day precision; `valid_from` 2023-03-14 local start; prior row superseded, not retracted |
| H9 | Elapsed + ambiguity | Two laptops; old plan "Kerala in August" (elapsed): "Is my laptop fine for the Kerala trip?" | clarifies the laptop; the Kerala date passed with outcome unknown, not assumed |
| H10 | Forget, keep others | "Forget the Pixel." | Pixel lineage and evidence gone; ThinkPad evidence clean and intact |
| H11 | Scale, other category | 10 devices; "What devices do I have?" | partial disclosed or paged; never 8 presented as all |


**Pass bar:**
- every (a) and (b) check passes;
- (c) correct on every D case and on at least 10 of 11 H cases;
- **absolute failures:** an invented date or finer precision; a slot alternative or tentative plan stored or spoken as decided; a forgotten item or its evidence recoverable from personal memory; a partial list presented as complete; a refine stored as retracted;
- existing personal-context, learning, forget and migration suites still pass.

