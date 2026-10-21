# Personal memory: bounded owner acceptance — 21 October 2026

This release record accompanies PR #294 and its reviewed dependencies #292/#293.
It becomes protected-main release documentation when that authorized PR merges.
The owner authorized the stack merge, conditional on successful checks, after
confirming the normal-app spoken test. The PRs record actual merge status.

## Accepted behavior and evidence

The owner ran the complete configured Windows app from the Desktop checkout with
`jarvis-voice --personal-context apply`, using an existing saved diet preference.
The sequence was recall, natural correction to vegan, verification, actual process
restart, verification after restart, restoration to vegetarian, final verification.
The owner confirmed correct spoken answers at every step:
“yes spoken confirmation tha at every step”.

The supplied log independently contains eight wake conversations, five one-fact
context selections, two concrete-consented correction commits, an actual
shutdown/relaunch and one denied catalog request with no read/write. The first
correction rejected one ungrounded proposal, then retried and committed in the
same request. Spoken-value correctness is owner testimony, not inferred from
logs. No raw transcript logging was enabled for acceptance.

Accepted scope: saved-preference recall, natural existing-memory correction,
restart persistence and restoration in the opt-in normal app. Canonical memory,
existing authority and audio guards remain responsible for the flow.

Runtime head `f3c458dd38afa91f28946ec2edc1f2649093bef2` passed 2,636 local tests
(8 skipped) and all six Code Quality jobs in
[run 39558981208](https://github.com/gkgajendra0/JARVIS_V1/actions/runs/39558981208).
This subsequent update changes documentation only. Any newer publication head
must pass applicable checks. Reviews and reproduced fixes are recorded in the
[repair report](../research/MEMORY_INTENT_REPAIR_2026-10-21.md).

## Boundaries

- APPLY is opt-in; OFF remains default. No saved machine setting changes.
- Reads require exact-request Hello. Existing-memory changes can need separate
  read-resolution and concrete-write approvals. Wake again after each answer.
- Speaker scores remain SHADOW. Automatic durable learning remains disabled.
- No new dependency, schema, model/provider or parallel memory store.
- Broader advice quality, every language, owner-machine deletion/negation,
  held-out relevance, billed cost and seamless speaker follow-ups remain open.
- Audio timeout/pause warnings appeared while execution continued; their audible
  impact was not separately qualified and is not labeled harmless.

CAP-053 is PARTIAL, not DONE. This is bounded human evidence toward personal
intelligence, not acceptance of the whole assistant goal.

Run `jarvis-voice --personal-context apply`; disable with `--personal-context off`.
The agent did not open the app, microphone, camera or owner DB during promotion.
