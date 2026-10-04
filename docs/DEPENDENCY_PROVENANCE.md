# Third-Party Dependency Provenance

This ledger records durable provenance for third-party dependencies introduced by governed autonomous engineering. It is evidence for the repository Dependency and Supply-Chain Gate; it is not a vulnerability guarantee.

## rfc8785 0.1.4

- Package identity: `rfc8785`
- Resolved version: `0.1.4`
- Registry: PyPI
- Source repository: `trailofbits/rfc8785.py`
- Maintainer/owner shown by the registry at review time: Trail of Bits
- License: Apache-2.0
- Python requirement: Python >= 3.8
- Runtime dependency graph: upstream project declares no runtime dependencies
- JARVIS owner/change: Phase 2B — EngineeringKnowledge registry and versioned facets
- Purpose: standards-conformant RFC 8785 / JSON Canonicalization Scheme serialization before SHA-256 schema/payload integrity digests
- JARVIS usage boundary: wrapped only by `jarvis.engineering_knowledge.canonical`; callers do not depend directly on the third-party API
- Network/authority effect: none at runtime; canonicalization is local and side-effect free
- Native/executable payload: pure Python package; no native extension is required by this dependency
- Acquisition: normal project dependency resolution from PyPI through the existing CI/install path; no hidden shell/package-install capability was added to JARVIS
- Reproducibility: exact version is pinned in `pyproject.toml`

### Published artifact digests reviewed 2026-09-24

PyPI published the following SHA-256 digests for version 0.1.4:

- source distribution `rfc8785-0.1.4.tar.gz`:
  `e545841329fe0eee4f6a3b44e7034343100c12b4ec566dc06ca9735681deb4da`
- wheel `rfc8785-0.1.4-py3-none-any.whl`:
  `520d690b448ecf0703691c76e1a34a24ddcd4fc5bc41d589cb7c58ec651bcd48`

The repository currently does not use a lockfile with artifact-hash enforcement, so these digests are provenance evidence rather than an installation-time hash gate. A future DependencyBroker/staged artifact cache should enforce acquired-artifact hashes directly.

### Security/reliability review

- The implementation is intentionally narrow: pure-Python RFC 8785 canonicalization with no runtime dependencies.
- The upstream repository publishes a security policy.
- No published GitHub security advisories were visible for the repository at the 2026-09-24 review.
- Absence of a published advisory is not proof of absence of defects.
- The package's latest PyPI release is from 2024; JARVIS therefore isolates it behind a small replaceable wrapper and verifies the required RFC behavior with repository tests rather than granting it broader responsibility.
- Phase 2B tests cover deterministic digest stability, payload sensitivity, duplicate-key rejection, UTF-16 property ordering behavior and fail-closed integrity handling.

### Rollback

Removal is bounded: replace the wrapper implementation or dependency, preserve the declared canonicalization identifier `rfc8785` only if byte-for-byte compatibility is proven, rerun EngineeringKnowledge integrity tests, and migrate only if canonical bytes would change.


## LLMLingua / LLMLingua-2 bounded prompt compression — 2026-10-04

- Library identity: `microsoft/LLMLingua`
- Library source repository: `microsoft/LLMLingua`
- Reviewed source revision: `5a4c78ae18ab17a98cf997e8259354e546081d64`
- Acquisition: optional `context-compression` project extra from the exact Git revision;
  it is not part of the base JARVIS install
- Upstream license: MIT
- Compressor model identity:
  `microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank`
- Reviewed model revision: `5f0c82792b7ea14c6484e015b6a072009496b7f2`
- Model license: Apache-2.0
- Published model size at review: approximately 713 MB total; `model.safetensors`
  approximately 709 MB
- Published `model.safetensors` SHA-256 at review:
  `22b9ecde52fec5c97e8c54a293be768727df95a81c6c8dccb03f262a50c58324`
- JARVIS owner/change: C6 retrieval/context optimization on PR #252
- Purpose: local, pre-provider compression of long natural-language research/evidence
  prose so full structured Work context can consume fewer cloud-model input tokens
- JARVIS usage boundary: isolated behind
  `jarvis.work.prompt_compression.LLMLingua2WorkPayloadCompressor`; canonical WorkStore
  state and decision output schemas do not depend on the third-party API
- Authority effect: none; compression cannot add actions, permissions or Authority
- Network effect: model/library acquisition may require network access; inference is
  local after artifacts are present
- Code execution boundary: `trust_remote_code=False` is forced for the reviewed model
- Default runtime state: prompt compression `off`; C6 context remains `shadow`
- Failure behavior: compressor initialization/execution/validation failures retain the
  exact legacy provider payload; they do not widen provider fallback or permissions

### Dependency graph and compatibility boundary

The upstream project declares `transformers>=4.26.0`, `accelerate`, `torch`,
`tiktoken`, `nltk` and `numpy`. JARVIS keeps LLMLingua optional and lazy-loaded so
ordinary runtime and CI do not gain a mandatory ML dependency.

The owner-machine acceptance must prove compatibility with the installed JARVIS
Torch/Transformers environment before any compression mode is promoted. This is
particularly important because upstream issue history contains Windows/CPU and newer
Transformers compatibility reports. JARVIS therefore does not treat package import or
model download as acceptance evidence.

### Security/reliability review

- Only selected long natural-language fields are eligible for compression in the first
  admission. Owner request, action catalog, parameter schemas, source/code `text`,
  paths, IDs, digests, evidence references, source identity/version and JSON structure
  remain exact.
- The wrapper validates object/list structure and every non-compressible leaf after
  compression.
- Empty/malformed compressor output is rejected.
- A replacement that is not smaller is discarded for that field.
- The first production-eligible task class is RESEARCH only; development/code payloads
  are deliberately outside this admission.
- The owner benchmark compares legacy and compressed decisions using the existing strict
  action/parameter/completion/owner equivalence gate and checks actual provider input
  tokens, not only character estimates.
- The benchmark executes no Work action, cannot mutate production routing or the shared
  provider circuit, and cannot automatically promote C6 APPLY.

### Reproducibility and rollback

The library is bound to the exact Git commit above and the model load is bound to the
reviewed Hugging Face revision. The owner acceptance report records both identities.

Rollback is bounded: set `JARVIS_WORK_PROMPT_COMPRESSION_MODE=off` (the default), remove
the optional extra, and JARVIS sends the existing uncompressed provider payload. No
canonical Work data migration is required because compressed text is never canonical or
persisted as replacement Work history.
