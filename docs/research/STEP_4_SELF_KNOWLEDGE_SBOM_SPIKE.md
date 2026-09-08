# Step 4 — Self-Knowledge / SBOM Research Spike

## Status

**RESEARCH SPIKE. NOT PRODUCTION ARCHITECTURE APPROVAL.**

This spike tests the minimum trustworthy foundation JARVIS will later need to answer questions such as:

- what am I built from?;
- what capabilities are actually declared?;
- which implementation files and accepted decisions define a capability?;
- which installed Python packages support the current runtime?;
- what health/test evidence exists for a capability?;
- has an authoritative architecture/source file changed since a derived self-knowledge snapshot was produced?

It does **not** implement autonomous repair, self-modification, deployment, permission expansion, or an LLM-owned architecture model.

## Research performed 2026-09-05

### CycloneDX

Current stable CycloneDX BOM specification is `1.7`. CycloneDX 2.0 has been announced but is not yet the stable BOM specification at the time of this spike.

CycloneDX 1.7 can represent software components, services and dependency relationships and is suitable for the dependency-inventory portion of JARVIS self-knowledge.

Sources:

- https://cyclonedx.org/specification/overview/
- https://cyclonedx.org/docs/1.7/
- https://cyclonedx.org/news/

### `cyclonedx-bom`

The selected research tool is `cyclonedx-bom==7.3.1` / `cyclonedx-py`.

Reasons:

- maintained by the CycloneDX project;
- current release on 2026-09-05 is 7.3.1;
- Python environment mode inventories actually installed packages and dependency relationships;
- supports CycloneDX 1.7;
- supports a target Python interpreter, PEP 621 `pyproject.toml` metadata, JSON output, validation and reproducible output;
- the 7.3.1 PyPI wheel was uploaded using Trusted Publishing and includes provenance attestation;
- therefore JARVIS should use the mature generator rather than create a custom Python dependency/SBOM parser.

Sources:

- https://cyclonedx-bom-tool.readthedocs.io/en/latest/usage.html
- https://pypi.org/project/cyclonedx-bom/7.3.1/

## Why SBOM is necessary but insufficient

A dependency inventory can answer questions such as:

```text
jarvis
  -> livekit-agents
  -> opencv-python
  -> cryptography
  -> ...
```

It cannot reliably answer product-semantic questions such as:

```text
What does voice.conversation mean inside JARVIS?
Which accepted architecture decision defines it?
Which module is its implementation owner?
What health test demonstrates it?
Does it grant authority?
Is it accepted production architecture or shadow evidence only?
```

Encoding those meanings only as arbitrary SBOM custom properties would also make an external supply-chain format the owner of JARVIS product semantics.

Therefore the leading Step-4 foundation is a **hybrid**:

```text
CycloneDX 1.7 SBOM
    = generated dependency evidence

JARVIS Capability Registry
    = JARVIS-owned declarative capability semantics

Accepted repo architecture / ADR / policy / code / tests
    = authoritative declared sources

Current runtime/configuration
    = authoritative source for current configured values

Operational memory
    = evidence-backed learned observations/history
```

No one of these is allowed to impersonate the others.

## Capability Registry research contract

The fixture in this spike is intentionally small and describes only capabilities already accepted or explicitly retained as shadow evidence by the current architecture.

A capability declaration contains research fields such as:

- stable capability ID;
- lifecycle (`accepted` or `shadow`);
- purpose;
- implementation file references;
- accepted architecture/ADR/policy references;
- expected base runtime packages;
- optional dependency group references;
- capability dependencies;
- structured health-test/entrypoint references;
- authority effect (`none`, `evidence`, or `governed_execution`);
- known limitations.

The registry does **not** contain:

- current API keys or environment secret values;
- copied `%LOCALAPPDATA%\\JARVIS\\machine.json` values;
- free-form shell commands;
- executable recovery instructions;
- an LLM-generated architecture summary treated as truth.

This boundary is intentional. A future diagnostic executor may resolve a structured health-test ID through governed code, but free-form executable text must not become trusted self-knowledge simply because it appeared in a registry or model response.

## Source authority

This spike follows the Step-4 declared-versus-learned requirement.

