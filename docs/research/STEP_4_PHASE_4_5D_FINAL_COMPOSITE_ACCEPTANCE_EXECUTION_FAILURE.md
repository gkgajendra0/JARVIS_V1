# Step 4 Phase 4.5D — Final Composite Acceptance Execution Failure

Date: 2026-09-06

Status: EXECUTION_FAILURE_QUOTA — NO MODEL-QUALITY DECISION

## Frozen acceptance identity

Owner-run repository SHA:

`6cba430ca9d8ea8c95c542c0664e64bd9cffbd21`

Frozen corpus SHA-256:

`69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf`

Frozen corpus shape:

- 55 synthetic documents;
- 255 total queries;
- 90 release targets;
- 165 abstain targets.

Owner environment preflight passed unchanged:

- Torch `2.13.0+cu132`;
- Torchvision `0.28.0+cu132`;
- Transformers `5.16.1`;
- CUDA available;
- NVIDIA GeForce RTX 5060 Ti;
- `GOOGLE_API_KEY` available;
- fresh acceptance artifact absent before execution.

## What happened

The one-shot final composite acceptance began successfully and evaluated cases `v4_r0001` through `v4_r0031`.

Before case 32 could complete, the Gemini provider returned HTTP `429` / `too_many_requests` for `gemini-3.5-flash-lite`.

The returned provider error identified:

- quota metric: `generativelanguage.googleapis.com/generate_content_free_tier_requests`;
- quota limit: `500`;
- model: `gemini-3.5-flash-lite`;
- provider retry hint: approximately `54.3s`.

The harness exhausted its existing bounded retry policy and terminated with an exception.

No line beginning `Wrote UTF-8 result:` was produced. Therefore `.step4-phase45d-final-composite-acceptance.json` was not completed and there is no acceptance summary or decision artifact from this execution.

## Interpretation

This run is **not** `FAIL_ACCEPTANCE` and is **not** evidence that the selected composite memory architecture failed.

The frozen method explicitly states:

> provider quota/transport failure before a complete artifact → execution failure, not model-quality evidence; preserve the frozen corpus and architecture rather than changing them opportunistically.

Only a complete final artifact may be evaluated against the frozen release/precision/security gates.

The first 31 printed case dispositions are partial transport-era observations only. They must not be used to tune the corpus, prompt, model, local answer-type guard, thresholds, gates, or architecture.

## Rate-limit research

Google documents that Gemini API limits are project-wide and can be enforced by requests per minute (RPM), tokens per minute (TPM), and requests per day (RPD). Exceeding any active limit can return a rate-limit error. Google also documents that RPD limits reset at midnight Pacific time and that active model/project limits should be checked in AI Studio.

Source:

- https://ai.google.dev/gemini-api/docs/rate-limits

The returned error specifically names the free-tier request quota and limit `500`. This is separate from the harness pacing setting `--gemini-rpm 12`; lowering the harness RPM does not increase a fully exhausted project request quota.

## Frozen continuation decision

Preserve unchanged:

- corpus and corpus SHA;
- `gemini-3.5-flash-lite` planner adapter;
- one-query-per-request shape;
- structured query-planner prompt/schema;
- local multilingual answer-type guard model/revision;
- deterministic grounding/lifecycle/authority/sensitivity checks;
- exact canonical facet lookup;
- all acceptance gates;
- Phase 4.5E remains blocked.

Do **not** create a new corpus, tune against the 31 partial outputs, change models, change prompts, weaken gates, or classify this event as a semantic failure.

## Next owner action

Run the exact same frozen acceptance again only after sufficient Gemini project quota is available, either after the relevant free-tier quota resets or after the same project is moved to an adequate paid usage tier.

Before rerun:

1. pull the clean exact owner-run candidate SHA selected after this incident is documented;
2. verify the existing final artifact is still absent;
3. verify the frozen corpus SHA and shape are unchanged;
4. verify the same Torch/Torchvision/Transformers/CUDA environment;
5. execute the same acceptance harness with `--device cuda --gemini-rpm 12`.

A later complete `PASS_ACCEPTANCE` or `FAIL_ACCEPTANCE` artifact will be the first model-quality decision for this frozen final corpus.
