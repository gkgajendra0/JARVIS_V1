# JARVIS — Hindsight real loopback import acceptance (2026-10-17)

**Draft / synthetic-only / one local import / no LLM provider**.
The previous PR #274 passed a five-document fake/archive contract on the
owner's Windows 11 PC (7/7 tests), with SHA-256
`2ed821195ea9ea2ff388f7f366c14c3f3c5363edaa088d642ac6f440c3b99ac0`.
This PR builds the **next optional server-compatibility stage**. It is NOT
a live result, consolidation test, private-memory test, or approval for
new Gemini requests. Do not merge into production.

## What the opt-in probe does

`tools/research/step4_hindsight_loopback_import_probe.py` uses standard
Python libraries, no Hindsight SDK, no pip install or Docker pull. It
defaults to a zero-network summary. When the owner explicitly opts in,
it checks a real `docker inspect` for the exact **owner-created**
`jarvis-hindsight-lab` container before any HTTP request:

- exact image tag `ghcr.io/vectorize-io/hindsight:latest` (locally pulled);
- Docker running with localhost-only **127.0.0.1:18888 → 8888** mapping,
  no restart policy, one disposable Docker **named volume** and embedded pg0;
- explicit `HINDSIGHT_API_LLM_PROVIDER=none`,
  `HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false`,
  `HINDSIGHT_API_ENABLE_OBSERVATIONS=false`;
- no cloud API keys / default bank templates in Docker config.

It then uses only **http://127.0.0.1:18888**, with proxies and
redirects disabled, to create a random disposable bank, set
`enable_observations=false`, `enable_auto_consolidation=false`,
and **read back effective config**. When the provider is `none`, Hindsight
selects chunks mode automatically; `retain_extraction_mode=chunks` is not
a supported configurable extraction-mode override.

Only after confirming those settings does it send exactly ONE
`/v1/default/banks/{bank}/transfer/import?mode=merge&document_conflict=skip`
ZIP built and verified directly from the pinned five fictional facts.
It polls the returned operation ID (does not mistake a 202 accepted
submission for success), verifies exactly five documents/one fact per
document and matching fictional original text, deletes its temporary
bank, and confirms a 404 on the deleted bank's config endpoint.

**Limitations:** no proof of Hindsight's semantic correction behavior,
no test of idempotent re-imports, no independent verification of
fact-level source metadata after import. External-fact import may
re-embed facts even when no LLM is used. Local Docker can make network
connections to fetch model assets: configure container/network firewall
separately to guarantee no outbound traffic. This runner does not
guarantee that by itself. The absence of keys plus `provider=none`
prevents use of conventional paid LLM providers in this configured
container, but does not cryptographically attest downstream egress.

If any stage fails, the probe attempts to delete **only its own**
newly minted disposable bank. A cleanup failure itself exits nonzero;
stop, inspect the disposable container and delete the volume. No
automatic retry and no additional model calls.

## Owner-machine commands — ONLY when ready for Docker evaluation

Prerequisites: Docker Desktop installed and running with Linux
containers. This is the **first stage requiring the owner to download
or run a real external Hindsight service**. The full upstream image is
approximately 9 GB on amd64 and may consume additional disk/RAM.
There is no Hindsight subscription or per-call API charge for this
self-hosted/LLM-disabled import, but disk, electricity, and internet
transfer are real costs. Do not perform this stage if disk/RAM are tight
or if it would interrupt the existing JARVIS environment.

Use the **separate** research worktree and existing JARVIS Python
environment. Do not start/stop/modify production JARVIS Docker
containers.

Inspect a *dry run* before Docker (no network requests or install):
```powershell
$py = "C:\Users\gkgaj\Desktop\jarvis_v1\.venv\Scripts\python.exe"
& $py tools\research\step4_hindsight_loopback_import_probe.py
& $py -m pytest -q tests\test_step4_hindsight_loopback_import_probe.py
```

When the owner explicitly elects to use local Docker (image download
is deliberate, not performed by the Python script):

```powershell
# Confirm disk headroom and Docker Desktop status first.
docker version
docker pull ghcr.io/vectorize-io/hindsight:latest
docker volume create jarvis-hindsight-lab-20261017

docker run -d --rm --pull=never --name jarvis-hindsight-lab --restart=no `
  --shm-size=1g -p 127.0.0.1:18888:8888 `
  -e HINDSIGHT_API_LLM_PROVIDER=none `
  -e HINDSIGHT_API_ENABLE_OBSERVATIONS=false `
  -e HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false `
  -e HINDSIGHT_API_DATABASE_URL=pg0 `
  -e HINDSIGHT_API_ENABLE_BANK_LLM_HEALTH=false `
  -e HINDSIGHT_API_ENABLE_DRY_RUN_EXTRACT=false `
  -v jarvis-hindsight-lab-20261017:/home/hindsight/.pg0 `
  ghcr.io/vectorize-io/hindsight:latest

# Confirm container is healthy, without invoking an LLM:
Invoke-RestMethod http://127.0.0.1:18888/version

# Execute ONLY ONCE. Uses exactly one external-fact import.
& $py tools\research\step4_hindsight_loopback_import_probe.py --allow-one-local-import

# Clean up container and its isolated PostgreSQL volume.
docker stop jarvis-hindsight-lab
docker volume rm jarvis-hindsight-lab-20261017
```

If the server fails to start or returns unsupported config/import
endpoints, share the **sanitized status JSON and Docker error category**
(no API keys or memory values). Do not retry the import or adapt
Docker flags to use cloud inference without explicit new approval.

## Evidence contract

Successful fake-client tests must establish:
- wrong or paid-capable container configuration fails BEFORE HTTP;
- exactly one request to import the pinned ZIP;
- effective bank overrides verified before upload;
- operation status polled to completed;
- exactly five source documents/one imported memory each;
- cleanup verified with 404 on the temporary bank;
- failed import, unclear target, and altered documents fail closed;
- default CLI issues zero Docker inspection, network, or provider calls.

Official API docs:
https://hindsight.vectorize.io/developer/api/memory-banks
https://hindsight.vectorize.io/developer/configuration
https://hindsight.vectorize.io/developer/installation

**Future task, separate approval:** manually run local consolidation with
a reviewed local LLM and test whether it independently resolves
English/Hindi/Hinglish source references and temporal corrections.
Do not call that a capability solved from an import-only pass.
