# Step 4 — Self-Knowledge / SBOM Windows Result

## Status

**RESEARCH SPIKE: PASS.**

**TECHNOLOGY DIRECTION: KEEP CYCLONEDX 1.7 + `cyclonedx-bom` FOR GENERATED DEPENDENCY INVENTORY, AND KEEP A JARVIS-OWNED DECLARATIVE CAPABILITY REGISTRY FOR PRODUCT SEMANTICS.**

This result closes the Step-4 self-knowledge/SBOM research gate. It does not approve autonomous repair, self-modification, deployment, or authority expansion.

## Run

Successful GitHub Actions run:

- workflow: `Step 4 self-knowledge SBOM research`;
- run ID: `33945807545`;
- commit: `0275d179269087a00cd1d2cc3dad100f6ff2e3b9`;
- runner: Windows;
- Python: 3.11;
- result: `success`.

The first run had already passed every semantic/self-knowledge assertion but failed only because `actions/upload-artifact` excludes dot-directories by default. The workflow was corrected to explicitly include the research-only hidden output directory. The second run then passed every step, including evidence upload.

## Measured result

The validated research snapshot reported:

- `SELF_KNOWLEDGE_STATUS=PASS`;
- CycloneDX specification: `1.7`;
- installed target-environment SBOM components: `92`;
- JARVIS capability declarations in the fixture: `8`;
- authoritative repository source fingerprints: `45`;
- failed validation checks: `[]`.

The target JARVIS environment also passed `pip check` before SBOM generation.

## What was proven

### 1. Mature SBOM generation works for JARVIS

`cyclonedx-bom==7.3.1` successfully generated a validated, reproducible CycloneDX 1.7 JSON SBOM from an isolated Windows/Python 3.11 JARVIS runtime environment.

The SBOM generator was installed in a separate tool environment, so the generator and its dependencies did not contaminate the target JARVIS runtime inventory.

### 2. SBOM + capability registry can be joined without creating a second architecture brain

The JARVIS research probe successfully joined generated dependency evidence with a JARVIS-owned declarative capability registry while preserving the source-of-truth boundary:

```text
current runtime/configuration
    = current configured truth

accepted repo architecture / ADR / policy / code / tests
    = declared architecture truth

JARVIS capability registry
    = stable capability semantics + references

CycloneDX SBOM
    = generated dependency evidence

verified operational/incident memory
    = learned historical evidence
```

Generated evidence and learned observations do not outrank the authoritative sources above them.

### 3. Capability declarations were mechanically validated

The spike validated:

- unique stable dot-form capability IDs;
- known lifecycle states (`accepted`, `shadow`);
- known authority-effect states (`none`, `evidence`, `governed_execution`);
- all declared capability dependencies resolve;
- capability dependency graph is acyclic;
- implementation/source/test references exist under the repository root;
- health entrypoint references exist in `project.scripts`;
- referenced optional dependency groups exist in `pyproject.toml`;
- base runtime packages named by capabilities exist in the generated SBOM;
- registry has no raw `command`, `shell`, `script`, secret/token/API-key/password fields.

### 4. Drift fingerprints work

The probe generated SHA-256 fingerprints for authoritative repository files referenced by the capability declarations.

This provides a safe primitive for later detecting that a derived self-knowledge snapshot has become stale after architecture/code/test changes, without copying full architecture documents into memory.

A fingerprint difference is evidence of drift only. It is not permission for JARVIS to rewrite code or documentation automatically.

## Capability fixture coverage

The research fixture intentionally represented only existing accepted/shadow Step-3 architecture:

- `startup.preflight` — accepted;
- `voice.conversation` — accepted;
- `voice.wake_detect` — accepted;
- `vision.track_person` — accepted;
- `identity.owner_visual_evidence` — accepted evidence;
- `authority.governed_execution` — accepted governed execution;
- `identity.speaker_shadow` — shadow evidence;
- `identity.active_speaker_shadow` — shadow evidence.

This fixture is not yet the final production capability registry. It proves the contract and validation pattern.

## Technology decision

### KEEP

- CycloneDX `1.7` as the current stable dependency inventory format for this Step-4 design;
- `cyclonedx-bom==7.3.1` / `cyclonedx-py` as the maintained Python SBOM generator;
- generation from the actually installed target Python environment;
- separate tool and target environments;
- a small JARVIS-owned declarative capability registry;
- structured health references rather than free-form executable commands;
- authoritative path + SHA-256 fingerprints for derived-snapshot drift detection;
- explicit lifecycle and authority-effect metadata;
- current runtime/configuration remaining authoritative for current values;
- learned observations stored separately with provenance and time.

### DO NOT BUILD

- a custom Python dependency scanner;
- a custom SBOM format;
- an LLM-generated list of capabilities treated as truth;
- a second self-knowledge database that silently duplicates or outranks accepted architecture;
- free-form shell commands inside trusted capability declarations;
- autonomous self-repair or self-modification as part of Step 4.

## Why not use the SBOM itself as the capability registry?

CycloneDX is excellent at inventorying components, dependencies, services and related supply-chain evidence. JARVIS capability semantics contain product-specific meaning such as:

- what the capability does;
- whether it is accepted or shadow;
- which accepted decision owns it;
- what health evidence exists;
- what authority effect it may have;
- which limitations are intentionally retained.

Keeping those semantics in a small JARVIS-owned declaration preserves architectural ownership while still using a standard tool for the part standards already solve well.

## Current-version note

At the time of this research (2026-09-05), CycloneDX 1.7 is the current stable BOM specification. CycloneDX 2.0 has been announced for later 2026 but is not treated as the stable dependency format for this Step-4 gate. The architecture should keep the SBOM adapter replaceable so a later standards upgrade does not change JARVIS capability semantics.

## Supply-chain note

`cyclonedx-bom==7.3.1` was released on 2026-07-23. Its PyPI wheel was uploaded using Trusted Publishing and includes provenance attestation. This materially improves the provenance of the selected research tooling compared with inventing or adopting an opaque dependency parser.

## Research artifacts

Repo:

- `docs/research/STEP_4_SELF_KNOWLEDGE_SBOM_SPIKE.md`;
- `tools/research/requirements-step4-self-knowledge.txt`;
- `tools/research/step4_capability_registry_fixture.json`;
- `tools/research/step4_self_knowledge_probe.py`;
- `.github/workflows/step4-self-knowledge-sbom.yml`.

GitHub Actions artifact from the successful run contains:

- generated CycloneDX 1.7 SBOM;
- derived self-knowledge snapshot.

The artifact is research evidence and is not a production runtime store.

## Step-4 disposition

The self-knowledge/SBOM technology question is now sufficiently answered for the final Step-4 technology decision and architecture proposal.

Remaining work is no longer to search for another self-knowledge framework. The next Step-4 research consolidation should combine:

- SQLite + FTS5 canonical memory;
- temporal/provenance lifecycle;
- selected hybrid retrieval/reranking;
- memory extraction provisional provider tie/evidence;
- SQLCipher + DPAPI encryption decision and current packaging result;
- this CycloneDX + JARVIS capability-registry decision;

into one final technology decision and human-reviewable architecture before any production Step-4 memory implementation begins.

## Sources

- CycloneDX specification overview: https://cyclonedx.org/specification/overview/
- CycloneDX 1.7 documentation: https://cyclonedx.org/docs/1.7/
- CycloneDX newsroom / 2.0 status: https://cyclonedx.org/news/
- CycloneDX Python usage: https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html
- `cyclonedx-bom` 7.3.1 release/provenance: https://pypi.org/project/cyclonedx-bom/7.3.1/
