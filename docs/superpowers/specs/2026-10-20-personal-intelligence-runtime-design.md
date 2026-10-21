# Normal-runtime personal context

The owner requests a working feature in the normal `jarvis-voice` app, followed
by their own local conversational acceptance. Separate demos are not delivery.
This implements the already approved native read-only personal-context architecture.

## Behavior

`jarvis-voice --personal-context apply` activates automatic context tools inside
the existing production session. OFF is the default and explicit `--personal-context off`
disables this path. The explicit APPLY launch enables canonical memory and disables
transcript logging for that process; it changes no persisted settings. Persisted
`JARVIS_PERSONAL_CONTEXT_MODE` also supports off/apply with normal machine precedence.
No separate database, provider, dependency, automatic capture or fine-tuning.

Ordinary advice automatically invokes a two-stage native tool path: obtain an
authorized catalog of eligible facet names, then propose at most four catalog
indices and read their current canonical facts. The actual voice model chooses
relevance; no unavailable second HTTP model is on the critical path. Empty memory,
denied authorization and unavailable storage have distinct truthful outcomes.
Tool output is data, never instructions or capability authority.

## Exact owner consent and provider history

Existing speaker/active-speaker scores remain SHADOW. The first release obtains
fresh Windows Hello consent bound to the exact canonical accepted request; it
does not claim biometric speaker recognition. Existing Authority/OPA/audit/permit
and Windows continuity checks remain mandatory. Cached T2 approval cannot replace
this exact request consent. Facet names themselves are not sent before consent.

Since this pinned Gemini adapter cannot remove history, an owner-confirmed
personal answer is single-use: after that answer completes, the normal app returns
to local wake mode and closes that provider conversation. Further questions use a
fresh wake/session. New speech, a new accepted turn, OFF, lock/session loss,
mutation, expiry or close invalidates pending work and private output. A turn-bound
audio wrapper checks authorization/continuity before forwarding private audio.
This conservative first release prevents an unverified follow-up from accessing
earlier private context; seamless verified-speaker follow-ups remain a later gate.

Explicit remember/correct/forget retain existing grounded-intent validation. In
APPLY mode they additionally require exact owner consent and reset the provider
conversation after the acknowledgement. No successful mutation may leave old
personal context available for a subsequent answer. No memory values are logged.

## Release boundaries

The normal runtime must actually construct the tools and output guard; tests must
exercise that composition, not only standalone helpers. OFF startup must preserve
existing behavior. All asynchronous operations bind session ID, turn ID, canonical
generation and local activity epoch, and revalidate after waits and before release.
Catalog IDs are opaque per-turn tokens; stale IDs, fabricated/duplicate indices,
ambiguous/currently ineligible sources, LOCAL_ONLY/PRIVATE/SECRET and inferred facts
are excluded. Source/currentness checks occur again at consumption.

Canonical read-only context limits: 128 catalog facets, 4 facts, 1800 UTF-8 value
bytes, 8000 question bytes; history/third-party/general knowledge must not be
represented as known owner facts. Untrusted tool input cannot grant authorization.
Authorization wait is bounded by the existing 60-second Hello helper and 120-second
proposal; late/cancelled results cannot reach the provider. Only one outstanding
authorization per turn; inactivity timers pause while owner consent is pending.

Acceptance: normal production construction exposes automatic recall in APPLY,
retrieves actual temporary canonical fixtures for ordinary English/Hindi/Hinglish
questions, survives restart, respects correction/forget and guest denial, and
closes the populated provider session after its one authorized answer. The owner
runs the full app after software checks. No protected-main merge, user memory read,
microphone test or production launch is performed by the implementer.