For current configuration facts:

```text
current runtime/configuration
  > cached observation
  > durable historical memory
  > model inference
```

For architecture and capability facts:

```text
accepted repository architecture / ADR / policy / declared capability
  > generated summary or SBOM evidence
  > learned inference
```

For historical incidents/outcomes:

```text
verified incident record + referenced evidence
  > reflection summary
  > inferred pattern
```

Generated SBOM data is therefore useful evidence, not a replacement for accepted architecture.

## Drift detection approach

The derived self-knowledge snapshot does not copy the content of architecture documents into durable memory.

Instead it records SHA-256 fingerprints for the authoritative repository files referenced by each capability.

Example concept:

```text
docs/CURRENT_ARCHITECTURE.md
  -> sha256: ...

src/jarvis/voice/production_runtime.py
  -> sha256: ...
```

A later diagnostics/self-knowledge consumer can compare the stored fingerprint with the current authoritative source and recognize that the derived snapshot is stale.

This is a foundation for architecture/documentation drift detection; it is not automatic reconciliation or deployment.

## Spike harness

Research files:

- `tools/research/requirements-step4-self-knowledge.txt`
- `tools/research/step4_capability_registry_fixture.json`
- `tools/research/step4_self_knowledge_probe.py`
- `.github/workflows/step4-self-knowledge-sbom.yml`

The CI spike deliberately uses two isolated Python environments:

1. **target environment** — installs JARVIS base runtime dependencies;
2. **tool environment** — installs `cyclonedx-bom==7.3.1`.

This prevents the SBOM generator itself from contaminating the target JARVIS dependency inventory.

The generator runs approximately as:

```text
cyclonedx-py environment
  --spec-version 1.7
  --output-format JSON
  --output-reproducible
  --pyproject pyproject.toml
  --mc-type application
  <target-python>
```

The standard-library JARVIS research probe then validates and joins the SBOM with the registry.

## Assertions

The spike must fail closed unless all of the following hold:

- BOM format is CycloneDX;
- BOM spec is exactly 1.7;
- SBOM root component name/version match JARVIS `pyproject.toml`;
- registry remains explicitly `research-only`;
- capability IDs are unique and stable dot IDs;
- lifecycle and authority-effect vocabulary are known;
- declared capability dependencies all exist;
- capability dependency graph is acyclic;
- implementation, source and test references exist under the repository root;
- health entrypoint references exist in `project.scripts`;
- referenced optional dependency groups exist in `pyproject.toml`;
- base runtime package references appear in the generated target-environment SBOM;
- registry contains no raw command/shell/script or secret/token/password fields;
- authoritative source SHA-256 fingerprints can be generated.

## Expected derived snapshot

The snapshot should contain only enough structured evidence to support future safe self-knowledge:

```text
project identity + git SHA
CycloneDX version / inventory counts
capability declarations
resolved installed package versions
optional dependency declarations
capability dependency relationships
structured health references
authority effect
known limitations
path + SHA-256 authoritative-source fingerprints
validation checks / errors
```

It must explicitly state that it is derived evidence and cannot outrank current runtime/configuration or accepted repository architecture.

## Decision hypothesis

If the spike passes, the leading Step-4 self-knowledge foundation is:

**KEEP `cyclonedx-bom` + CycloneDX 1.7 for generated dependency inventory, and KEEP a small JARVIS-owned declarative capability registry for product semantics.**

Do not create a custom SBOM format or custom Python package dependency scanner.

Do not turn the capability registry into a second copy of the architecture documentation. Use stable IDs and references to authoritative sources, plus fingerprints for drift detection.

Do not put learned operational conclusions directly into the declared capability registry. Learned observations belong in provenance-rich incident/episodic memory and may later be compared with declared truth.

## What this enables later

This foundation can later support a governed flow such as:

```text
capability failure observed
      |
      v
resolve capability ID
      |
      v
inspect declared implementation + dependencies + health refs
      |
      v
consult current runtime/configuration
      |
      v
consult verified incident/outcome memory
      |
      v
form diagnosis/research requirement
```

Actual diagnosis, automated repair, technology replacement, code modification, deployment and rollback remain later governed capabilities and are **not** part of Step 4.
