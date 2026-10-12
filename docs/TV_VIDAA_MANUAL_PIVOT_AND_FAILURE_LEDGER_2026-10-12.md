# JARVIS TV: owner-directed manual VIDAA pivot and failure ledger
_Date: 2026-10-12 | Status: manual prototype; no physical TV acceptance_

## 1. Owner decision / scope

**PAUSE automatic capability acquisition for the TV use case.** This is a project
direction and repository-level freeze, **not** a claim that a running JARVIS
process or durable goal was remotely stopped. No local runtime/process access was
available when this record was authored. Preserve all existing GICC,
EngineeringChange, DevelopmentEngine, approval and discovery history. Do not
delete it, reset it, invent a new automatic-acquisition goal or count a manual
TV implementation as proof of automatic acquisition.

For the interim, build a **manually engineered Hisense U7N / VIDAA controller**,
then let the owner explicitly test it on the Windows machine. Keep the direct
controller outside the autonomous capability lifecycle until separately
reviewed, verified, and integrated.

Affected historic intent: operate the owner's Hisense VIDAA TV and eventually
open a streaming app, find a requested title and play it. First acceptance is
smaller: identify the TV, pair with screen PIN, and observe a safe navigation
key working. Media search/playback is **not** implemented by this prototype.

## 2. Evidence-quality vocabulary

- **Observed / documented**: result visible in recorded owner transcripts or
  repository architecture/evidence. It may still require fresh repro.
- **Attempted / not established**: a probe or flow ran, but expected device
  identity, action effect, or exact outcome was not established.
- **Unverified**: hypothesis or candidate. Not permission to pair/control.
- **Passed (mock only)**: automated fake-client tests if CI shows a pass.
- **Owner accepted**: physical device response explicitly observed by owner;
  **none recorded for the new manual implementation**.

## 3. Chronological failures and findings (retain history)

| Period | Attempt / symptom | Evidence / outcome | Disposition |
|---|---|---|---|
| 2026-09-27 to 09-28 | Phase 9 owner-requested acquisition framework, external TV scenario | Software/CI and bounded owner acceptance recorded; real external TV lifecycle **did not finish** because Gemini rate-limited and OpenAI fallback quota was exhausted | Preserve bounded acceptance; do not claim TV integration succeeded |
| 2026-10-01 onward | GICC / D8 owner TV goal intended to acquire capability through Research, Architecture, Development, Verification and promotion | TV path exercised but final physical TV control not established | Keep original lineage, no replacement automatic goal |
| Early October | Architecture/development handoff using `local_device_control` | Manifest binder requested `local_device_control.v1` and raised `UnknownSandboxProfileError` while approved architecture referenced unversioned profile | Exact profile mismatch; reported Dev attempt 9 ended `needs_architecture_revision` |
| Early October | Tests requested from Development | `run_tests` rejected approved test directory as outside permitted acceptance targets | Approval/sandbox target mismatch; do not weaken allowed paths automatically |
| Early October | Work attempt supersession and replan | Recorded research sequence: attempt 1 completed, 2 failed, 3 completed replacement; dependency assembly still included superseded failed work | Old failed dependencies could poison current development; requires authoritative current-attempt semantics |
| Early October | Candidate SDK/library selection | An incompatible Samsung-specific SDK surfaced for the Hisense/VIDAA target | Must reject target-incompatible candidate instead of silently claiming a viable SDK |
| Early October | Package/dependency resolution | A PyPI project URL was used in a context requiring the distribution name | Normalize provider/package reference before dependency admissibility |
| Early October | Architecture revision / approvals | Architecture changed and needed an exact new approval; owner voice approval/response handoffs were also problematic | Retain exact approval boundary, test turn handoff rather than invent approval |
| Early October | E2E development/replay coordination | Provider overload, malformed model structured output, developer-to-research follow-up, retries and restarts identified as cross-system replay scenarios | Component tests are insufficient; keep scenario replay work separate from TV manual pilot |
| 2026-10-09 | Owner supplied `192.168.1.10` for LAN test, port `36669`; PowerShell TCP client attempt recorded | A candidate and a TCP test were recorded, but these transcripts alone do **not** independently establish TV identity or an authenticated control session | Probe specifically; never treat IP or open TCP socket as ownership/TV proof |
| 2026-10-10 | Historical TV test goals `goal_3d8c1c46854cf8184659`, `goal_ecad5b23e96e7e84f6a8`, `goal_af41dcab0613b8e421df` | JARVIS reported cancelling them; audit history remains. Do not assume this proves every other TV goal is stopped | Do not revive old goals |
| 2026-10-11 | Existing goal `goal_3bf2a80a14ecb70dd5b6`, information need `information_need_650e5d2bec48607b852a` | Reported `waiting_for_owner` after bounded discovery attempts; not known to have been cancelled or paused in runtime | Preserve state and verify before automatic resumption |
| 2026-10-11 | DNS-SD, UPnP/SSDP and VIDAA UDP discovery | Permits marked consumed; candidate count **0**; VIDAA UDP result `send_accepted_no_candidates` | Does NOT prove no TV on LAN, or prove that packets were emitted |
| 2026-10-11 | Windows network diagnostics | WinRT backend loadable; network probe `False`; OS-cached neighbors 192.168.1.1, .2, .10, .13 | Cached addresses are not verified TV identities; no permission to pair or control |
| 2026-10-12 | Decision | Owner suspended automatic acquisition and directed manual VIDAA development | This document and an isolated prototype branch record the pivot |

