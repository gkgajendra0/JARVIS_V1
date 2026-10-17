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
redirects disabled, to create a random disposable bank and
**read back effective config**. It does NOT PATCH bank configuration:
the inspected Docker configuration already sets
`enable_observations=false` and `enable_auto_consolidation=false`.
If the resolved per-bank settings do not both read back as false, the
probe deletes its temporary bank and refuses import. With LLM provider
`none`, Hindsight automatically uses chunks mode.

Only after confirming those settings does it send exactly ONE
`/v1/default/banks/{bank}/transfer/import?mode=merge&document_conflict=skip`
ZIP built and verified directly from the pinned five fictional facts.
It polls the returned operation ID (does not mistake a 202 accepted
submission for success), verifies exactly five documents/one fact per
document and matching fictional original text, then independently reads
each fact using the documented /memories/list?document_id=... endpoint.
It requires the exact fictional text, source document, fact type, source
turn, canonical reference, assertion version, predicate and supersession
lineage in fact metadata. Any missing or changed value fails the
acceptance probe. It then deletes its temporary bank and confirms a 404
on the deleted bank's config endpoint.

**Limitations:** no proof of Hindsight's semantic correction behavior,
no test of idempotent re-imports, no independent verification of
fact-level source metadata after import **until a real import passes
this new readback gate**. External-fact import may re-embed facts even
when no LLM is used. Local Docker can make network
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
- one readback per imported fact, checking full synthetic source/version
  metadata independently of the document text;
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

## Owner-machine first live run (2026-10-17): HTTP 400, not accepted

Owner confirmed the clean separate image and localhost Hindsight 1.0.0
server with health/ready=200, document_import_api=true, observations=false.
At pinned research head `784b3eee`, the sole explicitly approved
`--allow-one-local-import` invocation returned
`{"error_type":"LocalHTTPError","reason_code":"local_http_400","status":"fail_closed"}`,
exit code 1. **No import success, no 5-document readback or verified cleanup
was observed. No repeat is authorized by that invocation.**

The original script intentionally suppressed HTTP response bodies but also
suppressed the stage of the failing request; the 400 can have occurred during
bank create, config, upload or cleanup. Do not infer which, or assume cleanup
succeeded. A later change in this draft reports the exact operation stage
from a fixed sanitized allowlist, never the bank ID or provider text; that
is for **future separately approved runs only**.

Investigate the existing **read-only local Docker logs** first:
```powershell
docker logs --since 60m jarvis-hindsight-lab 2>&1 |
  Select-String -Pattern '400 Bad Request|/v1/default/banks/|ValidationError|ERROR|failed' |
  Select-Object -Last 45
```
Sanitize any non-fictional values before sharing. Do not repeat the import,
start paid providers, delete the volume or promote JARVIS memory logic
before the failure and cleanup state are established.


## Owner-machine follow-up: original HTTP 400 remains unresolved (2026-10-18)

Owner re-ran the original live script and observed a second
`local_http_400` (the old checkout did not yet report a request stage).
This repeat is **not** additional evidence of successful import or cleanup.
The container was running, but grep of recent Docker logs for `400`,
`Bad Request`, `/v1/default/banks`, `ValidationError`,
`ERROR`, and `Traceback` printed **no matching lines**. No request-stage
deduction is justified from that silence.

Owner then updated the isolated worktree to commit `d7ed3ff1` and
confirmed **12/12 offline fake-service tests passed**. They did not report
a new live import against that commit. The updated probe now emits
`bank_creation_http_400`, `bank_config_update_http_400`,
`archive_upload_http_400`, etc., and preserves the first error when
cleanup also fails. It does NOT retroactively classify earlier 400s.

Read-only `GET /openapi.json` evidence from that container showed:
- `PUT /v1/default/banks/{bank_id}` accepts JSON
  `CreateBankRequest` (no required fields in the exposed request schema).
- `PATCH /v1/default/banks/{bank_id}/config` accepts JSON
  `BankConfigUpdate` whose required top-level field is `updates`.
- `POST /v1/default/banks/{bank_id}/transfer/import` accepts
  multipart/form-data and requires a `file` field.
- `DELETE /v1/default/banks/{bank_id}` has **no request body**.
  The `Cannot index into a null array` exception in the PowerShell
  schema-inspection loop resulted from dereferencing that absent body,
  not a Hindsight DELETE failure.

These checks confirm route existence and outer request shape, not
nested validation rules, response shape or whether any request was
accepted. Do **not** submit another import, delete the volume, or
enable LLM consolidation on these facts alone.

**Next read-only evidence to collect**: resolve
`$api.components.schemas.BankConfigUpdate.properties.updates` and its
nested `$ref`/`anyOf`; inspect bank creation path parameters, and
enumerate IDs only for banks starting `jarvis-dev-only-` in this
disposable instance. No user-private memory values or API keys should
be printed. Use the output to locate the 400 source before authorizing
a separate single local import.

## Next non-production contract refinement (2026-10-18)

The owner confirmed the server is healthy after restart
(`/health/ready` HTTP 200; PostgreSQL connected) and that the
`GET /v1/default/banks?query=jarvis-dev-only-&limit=100` response
contains `{"banks":[],"total":0}`. This is reassuring evidence
that no matching disposable banks are currently registered in this
test instance. It is not a proof of which earlier request returned 400.

The live server's OpenAPI `BankConfigUpdate.updates` schema is a
free-form object, but documents say only hierarchical fields may be
overridden per-bank. The official Hindsight docs identify both
`enable_observations` and `enable_auto_consolidation` as hierarchical
and valid bank overrides. Consequently the old config-PATCH call
**cannot be blamed for the 400 without additional evidence**.

We removed that unnecessary PATCH from the research-only probe,
because the lab Docker configuration already sets both server defaults
to false. The probe still requires a GET of the *resolved* bank
configuration showing both values false before it will upload. This
reduces writes and possible API compatibility faults while keeping
the critical no-auto-consolidation gate in place. Fake-client tests
assert **no PATCH** in both the normal path and disabled-gate failure.
No further Hindsight server requests were made as part of this fix.

The only way to identify the previous 400 operation conclusively is
from matching server diagnostics or a new, separately approved
single-run stage-coded test. Do not represent the earlier two failed
runs as successful or proof of Hindsight engine incompatibility.

## GitHub-only follow-up (2026-10-18): provenance-gated readback

GitHub CI at `4ffff153` completed with all six jobs passing, including
Windows DPAPI, Windows full pytest and promotion-policy. The two previous
HTTP 400 live attempts are **still unclassified**, and no additional real
Hindsight import was performed.

The official Hindsight 1.0.0 API documents
`GET /v1/default/banks/{bank_id}/memories/list` with a
`document_id` query filter and result fields `items`, `total`,
`text`, `fact_type`, `document_id`, and `metadata`.
The research probe now checks fact-level assertion lineage on this endpoint;
fake-service tests cover exact provenance and a simulated missing-source
failure with cleanup. These tests do **not** imply a successful real import.

Before a new owner-approved single import, fetch the latest tested research
head and rerun the offline fake-service tests. Preserve the existing isolated
volume and do not auto-repeat any failed import.
