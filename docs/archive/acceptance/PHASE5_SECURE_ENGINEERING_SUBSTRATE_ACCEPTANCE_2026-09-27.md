# Phase 5 Secure Autonomous Engineering Substrate — Owner-Machine Acceptance

## Status

**PASS — OWNER-MACHINE ACCEPTED 2026-09-27**

Acceptance-tested implementation head:

`b8918d1ba6985b2d5130e10e64a633c77565e2f0`

PR:

`#133 — Phase 5J: substrate evaluation and owner acceptance harness`

Owner-machine evidence file:

`C:\Users\gkgaj\AppData\Local\Temp\jarvis_phase5_final_bb23898c0e1e4585a6df6d5fa6bf95ea\phase5-owner-acceptance-b8918d1.json`

Evidence digest:

`a279b3e387c78cfa402a40c2074b7aed56db479f4cc7f07f65e5b245444d4b3e`

## Final disposition

Phase 5 is accepted for its defined scope.

The final owner-machine run proved the integrated secure engineering substrate on the real Windows owner machine, including reviewed uv trust, dependency resolution, artifact admission, provenance/attestation verification, network-disabled offline recreation, manifest binding, disposable secret acceptance, bounded mDNS discovery, and durable restart lineage.

The acceptance harness returned `status=PASS` for the exact implementation head above.

## Accepted security and governance properties

The accepted Phase 5 path preserves:

- exact reviewed dependency tooling and binary provenance;
- registered dependency sources and wheel-only offline verification;
- admitted artifact integrity and digest binding;
- pinned verification container image;
- network-disabled candidate recreation;
- read-only worktree/artifact mounts;
- secret scope controls and disposable DPAPI acceptance;
- bounded read-only discovery;
- capability manifest digest binding;
- restart-safe WorkItem lineage;
- protected-main governance and existing Authority boundaries.

Phase 5 does not grant autonomous merge/deploy authority, bypass Windows Hello, broaden secret scope, allow arbitrary network discovery, permit source builds during offline verification, or fall back to unsandboxed execution.

## Owner-machine defects discovered and corrected during acceptance

The owner-machine run exposed real Windows/Linux integration defects that automated Ubuntu CI did not originally reveal.

### 1. uv cache on Windows bind mount

The verification profile originally placed the Linux uv cache under `/candidate/.uv-cache`, where `/candidate` was backed by a Windows host path.

Linux filesystem objects created there could not always be traversed or cleaned up by Windows, producing `WinError 1920`.

The uv cache was moved to container-local Linux tmpfs.

### 2. Host-dependent pytest target validation

Sandbox pytest-target validation used `pathlib.PurePath`, whose semantics depend on the host operating system.

A POSIX absolute path such as `/absolute/test.py` was therefore rejected on Linux but not consistently on Windows.

Validation now explicitly checks both POSIX and Windows path semantics, with Windows CI regression coverage.

### 3. Linux virtualenv on Windows bind mount

After moving the uv cache, the Linux virtualenv itself still lived on the Windows-backed `/candidate` mount. Linux uv created filesystem constructs such as the `lib64` symlink, which Windows could not safely traverse during cleanup.

The final verification design keeps the complete candidate environment inside Linux tmpfs and performs venv creation, offline sync, package check, and inventory freeze inside one network-disabled container. No Linux virtualenv is persisted onto NTFS.

### 4. Missing local zeroconf dependency

The owner acceptance correctly failed closed when the declared `zeroconf==0.151.3` runtime dependency was absent from the existing owner-machine virtual environment.

The dependency was installed and import verified before rerunning acceptance. No discovery policy was weakened.

### 5. SQLite connection lifecycle on Windows

The restart-lineage acceptance exposed that `SQLiteWorkStore` used the sqlite connection context manager as though it closed the connection. Python's sqlite context manager commits or rolls back but does not close the handle.

Linux tolerated deletion of the open temporary SQLite file; Windows correctly returned `WinError 32`.

The WorkStore connection lifecycle now always commits or rolls back and explicitly closes every connection. Regression coverage verifies that all opened handles are released.

## Final owner-machine result

The final run reported:

- status: `PASS`;
- tested commit: `b8918d1ba6985b2d5130e10e64a633c77565e2f0`;
- evidence digest: `a279b3e387c78cfa402a40c2074b7aed56db479f4cc7f07f65e5b245444d4b3e`.

This is the accepted implementation boundary. Later documentation/lint-only closure commits do not change the accepted runtime behavior.

## Promotion decision

Phase 5 Secure Autonomous Engineering Substrate is **DONE / OWNER-MACHINE ACCEPTED 2026-09-27**.

PR #133 is authorized for protected-main merge once the final documentation/lint-only head is CI-green and comparison confirms that no additional unaccepted runtime change was introduced.
