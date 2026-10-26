# Controlled Gemini Live: contract and qualification record

23 October 2026. Offline implementation verified; no real provider/client call or activation. See [implementation, verification and remaining work](GEMINI_CONTROLLED_LIVE_IMPLEMENTATION_2026-10-23.md).

## Supported public mechanics

Installed google-genai2.22.0 AsyncLive.connect has one public connection context
and yields one AsyncSession; there is no reconnect loop in that implementation.
LiveKit1.8.3 public RealtimeSession exposes start_user_activity/commit_audio/
generate_reply; Agent public TurnHandlingOptions supports local VAD. The existing
bundled local Silero is reused. Server AAD is disabled and client activity signals
bound each user turn. Standard3.8 supports blocking functions and returns idle on
turnComplete; extended-thinking is excluded because its processing lifecycle
contains multiple utterances. [Capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities),
[Live thinking lifecycle](https://ai.google.dev/gemini-api/docs/live-api/thinking).

The exact model card gives131072input/65536output. No unverified alias/model
inherits these capacities. Full native capacity is reserved per priced modality;
a configured small reply limit is not used to under-reserve thought/audio costs.
[Model card](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live).

## Auxiliary billing is a real open production-qualification requirement

Google describes context re-billing per turn, proactive listening charges and
additional text-output transcription charges. Approximate25audio tokens/sec is
not a hard ceiling. Therefore model limits alone do not qualify paid audio with
ASR/listening enabled. [Billing guide](https://ai.google.dev/gemini-api/docs/live-api/best-practices).

The new contract deliberately requires an explicit model-bound, sourced/versioned
auxiliary envelope for listening, input transcription and output transcription,
plus a reviewed interpretation that transcription usage is included in response
text counts. No such production auxiliary envelope is asserted from the current
documentation inspection. Calling reviewed_live_contract with only the real model
name remains denied before any provider client construction. Test-supplied
synthetic envelopes verify software behavior only; they are not production proof.
A later real provider/usage/accounting qualification needs separate authorization;
it cannot be inferred from these tests or a billed-token counter.

This first task produces the explicit interface/proof gate consumed by admission
and transport work. It does not mean actual Paid Live has become available.
The default remains OFF and the previous real factory denial remains in place.

## Usage normalization

Public raw UsageMetadata carries per-generation prompt/response, thinking,
cache, tool-use and modality fields. Preserve missing values; reject inconsistent
sums, unsupported modalities and unpriced tool-use. Full cached input is charged
conservatively. Explicit thoughts are text output. Only the caller's qualified
auxiliary response-text interpretation permits complete settlement; the SDK type
alone provides no such assertion. [Wire usage reference](https://ai.google.dev/api/live#UsageMetadata).

Normalization is stateless; stable event/trigger identity, monotonic snapshot
handling and final settlement belong to the shared admission owner. No early
stream snapshot can release a full worst-case reservation as final usage.
Missing/ambiguous final data retains unknown exposure; overruns are recorded and
stop further admission rather than clipped to the reservation.

## First-task evidence

Observed RED: missing contract module at collection, as expected by the task.
Initial GREEN45 contract/pricing/provider-policy checks,10.41s. Additional real
public SDK UsageMetadata shape is verified in the final task receipt. No actual
API key, owner memory, microphone, billing account or external network was used.
