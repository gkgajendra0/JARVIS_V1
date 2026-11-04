# Project personal-request wire contract and one-case diagnosis

Spec: [project memory contract](../../PROJECT_CONVERSATION_MEMORY.md).
Owner b989 six-case result: five completed / one response_contract_invalid, one
persisted routing attempt in the failed p5 profile. The original invalid output
was not retained; its exact rejected field cannot be recovered from routing health.

Confirmed local defect: the project wire embeds PersonalContextRequest's default
schema, which advertises nullable target_quote and permits food/response preference
targets that its existing strict validator rejects. Do not relax the canonical
validator, consent, question binding, scopes, capacity or routing budgets.

1. RED→GREEN wire-only schema specialization: scope-only request for every existing
   scope; targeted request only for permitted scopes with a required non-null string.
   Canonical validation and original byte/quote checks remain authoritative. Test
   the schema at the actual Gemini adapter boundary and retain invalid-input tests.
2. RED→GREEN opt-in lab diagnostics before the routed boundary drops the validation
   cause. Emit only closed reason codes, error counts and input types/known scope
   identifiers; no source text, provider output, error messages or arbitrary keys.
   Preserve exception/result identity, restore patched adapter methods, add no calls
   or retries. Report the coordinator stage and normalized routed failure kind.
3. RED→GREEN select one of the six frozen development cases using an explicit
   development-case option, new root only. Retest p5 alone rather than five already
   completed questions. Invalid mode combinations fail before profile/worktree work.
4. Scoped regressions (real OPA excluded locally), Ruff and a fresh final review.
   Publish to existing draft only and qualify exact head through hosted gates.
   Owner p5 retest is required; do not claim the original null hypothesis proved.

Interfaces: Task1 changes only schema generation; Task2 observes parse exceptions
without changing validation. Task3 passes one existing frozen case through the same
runner and diagnostics. No held-out fixture changes, automatic semantic grader,
paid fallback expansion, installed activation or main merge.

Review focus: canonical/schema agreement, nullable and forbidden targets, unknown
field secrecy, malformed/empty/non-object JSON, observer failure/restoration,
reporting after failure, case/mode guards, and unchanged personal consent/revocation.
