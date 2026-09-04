# Step 4 — SQLCipher + Windows DPAPI bake-off plan

## Status

**RESEARCH / OWNER-MACHINE SPIKE. NOT PRODUCTION APPROVAL.**

This gate determines whether the selected SQLite/FTS5 memory foundation can be protected safely on the real JARVIS Windows machine without introducing an unnecessary database service or a custom cryptosystem.

## Research conclusion before the spike

SQLCipher remains the leading whole-database encryption technology. It is a mature SQLite encryption extension maintained by Zetetic, uses AES-256 full-database encryption, encrypts database pages and WAL/rollback-journal page data, and exposes keying, rekeying, cipher integrity checking and provider/version inspection.

Important Windows/Python packaging distinction:

1. Zetetic distributes official prebuilt Windows SQLCipher packages, but these are Commercial/Enterprise products.
2. SQLCipher Community Edition remains available under its BSD-style license, but Zetetic does not provide public Community Edition Windows build support/instructions.
3. `sqlcipher3==0.6.2` is a third-party Python wrapper maintained by Charles Leifer. Its 2026-01-07 release includes a CPython 3.11 Windows x86-64 wheel, which matches the current JARVIS runtime. The PyPI wheel was not uploaded with Trusted Publishing.
4. Therefore the wheel is a **bake-off candidate**, not an automatically trusted production dependency. If runtime behavior is good, the final packaging decision must still choose between a hash-pinned third-party wheel, a reproducible/pinned Community Edition source build, or Zetetic's official commercial Windows package.

Sources reviewed 2026-09-04:

- https://www.zetetic.net/sqlcipher/
- https://www.zetetic.net/sqlcipher/design/
- https://www.zetetic.net/sqlcipher/sqlcipher-api/
- https://www.zetetic.net/sqlcipher/sqlcipher-windows/
- https://www.zetetic.net/sqlcipher/license/
- https://pypi.org/project/sqlcipher3/
- https://github.com/coleifer/sqlcipher3
- https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata

## Key-management direction

JARVIS already has a tested user-scoped Windows DPAPI protector in `src/jarvis/identity/crypto.py`. Microsoft documents that DPAPI-protected data is normally decryptable only by the same user credentials on the same computer, and `CryptUnprotectData` performs an integrity check while unprotecting.

The memory design under test is:

```text
random 32-byte SQLCipher raw key
        |
        v
Windows DPAPI, user scope + JARVIS purpose entropy
        |
        v
small sealed key blob on disk

SQLite + FTS5 memory DB
        |
        v
SQLCipher full-database encryption using the random raw key
```

This avoids storing a plaintext passphrase/key and avoids inventing a JARVIS cryptographic format.

The research harness may import the existing identity DPAPI class to validate the already-implemented Windows primitive. **Production memory must not import identity internals.** If selected, the common protector must move behind a neutral `jarvis.security` boundary or equivalent architecture during implementation.

## Real-machine assertions

The Windows spike must measure/prove all of the following using synthetic data only:

- the installed Python wrapper is actually backed by SQLCipher (`PRAGMA cipher_version`);
- record the bundled SQLCipher version, SQLite version, crypto provider/provider version and compile options;
- FTS5 is compiled and English/Hindi search works inside the encrypted database;
- a random 256-bit raw SQLCipher key works using SQLCipher's supported raw-key syntax;
- DPAPI seal/unseal round-trip succeeds for the intended purpose;
- DPAPI unseal with a different purpose is rejected;
- the raw DB key is not present in the DPAPI blob;
- `temp_store=MEMORY`, `secure_delete=ON`, and WAL mode are usable;
- SQLCipher page integrity check is clean for an intact database;
- synthetic plaintext markers and raw key material are absent from the encrypted DB/WAL/SHM/key artifacts during the live WAL test;
- standard Python `sqlite3` cannot open the encrypted database without a key;
- SQLCipher with a wrong key cannot read the database;
- offline backup of encrypted DB + DPAPI-wrapped key can be restored and queried on the same Windows user/machine;
- deliberately modified ciphertext is detected;
- explicit forget removes the canonical row and FTS result, with `secure_delete` enabled and a vacuum before final verification;
- final encrypted artifacts still contain none of the synthetic plaintext markers or raw key bytes.

## Supply-chain gate

Before installing `sqlcipher3` in the isolated spike venv, download the exact CPython 3.11 Win64 wheel and verify its SHA-256 against PyPI metadata.

Expected file:

`sqlcipher3-0.6.2-cp311-cp311-win_amd64.whl`

Expected SHA-256 from PyPI on 2026-09-04:

`4ad7e4a32de907011ea22ac2012c9bca1bb414e2f599c56a55c8b0fe6445b932`

A matching hash proves the local file matches the artifact published on PyPI; it does **not** turn the third-party wheel into a first-party Zetetic build. Provenance remains a separate final technology-decision input.

## Decision rule after owner-machine run

A functional/security PASS means SQLCipher is technically suitable for the JARVIS memory store on Windows. It does **not by itself approve the `sqlcipher3` wheel for production**.

After the measured run we will disposition packaging explicitly:

- **KEEP HASH-PINNED WHEEL** only if bundled SQLCipher/version/options are acceptable and third-party artifact provenance is acceptable for this personal local deployment;
- **SELF-BUILD PINNED COMMUNITY EDITION** if runtime is good but wheel provenance is not acceptable;
- **OFFICIAL ZETETIC WINDOWS PACKAGE** if first-party binaries/support justify the commercial dependency and Python integration can be kept maintainable;
- **REJECT SQLCIPHER** only if the real Windows behavior fails a security/compatibility requirement and another mature solution demonstrably handles it better.

No production Step-4 memory implementation begins from this spike alone.