Primary repository references:
- `docs/GLOBAL_SUPERVISOR_GOVERNED_BLACKBOARD_RESEARCH_AND_PLAN_2026-10-05.md` (failed/superseded attempt poisoning, target incompatibility, replay scenarios)
- `docs/PHASE9H_AUTONOMOUS_EXTERNAL_CAPABILITY_COMPLETION.md` (discovery architecture)
- `docs/PHASE9_OWNER_REQUESTED_CAPABILITY_ACQUISITION_ACCEPTANCE_2026-09-27.md` (bounded acceptance)
- `docs/GICC_CHAT_HANDOVER_2026-10-01.md` (owner goal and VIDAA TV scenario)
- Existing owner D8 and VIDAA machine logs (not fully present in this GitHub branch). **Reconcile any missing raw logs before asserting this is exhaustive.**

## 4. What did not work or has NOT been proven

1. No verified VIDAA device identity from approved automatic LAN discovery.
2. No proof that permission consumption meant network packets reached a TV.
3. No TV-screen PIN authentication / durable paired session accepted by owner.
4. No proven safe remote-control action, e.g. Home or Volume Up, with
   observable effect on the actual TV.
5. No verified installed app catalogue, launch, title search, or playback.
6. No end-to-end automatic capability package activation / external acceptance.
7. No general fix proven for all mismatched sandbox profiles, test scopes,
   superseded work dependencies or approval/response handoffs.
8. No evidence of a completed runtime stop/cancel for the still-referenced
   current TV objective as part of this manual GitHub change.

## 5. Protocol research and design decision

Hisense VIDAA commonly offers an **MQTT-based** local remote-control protocol
on TCP port **36669**, with firmware-dependent TLS/authentication. This is NOT
generic Roku and should not be assumed to be WebSocket. Community projects
include `pyvidaa` and `vidaa-control` for MQTT/TLS plus PIN, while some
older VIDAA firmware uses plain MQTT without the same PIN flow.

Prototype uses the community `pyvidaa` SDK as an **optional local dependency**,
rather than rewriting MQTT/authentication, and accepts an explicitly specified,
private-LAN IPv4 candidate. SDK and firmware behavior remain unverified on this
particular U7N. If TLS fails, collect transport diagnostics before choosing any
plain-MQTT variant. Never send default credentials or commands to merely
cached LAN neighbors.

Source references:
- https://github.com/warrenrees/pyvidaa/blob/master/docs/API.md
- https://github.com/tombabolewski/vidaa-control
- https://github.com/techmarkai/ha-vidaa-tv

## 6. Manual implementation and boundaries

- `src/jarvis/vidaa/manual.py`: operator-invoked CLI: `probe`, `pair`,
  `status`, `apps`, `key`, `launch`.
- `tests/test_manual_vidaa.py`: dependency-injected tests with fake SDK and
  socket; **not a physical-device demonstration**.
- No runtime auto-discovery, no background polling, no execution from voice,
  no authority bypass and no modification to protected production capability
  registry, approvals, existing goals or main branch.
- Only explicit RFC1918 IPv4 target addresses and allowlisted keys are
  accepted. `probe` uses a TCP connect and explicitly reports
  `tv_verified: false`.
- The script labels publish requests **unverified** until an owner observes
  the actual TV. Library-provided token persistence is opt-in via
  `--persist-tokens`; storage/security must be reviewed before production use.
- App launch accepts only an exact app name returned by `apps`. Streaming
  title search and playback automation is deferred until remote/key transport
  is physically verified.

### Owner Windows acceptance sequence

Open a PowerShell terminal in the actual JARVIS repo, with the TV ON, on the
same LAN, and **mobile remote / phone app control enabled in TV settings**:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_v1
git fetch origin
git switch feat/manual-vidaa-tv-control
.\.venv\Scripts\python.exe -m pip install pyvidaa
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 probe
```

`192.168.1.10` is a historical **candidate**, not a verified TV. Confirm
TV IP in router/TV settings first if the endpoint doesn't match.

If the probe responds, this is **only port reachability**. Then:

```powershell
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 --persist-tokens pair
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 --persist-tokens status
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 --persist-tokens key home
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 --persist-tokens apps
```

Enter only the PIN **visible on the TV** when requested; never paste the PIN,
library credential, or token into GitHub/chat logs. Observe whether Home
actually opens on screen; report yes/no and sanitized failure type. SDK
success or TCP success alone cannot close physical acceptance. Check `pyvidaa`
local token storage permissions before committing any persistence to production.

Run offline regressions:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_manual_vidaa.py
.\.venv\Scripts\python.exe -m ruff check src/jarvis/vidaa tests/test_manual_vidaa.py
.\.venv\Scripts\python.exe -m ruff format --check src/jarvis/vidaa tests/test_manual_vidaa.py
```

Do **not** claim these tests ran until output/CI evidence exists.

## 7. Acceptance / reintegration gates

1. Explicit TV identity confirmed locally; reachable broker variant identified.
2. PIN pairing/authorization proven where applicable.
3. Owner observes Home/Volume behavior; command outcome and error captured.
4. Installed app list accurately read; selected installed app visibly launched.
5. Streaming UI search/playback added later with evidence and no invented app IDs.
6. Only then wire reviewed controller into JARVIS Hands through existing
   AuthorityService, policy, audit, device identity and typed tool contracts.
7. Separately, resume/retest the frozen automatic acquisition lifecycle using
   the **same** original objective lineage and full system replay tests;
   manual control is not evidence that autonomous acquisition now works.

**Current position:** manual code authored; mocked/unit CI and owner-machine
validation pending. Existing automatic acquisition remains owner-paused by
direction, not technically stopped by this document.
