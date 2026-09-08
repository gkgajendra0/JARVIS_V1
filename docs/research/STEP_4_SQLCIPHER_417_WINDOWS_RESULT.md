# Step 4 — SQLCipher 4.17 Windows Packaging Result

## Status

**CURRENT-ENGINE BUILD / SECURITY GATE: PASS.**

**LEADING PACKAGING DIRECTION: REPRODUCIBLE, HASH-PINNED JARVIS BUILD OF SQLCIPHER 4.17.0 BEHIND THE MAINTAINED `sqlcipher3` PYTHON BINDING.**

This result is separate from the earlier owner-machine proof of the SQLCipher + Windows DPAPI architecture. The earlier real JARVIS PC run proved the encryption design with the published `sqlcipher3==0.6.2` wheel; this CI run proves that JARVIS can instead reproducibly build and verify the current SQLCipher 4.17.0 engine rather than freeze the older bundled 4.12.0 engine.

## Reproducible inputs

Pinned inputs used by the research build:

- SQLCipher upstream release: `4.17.0 community`;
- SQLCipher source commit: `810db22f575ee7cf94ea96a3e91622b5fcece3dc`;
- SQLCipher SQLite baseline: `3.53.3`;
- `sqlcipher3` wrapper source commit: `14fc263` (`0.6.2` wrapper surface);
- Python ABI: CPython 3.11 x86-64 Windows;
- OpenSSL provider reported at runtime: `OpenSSL 3.6.0 1 Oct 2025`;
- custom integrator version: `0.6.2+jarvis.sqlcipher4170`.

The build generated the SQLCipher amalgamation from the pinned 4.17.0 source, inserted it behind the pinned Python binding, and produced a Windows wheel in GitHub Actions rather than requiring a manually configured compiler toolchain on the owner PC.

## Built wheel

First successful substantive build produced:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Measured wheel SHA-256:

`a2eb76cdb067df0d1354b29a8b2dca046b148482b11659e6c4df40c40031489b`

The wheel digest identifies that exact CI output. A future production dependency must still be tied to a retained artifact or rebuilt under the pinned build recipe and re-verified; the digest must not be assumed for a separately rebuilt binary.

## Substantive CI result

GitHub Actions run `33945233778`, job `101250000638` successfully completed all security/build gates before the final artifact-upload plumbing step:

- checkout: PASS;
- Python 3.11 setup: PASS;
- MSVC environment: PASS;
- pinned SQLCipher 4.17.0 wheel build: PASS;
- isolated verification environment: PASS;
- full synthetic SQLCipher + DPAPI bake-off: PASS;
- current-engine version gate: PASS;
- wheel digest recording: PASS.

That run was marked failed only because `actions/upload-artifact` excludes dot-directories by default and the research wheelhouse used a dot-prefixed directory. The workflow was subsequently corrected with `include-hidden-files: true`; that upload concern is evidence-preservation plumbing, not a failure of the build or security assertions.

## Runtime verification

The built wheel reported:

- package version: `0.6.2+jarvis.sqlcipher4170`;
- SQLCipher: `4.17.0 community`;
- SQLite: `3.53.3`;
- provider: `openssl`;
- OpenSSL: `3.6.0 1 Oct 2025`;
- FTS5: compiled;
- `TEMP_STORE=2`;
- WAL: works;
- `secure_delete`: works.

The explicit current-engine gate printed:

```text
CURRENT_ENGINE_GATE=PASS
SQLCIPHER= 4.17.0 community
SQLITE= 3.53.3
PROVIDER= openssl
```

## Security / functional assertions — all PASS

The same synthetic harness used for the earlier owner-machine SQLCipher decision passed all core assertions with the 4.17.0 build:

