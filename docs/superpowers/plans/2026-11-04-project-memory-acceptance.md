# Project-memory acceptance hardening

Goal: continue PR #312 safely and prevent a false production acceptance PASS.

Scope approved in chat: inspect the installation, strengthen acceptance in isolation,
verify, and prepare a concrete merge/deployment proposal. Do not merge, deploy, stop
Jarvis, reset memory, or remove the existing disputed personal fact.

Approach: retain the Python recorder and existing schema. Add a separate existing-only
SQLCipher URI read-only opener; never invoke migrations or key creation for inspection.
Match database evidence to canonical turn IDs and expected project titles, rather than
old keyword rows. Require replies and save receipts. Treat unresolved REVIEW as
INCOMPLETE. Automated keyword checks remain smoke checks; require a reviewer record
bound to the collected evidence digest for response meaning and observed restart.
No provider calls, new dependencies, model judge, schema changes or new live prompts.

Alternatives: relying on keywords preserves false passes; adding an LLM judge adds
provider cost and another fallible model. Explicit evidence review fits this one-PC
acceptance task. New-wake session IDs are checked automatically; actual process
restart and spoken audio correctness require documented observation.

1. Reproduce false passes and unsafe database-opening behavior with tests.
2. Implement read-only opener and test missing files, denied writes, unchanged
   encrypted bytes/schema, invalid keys, and exception cleanup.
3. Strengthen recorder: canonical IDs, project evidence, mandatory receipt/reply,
   unique titles, REVIEW handling, evidence-bound manual review and restart notes.
4. Update the audit and operating instructions to separate CI from live acceptance.
5. Run focused tests, relevant memory/voice checks, Ruff and the full suite. Review
   the final diff; prepare a patch and deployment/rollback checklist. Preserve live
   app, configuration and database throughout.

Baseline: PR head e5d259d369fb279aa1ace62d5195472f813aa1b4; 85 focused tests pass.
The first baseline invocation had a missing temp parent; rerun after creating it passed.


Validation-discovered dependency: the full suite exposed two repeatable
startup-progress failures. A Windows venv redirector's Popen PID differs from
its base-Python worker PID. Prepare a separate local startup commit that
accepts only the same watched process or its OS-verified direct Python worker
with matching interpreter images. Keep unrelated/stale writers rejected.
Verify steady start, stalled start, child exit and overall cap with real child
processes; retain user approval before any publication/deployment.
