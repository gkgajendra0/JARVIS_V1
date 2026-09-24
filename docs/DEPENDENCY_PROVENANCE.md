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
