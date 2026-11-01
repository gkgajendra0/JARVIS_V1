# Project archive lexical ranking repair

The owner approved repairing the demonstrated PR 303 search gap, with recovery regressions followed by offline verification. This small change retains the current Python/SQLite architecture.

## Intent and constraints

Recover an older original matching several query terms despite many newer partial matches. Keep the latest matching source per role as a recency anchor so a recent user correction is not displaced by lexical relevance. Preserve user/assistant interleaving, chronological returned evidence, scoped SQL parameters, exclusion of the current request, eight-result search and existing packet/tool/authority limits. No inference, provider calls, frozen fixture changes, schema migration or installed activation.

## Approaches

Increasing the hit limit consumes context and still permits crowding. Embedding retrieval adds dependencies and qualification work. The chosen narrow repair promotes one best distinct-term lexical candidate per role alongside its newest matching evidence, filling remaining slots by recency and interleaving roles. Ranking every remaining slot by term coverage was rejected in review: redundant old full-term matches displaced a recent matching cancellation followed by accessory chatter.

Source selection priority is retained as a local-only `ArchivedSource.search_priority` value through byte-budget admission. Latest matching evidence takes priority 2, the best lexical candidate 1, other evidence 0. User originals still precede assistant material. The source wire content is unchanged and admitted rows are presented chronologically. Later source reads cannot erase an existing search priority. This prevents packet fill from throwing away the very old original recovered by search when messages are long.

Single-term queries still use recency; the fixture's `Jimny`-only query remains a documented limit. Matching terms are evidence-selection hints, never proof of truth. This fixed eight-result budget cannot preserve every historical correction: at most one recency slot per role is traded for the lexical candidate. Corrections outside selected evidence, or originals too large for the unchanged packet budget, remain subject to explicit partial-coverage reporting. This repair does not guarantee current truth from an old matching source.

## Acceptance

Specific-query 100/200-event scenarios recover the old decision into the final bounded packet, with both short sources and 1,000-character padding. Recent matching cancellation followed by later matching chatter remains selected in the review regression. Original users survive assistant echoes. Duplicate terms cannot inflate relevance. Existing scope, no-match, full-budget and chronological-output tests remain green. Measure without claiming model accuracy or token savings.