- SQLCipher present and active;
- random 256-bit raw-key DB creation/read;
- Windows DPAPI seal/unseal round trip;
- DPAPI wrong-purpose rejection;
- raw DB key absent from the DPAPI blob;
- FTS5 English search;
- FTS5 Hindi search;
- canonical write/read;
- memory temp store;
- secure delete;
- WAL;
- clean cipher integrity before mutation;
- no synthetic plaintext/key leakage in DB/WAL/SHM/key artifacts;
- standard SQLite without key blocked;
- wrong SQLCipher key blocked;
- same-user/same-machine backup and restore;
- FTS after restore;
- deliberate ciphertext corruption detected;
- explicit forget removes canonical row;
- explicit forget removes FTS result;
- clean cipher integrity after forget;
- no final plaintext/key leakage.

Overall harness status: `PASS` with zero failed core checks.

## Important improvement over the older published wheel

The earlier real-machine test of the published `sqlcipher3==0.6.2` Windows wheel bundled SQLCipher `4.12.0` and the optional:

`PRAGMA cipher_memory_security = ON`

probe crashed with Windows `STATUS_STACK_OVERFLOW`.

With the pinned SQLCipher 4.17.0 JARVIS build, the isolated enhanced-memory-security probe **passed**:

```text
passed = true
returncode = 0
stdout = PROBE_OK=1
```

This removes the main runtime-hardening concern observed in the older prebuilt wheel and is additional evidence for using the current pinned engine rather than freezing the published 4.12.0 binary.

## Technology disposition

### KEEP

- SQLCipher as the whole-database encryption family;
- SQLCipher `4.17.0` as the current pinned engine for the Step-4 production design unless a newer version is deliberately re-researched before implementation;
- the maintained `sqlcipher3` Python DB-API binding surface;
- a reproducible JARVIS-owned Windows build recipe with exact source commits;
- a JARVIS-specific local package version so the custom build cannot be confused with the published wheel;
- wheel/build manifest SHA-256 recording;
- full synthetic security verification in a clean environment before accepting a built artifact;
- Windows DPAPI for the local random DB key;
- FTS5, WAL, `temp_store=MEMORY`, and secure-delete behavior proven by the harness.

### DO NOT USE AS PRODUCTION DEFAULT

- the older published `sqlcipher3==0.6.2` Windows binary merely because it was easy to install;
- an unpinned `master`/latest SQLCipher source build;
- an unverified locally compiled database binary;
- a plaintext SQLCipher key or passphrase file;
- a custom encryption scheme invented inside JARVIS.

## Commercial Zetetic package versus JARVIS self-build

Zetetic's first-party prebuilt Windows packages remain a valid commercial/support option. The current evidence does not demonstrate a technical need to require that paid distribution for this personal/local JARVIS deployment because:

1. the Community Edition family already passed the real owner-machine encryption design test;
2. the pinned current 4.17.0 source build is reproducible in CI;
3. the generated wheel passes the complete security/functional harness;
4. the newer build also passes the enhanced-memory-security probe that failed with the older published wheel.

Therefore the **leading production route is the pinned reproducible JARVIS self-build**, while keeping the first-party commercial package as an optional future support/provenance upgrade rather than an architectural dependency.

## Owner-machine boundary

This 4.17.0 build/security run executed on a GitHub-hosted Windows runner, not yet on the owner's exact JARVIS PC.

The encryption architecture itself has already been proven on the real owner PC using the older wheel. Before final production acceptance of the exact custom 4.17.0 binary, the retained/hash-pinned artifact should be installed in an isolated owner-machine environment and the same synthetic harness rerun once. That is an implementation/acceptance packaging check, not a reopening of the technology-selection research.

## Artifact-upload note

The first substantive run failed only at final evidence upload because the output directory was dot-prefixed and `actions/upload-artifact` defaulted to excluding hidden files/directories. The workflow was corrected in commit `f2d015a2e52344cd686274e18c36134e8cb477c2` by enabling `include-hidden-files: true` for the explicitly scoped wheelhouse.

## Step-4 disposition

The SQLCipher technology and current-engine packaging questions are sufficiently answered for the final Step-4 technology decision:

```text
SQLite + FTS5 canonical memory
        |
        v
SQLCipher 4.17.0 Community Edition
pinned/reproducible JARVIS Windows build
        |
        v
random 32-byte raw DB key
        |
        v
Windows DPAPI user-scope + purpose binding
```

No further database-encryption technology search is required before the final architecture proposal.
