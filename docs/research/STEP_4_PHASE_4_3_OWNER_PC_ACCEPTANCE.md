# Step 4 — Phase 4.3 Owner-PC Acceptance

## Status

**OWNER-PC PACKAGE + ENCRYPTED ADAPTER: PASS.**

**CROSS-SESSION VOICE ACCEPTANCE: PENDING.**

Date: 2026-09-05

This record captures the real JARVIS Windows owner-machine acceptance evidence for the first production persistent-memory rollout. It does not mark Phase 4.3 complete until the cross-session voice remember/inspect/correct/forget sequence passes.

## 1. Retained SQLCipher package integrity — PASS

The retained JARVIS SQLCipher 4.17.0 CPython 3.11 Win64 wheel was downloaded from the successful GitHub Actions artifact and installed into the owner machine's existing `.venv` only after SHA-256 verification.

Wheel:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170-cp311-cp311-win_amd64.whl`

Expected SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Owner-machine measured SHA-256:

`f0b005bea9fe2451870266d1f3aa697c05383de21e6ebdf2bef470a4fad1dbba`

Result: **MATCH / PASS**.

Pip then reported successful installation of:

`sqlcipher3-0.6.2+jarvis.sqlcipher4170`

## 2. Production encrypted-memory adapter smoke — PASS

The owner machine ran:

`tools/research/step4_sqlcipher_production_adapter_smoke.py`

using the installed retained wheel and the production `SqlCipherMemoryDatabaseFactory` + Windows DPAPI boundary.

Measured runtime:

- SQLCipher: `4.17.0 community`;
- SQLite: `3.53.3`;
- result: `PASS`;
- leaks: `[]`.

Every production-adapter assertion passed:

- `cipher_status`;
- `cipher_version`;
- `sqlite_version`;
- migration version;
- single migration ledger entry;
- FTS first-open synchronization;
- encrypted reopen current assertion;
- encrypted reopen FTS;
- DPAPI-protected key sidecar exists;
- stdlib plaintext SQLite open blocked;
- synthetic memory marker absent from storage artifacts.

The smoke used a disposable owner-PC temporary directory under `%TEMP%`; it did not write the real personal-memory database.

## 3. Initial one-line version probe note

A convenience PowerShell/Python one-line probe failed to parse because nested quoting was malformed. This was a command-quoting issue only and is not a product failure. The subsequent production-adapter smoke directly proved the required SQLCipher and SQLite engine versions and all production adapter checks.

## 4. Remaining mandatory Phase 4.3 acceptance

Before Phase 4.3 may close, run the real production voice path with persistent memory enabled and prove at minimum:

1. explicit remember succeeds;
2. a later voice session exact inspect recalls the durable value;
3. explicit correction replaces the current belief;
4. a later voice session returns the corrected value;
5. explicit forget succeeds;
6. a later voice session no longer returns the forgotten memory;
7. memory survives at least one production process restart during the sequence;
8. no implicit ordinary statement is durably stored;
9. no secret/credential request is accepted;
10. normal wake/audio/provider behavior remains usable.

Phase 4.4 remains blocked until this owner cross-session voice acceptance passes.
