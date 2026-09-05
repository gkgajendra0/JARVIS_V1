# Step 4 — SQLCipher + Windows DPAPI real-machine result

## Status

**CORE SECURITY / FUNCTIONAL SPIKE: PASS.**

**SQLCIPHER FAMILY: KEEP. WINDOWS PREBUILT `sqlcipher3==0.6.2` WHEEL: DO NOT YET APPROVE AS THE PRODUCTION PACKAGE.**

This document records the measured owner-machine result from the synthetic Step-4 encryption harness on the real JARVIS Windows machine. It does not contain personal memory data or the raw database key.

## Environment measured

- Python wrapper: `sqlcipher3==0.6.2`
- bundled SQLCipher: `4.12.0 community`
- bundled SQLite: `3.51.1`
- crypto provider: `OpenSSL`
- provider version: `OpenSSL 3.6.0 1 Oct 2025`
- FTS5: compiled and working
- temp store compile option: `TEMP_STORE=2`
- runtime journal mode: `WAL`
- runtime secure delete: enabled
- SQLCipher enhanced all-SQLite-memory security default: disabled (`0`)

The exact CPython 3.11 Windows x86-64 wheel used in this spike was downloaded from PyPI and verified before installation against SHA-256:

`4ad7e4a32de907011ea22ac2012c9bca1bb414e2f599c56a55c8b0fe6445b932`

## Core checks — all PASS

The synthetic harness measured all of the following successfully:

- SQLCipher is present and reports an active cipher;
- random 256-bit raw-key database creation/read works;
- Windows DPAPI seal/unseal round trip works;
- DPAPI purpose binding rejects a wrong purpose;
- raw SQLCipher key bytes are not present in the DPAPI blob;
- FTS5 English query works inside the encrypted database;
- FTS5 Hindi query works inside the encrypted database;
- canonical writes/reads work;
- `temp_store=MEMORY` works;
- `secure_delete=ON` works;
- WAL mode works;
- `PRAGMA cipher_integrity_check` is clean before mutation;
- no synthetic plaintext marker or raw key was found in the database, live WAL, SHM or sealed-key artifact;
- standard Python `sqlite3` cannot open the encrypted database without the key;
- SQLCipher with a deliberately wrong key is rejected;
- no plaintext/key leakage was found after close;
- same-user/same-machine encrypted database + DPAPI key backup/restore works;
- FTS still works after restore;
- deliberately modified ciphertext is detected as database corruption;
- explicit forget removes the canonical row;
- explicit forget removes the FTS result;
- post-forget cipher integrity is clean;
- final encrypted artifacts contain none of the synthetic plaintext markers or raw key bytes.

Overall harness result: `PASS` with zero failed core checks.

The SQLCipher HMAC/page-decrypt errors printed during the run were expected negative-test evidence: one was produced by the deliberately wrong-key probe and one by the deliberately corrupted-ciphertext probe. They are not core failures.

## Enhanced memory-security child probe — FAIL / isolated packaging concern

The optional child-process probe that enables:

`PRAGMA cipher_memory_security = ON`

terminated with Windows return code:

`3221225725` / `0xC00000FD` (`STATUS_STACK_OVERFLOW`).

Earlier probing of the same wheel also emitted Windows `VirtualLock()` failures (`LastError=1453`) when enhanced memory security was enabled.

This failure does **not** invalidate the at-rest encryption result. SQLCipher documents that enhanced `cipher_memory_security` is disabled by default and extends sanitization/locking to all SQLite allocations, while SQLCipher always performs internal locking/sanitization for cryptographic allocations. The enhanced mode is therefore treated as an optional hardening feature and a package/runtime compatibility signal, not as a prerequisite for the core encrypted-memory-store decision.

## Current upstream comparison

The tested third-party wheel bundles SQLCipher `4.12.0` (December 2025). Current upstream SQLCipher is `4.17.0` (July 2026) with SQLite `3.53.3`, later maintenance fixes, thread-safety/error-handling improvements, and an upstream SQLite baseline that includes fixes for CVEs affecting earlier versions.

Therefore the JARVIS production dependency should not freeze the tested `4.12.0` bundled engine merely because its core bake-off passed.

## Technology disposition

### KEEP

- SQLCipher as the whole-database encryption family.
- SQLite/FTS5 as the canonical/lexical memory foundation.
- a random 32-byte raw SQLCipher database key.
- Windows DPAPI, user scope + purpose-bound entropy, for protecting the local database key.
- same-machine backup/restore as a supported local recovery path.

### DO NOT YET APPROVE

The exact third-party prebuilt `sqlcipher3==0.6.2` Windows wheel as the final production package.

Reasons:

1. the bundled SQLCipher engine is behind current upstream (`4.12.0` versus `4.17.0`);
2. current upstream includes later SQLite/security maintenance;
3. the optional enhanced-memory-security probe crashes on the real Windows machine;
4. the wheel is third-party rather than a first-party Zetetic Windows binary and its PyPI publication did not use Trusted Publishing.

## Next packaging gate

Do not repeat the encryption-family research. The next security spike should instead verify a **pinned current SQLCipher 4.17.0 build** behind the same Python-facing contract on the real JARVIS Windows machine.

Leading practical route:

- retain the maintained `sqlcipher3` Python binding surface;
- build it from pinned source with the vendored SQLCipher amalgamation replaced by the chosen pinned SQLCipher `4.17.0` amalgamation, as supported by the wrapper's documented custom-version build path;
- hash/source-pin all build inputs;
- rerun the exact same synthetic SQLCipher/DPAPI harness;
- separately probe enhanced memory security again;
- compare build/maintenance burden with Zetetic's first-party commercial Windows distribution before final package approval.

If the current pinned build passes the same core checks, package provenance/build reproducibility becomes the final encryption packaging decision rather than database-functionality uncertainty.

## Recovery boundary remains

DPAPI is intentionally tied to the Windows user/machine context. Same-machine backup/restore passed. Disaster recovery to a new PC is still a separate design requirement and must not be assumed to work merely because the encrypted DB and DPAPI blob were backed up.

## Sources reviewed around this result

- SQLCipher API / `cipher_memory_security`: https://www.zetetic.net/sqlcipher/sqlcipher-api/
- SQLCipher performance guidance: https://www.zetetic.net/sqlcipher/performance/
- SQLCipher changelog: https://github.com/sqlcipher/sqlcipher/blob/master/CHANGELOG.md
- SQLCipher 4.17.0 release: https://www.zetetic.net/blog/2026/07/08/sqlcipher-4.17.0-release/
- `sqlcipher3` wrapper custom-version build guidance: https://github.com/coleifer/sqlcipher3
- Microsoft `0xC00000FD` / `STATUS_STACK_OVERFLOW`: https://learn.microsoft.com/windows-hardware/drivers/debugger/debugging-a-stack-overflow
