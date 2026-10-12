# JARVIS TV: owner-directed manual VIDAA pivot and failure ledger
_Date: 2026-10-12 | Status: manual prototype; no physical TV acceptance_

## 1. Owner decision / scope

**PAUSE automatic capability acquisition, including the TV use case.** This is a project
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
| 2026-10-12 | Manual Windows setup | Owner fetched `feat/manual-vidaa-tv-control` and installed `pyvidaa==2.3.0` plus `paho-mqtt==2.1.0` in `.venv`; installation exited successfully | SDK dependency available on owner Windows machine; pairing still untested |
| 2026-10-12 | Manual TCP candidate probe | `python -m jarvis.vidaa.manual --host 192.168.1.10 probe` returned `{"outcome":"tcp_reachable_only","host":"192.168.1.10","port":36669,"tv_verified":false}` | Port 36669 reachable on candidate; **no actual device identity, PIN pairing or control confirmed** |
| 2026-10-12 | New manual-branch CI | First Ruff run exposed formatting/style defects, corrected; comprehensive pytest then reported new `vidaa` namespace missing in self-model; added explicit experimental self-model descriptor. Follow-up CI still pending in this record | Do not claim all tests pass until new branch CI concludes |
| 2026-10-12 | Owner attempted VIDAA PIN pairing twice after successful TCP probe | `pyvidaa 2.3.0` warned `Vidaa client certificate not found`; searched `C:\\Users\\gkgaj\\.config\\pyvidaa\\certs` for `vidaa_client.pem` and `vidaa_client.key`. First run ended `{"outcome":"blocked","reason":"VIDAA client did not connect; check protocol, TV settings and power"}`; second log only displayed the certificate warning, without a terminal outcome | Connection to VIDAA MQTT/auth not established; no PIN shown or pairing confirmed. Do not rerun `pair` before identifying TV/protocol and obtaining proper credentials where required |
| 2026-10-12 | Targeted UPnP identity diagnostic | Owner ran `identify` at `192.168.1.10`: `{"outcome":"vidaa_upnp_candidate","name":"Living Room TV","model":null,"brand":"his","protocol_version":"3290","tv_verified":false,"control_verified":false}` | VIDAA-specific descriptor and modern protocol 3290 confirmed as a device *candidate*. Exact U7N model and remote control effect are unverified |
| 2026-10-12 | Local certificate diagnostic | Owner ran `certs`: `{"outcome":"client_certificate_pair_missing","tls_files_found":false,"tls_handshake_verified":false}` | Cert/key pair absent on Windows. This explains the prior certificate warning; obtaining legitimate client identity is the next prerequisite for mTLS/pairing |
| 2026-10-12 | Owner-source APK importer added (offline prototype) | `src/jarvis/vidaa/import_certs.py` extracts only the documented VIDAA PKCS#12 identity signed by bundled RemoteCA, refuses overwrite, writes only into per-user certs directory; tests in `tests/test_vidaa_import_certs.py` | Code/CI pending; no APK, key, TLS session, or TV response observed |
| 2026-10-12 | Owner emulator APK transfer and certificate import | Official VIDAA app installed in owner's Android emulator (`emulator-5554`); ADB copied `base.apk`, `split_config.arm64_v8a.apk`, `split_config.en.apk`, `split_config.xxhdpi.apk` to owner Downloads. `python -m jarvis.vidaa.import_certs --apk ...base.apk` returned `local_vidaa_client_credentials_imported`, certificate expiry `2034-06-25`, `tv_authenticated:false`, `pairing_completed:false` | Expected client credentials recovered locally from official base APK; importer did not need the split packages. No keys shared with assistant, GitHub, or CI |
| 2026-10-12 | Client certificate availability confirmed locally | `python -m jarvis.vidaa.manual --host 192.168.1.10 certs` returned `client_certificate_pair_present`, `tls_files_found:true`, `tls_handshake_verified:false` | Missing credential prerequisite resolved. Actual TLS handshake, MQTT session, PIN pairing and TV control still unverified; next owner action is an explicit `pair` attempt |
| 2026-10-12 | Pairing after client certificate import | Owner ran `python -m jarvis.vidaa.manual --host 192.168.1.10 --persist-tokens pair` after successful `client_certificate_pair_present`; returned `{"outcome":"blocked","reason":"VIDAA client did not connect; check protocol, TV settings and power"}` | Certificate files found, but TLS/MQTT not authenticated; pairing PIN was never requested. Do not count file presence as a successful TLS connection |
| 2026-10-12 | Root-cause code review after pairing failure | Compared `src/jarvis/vidaa/manual.py` with upstream `pyvidaa 2.3.0` `VidaaTV` constructor. The wrapper passed `auto_detect_protocol=True` but omitted `use_dynamic_auth=True`; SDK default was `False`, which selects static MQTT credentials rather than detecting modern VIDAA protocol 3290 for a new client | Proven integration defect, not yet proven sole cause of runtime failure. Fixed `use_dynamic_auth=True`, added constructor and failure-classification regression tests. Await refreshed CI and owner real TV retest |
| 2026-10-12 | Owner retest after dynamic-auth fix | `identify` at `192.168.1.10` returned `vidaa_upnp_not_observed`; subsequent `pair` printed two `WinError 10061` protocol-descriptor HTTP refusals, `Could not detect protocol`, `modern auth needs a MAC address ... falling back to static credentials`; returned `VIDAA connection failed without an observed MQTT CONNACK` | UPnP descriptor service not reachable on candidate at retest; MAC not obtained; SDK downgraded from modern to legacy static despite `use_dynamic_auth=True`. Current TV IP/power and TCP 36669 need reconfirmation. No evidence TLS handshake or MQTT authentication succeeded |
| 2026-10-12 | SDK downgrade prevention and alternate discovery | Manual VIDAA client changed to fail closed if TV MAC cannot be recovered, rather than constructing static-auth session; bounded UDP broadcast discovery on port 36671 added for exact-match host MAC recovery, and explicit `discover` lists unverified UDP candidates for owner inspection. `allow_static_auth=False` set for owner U7N (prior transport 3290) | Code and tests pending CI/owner validation. UDP sightings are NOT proof of TV identity, successful pairing or permission to control another LAN host |
| 2026-10-12 | Owner retested transport and discovery after UDP fallback changes | Local branch pulled through `6ab088d3`. At `192.168.1.10`, CLI `probe` returned `tcp_unreachable` on 36669; `discover` returned `no_vidaa_udp_candidates`; `identify` returned `vidaa_upnp_not_observed`. | No current protocol reachability at historically identified IP; cannot infer device absence, correct IP, or successful security handshake. Next owner action: switch TV fully on using working iPhone app and verify current TV IP/MAC via TV network status. Do not retry pairing until target is verified. |
| 2026-10-12 | Owner verified correct TV network address and completed PIN pairing | Owner inspected the TV network status, discovering it had moved from `192.168.1.10` to `192.168.1.6` (MAC obtained locally; not copied into this ledger). Ran `python -m jarvis.vidaa.manual --host 192.168.1.6 --mac <verified-TV-MAC> --persist-tokens pair`; UPnP protocol fetch timed out, then user completed the PIN prompt; returned `{"outcome":"sdk_pairing_acknowledged","tv_effect_verified":false,"tokens_persisted_by_sdk":true}` | **PIN pairing succeeded per SDK**, with persistence enabled. Remote command effect and reconnect/token reuse NOT YET verified. Next: owner-visible `key home` or `key volume-up` and report whether TV actually responds. Do not claim end-to-end acceptance until that test passes. |
| 2026-10-12 | First independently confirmed direct TV-control acceptance | After PIN pairing to current TV IP, owner ran `key home`, `key volume-up`, then `key home` again via manual pyvidaa wrapper; all returned `key_submitted_unverified`, and **owner confirmed the TV actually responded to the Home and volume commands**. Each invocation still printed `Failed to fetch protocol info: <urlopen error timed out>` and owner reported substantial command latency. | **Direct TV control verified on owner machine.** Latency remained unacceptable; it is not evidence that commands themselves failed. Token persistence requested, but reboot/reconnect acceptance not yet measured. |
| 2026-10-12 | Known-protocol latency optimization | Added opt-in CLI `--protocol-version 3290` for the TV version previously observed via VIDAA descriptor. It selects `AuthMethod.MODERN` and `auto_detect_protocol=False`, while retaining dynamic auth, TV MAC, saved credentials and TLS. Added optional `session` subcommand to reuse one authenticated MQTT connection across multiple allowlisted remote commands. | Designed to avoid slow repeat HTTP discovery timeouts and per-command connection setup. Automated tests added; actual owner-device latency and command effects after optimization remain to be verified. |
| 2026-10-12 | Low-latency TV control physically accepted by owner | Owner pulled optimized manual-controller branch and ran `key volume-up` with owner-verified MAC and `--protocol-version 3290`, then started `session` using the same protocol flag. The previous `Failed to fetch protocol info` warning did not appear. Owner reports that commands in persistent session take effect on the actual TV **immediately on pressing Enter**. | **PASS:** owner-observed low-latency remote key control using persistent MQTT/TLS connection. Remaining: app listing/launch, clean reconnect after closing session/restarting, dynamic IP rediscovery, safe standby/wake, production JARVIS integration. Avoid claiming app/movie playback or power-on are accepted yet. |
| 2026-10-12 | Installed VIDAA TV app discovery accepted | Owner executed `python -m jarvis.vidaa.manual --host 192.168.1.6 --mac <owner-verified-TV-MAC> --protocol-version 3290 --persist-tokens apps`. Output: `apps_response` listing TV apps including `JioHotstar`, Netflix, Prime Video, YouTube, and Apple TV; `tv_effect_verified:false` | **PASS:** TV application inventory retrieved via authenticated SDK. Next owner acceptance: `launch "JioHotstar"` and visual confirmation on TV. App launch and specific-movie navigation remain unverified. |
| 2026-10-12 | Owner observed near-instant JioHotstar launch | Following `apps_response` listing exact `JioHotstar` title, owner invoked manual `launch "JioHotstar"` on paired Hisense U7N and **confirmed the application opened immediately on the physical TV**. | **PASS:** authenticated VIDAA app launch, owner-observed, near-instant. Next pending: in-app navigation/search/playback, power-on from standby, reconnect after DHCP change, main JARVIS runtime voice integration. App-launch success is not movie playback acceptance. |
| 2026-10-12 | Consolidated one-run owner TV acceptance harness added | Added `python -m jarvis.vidaa.manual --host <TV_IP> --mac <verified-TV-MAC> --protocol-version 3290 --persist-tokens acceptance` CLI. Reuses one verified connection to inspect app inventory, submit Home / volume up / volume down, launch installed JioHotstar by TV-supplied app descriptor, and reconnect MQTT once. Prompts owner only once for visual effects and emits machine-readable stage statuses, redacting SDK failure details. Added offline regression tests, GitHub CI pending. | No new machine acceptance yet for this new command. Movie text search/playback, standby wake, DHCP IP reacquisition and JARVIS voice/runtime integration remain explicitly `skipped` until capabilities implemented and verified. No automatic power-off or PIN re-pairing. |
| 2026-10-12 | Owner clarified required acceptance goal | Owner reports the consolidated remote-command smoke test returned `acceptance_completed`, confirmed Home, volume and JioHotstar launch, and MQTT reconnect. Owner explicitly clarified that this was insufficient: the intended **single end-to-end instruction** must launch JioHotstar, select the owner's profile, search for **The Martian**, start the film, then provide completion confirmation without manual per-step commands. | Previously completed smoke test is real but narrower. Full in-app workflow NOT implemented or validated; don't conflate `acceptance_completed` with movie playback. Need profile/search/playback UI strategy and observable playback evidence. |
| 2026-10-12 | VIDAA text-entry protocol researched, experimental helper added | Other VIDAA community integration uses MQTT `/remoteapp/tv/ui_service/{client_id}/actions/sendtext` with `{"text": "..."}`, noting firmware may silently ignore it. Added `publish_focused_text()` and a `text` CLI command as an experimental local-only building block with allowlisted text length, no text logging, tests pending CI. | NOT yet tested on owner's modern VIDAA 3290/JioHotstar. MQTT publish acceptance cannot prove the JioHotstar text field received the movie title. No screen capture, UI tree, or playback proof via existing pyvidaa API; movie flow must fail closed or get owner-observed confirmation. |
| 2026-10-12 | Software-only UI observation reconnaissance implemented | Owner prioritized generalized software screen observation as prerequisite to adaptive JioHotstar/Netflix/Prime navigation. Research: pyvidaa authenticated MQTT exposes TV-state and capability metadata, not screenshot/DOM/focus; VIDAA U4 developer docs describe older web-app remote inspection on port 9226, not guaranteed for U7N or protected third-party apps. Added `src/jarvis/vidaa/observation.py`, `observe` CLI command, safety tests, and `docs/VIDAA_SOFTWARE_OBSERVATION_RECON_2026-10-12.md`. Bounded read-only probe queries sanitized TV metadata and checks only 9226 `/json/version` without enabling debug/collecting app content. | **Unverified on owner TV; next one-command read-only `observe` run required.** Screen image, focus, DOM and movie playback remain unverified. Developer inspector reachability does not itself prove cross-app UI accessibility. |
| 2026-10-12 | Physical TV L1 observation acceptance and read-only inspector follow-up | Owner ran `observe` against paired Hisense U7N. TV state `statetype=app`; TV info, device info, capability returned safe metadata. Documented old 9226 inspector `unreachable_or_no_response`. Screenshot/UI tree/focused element/playback all `not_observed`; `software_ui_navigation_ready=false`. Research confirmed Hisense 55U7N VIDAA U7.6 and older VIDAA developer docs additionally describe port 9222 (chipset dependent); added one bounded read-only 9222 check. Suitest developer inspection typically requires authorized DevTools/app setup and is not proof of cross-app Netflix/JioHotstar UI visibility. | **PASS L1 (metadata); BLOCKED L2 (UI/screen focus).** Owner has not yet tested 9222. Do not falsely claim generalized UI observation. Next: one `observe` retry with updated optional legacy check, then decide verified software route or admit platform limitation. |
| 2026-10-12 | Second legacy inspector rejected; GitHub DNS recovered | Owner ran a bounded read-only HTTP request on current TV 192.168.1.6 port 9222 `/json/version`: `No usable inspector response`, `InspectorConfirmed=False`. Prior 9226 inspection also returned `unreachable_or_no_response`. Owner's first Git pull failed `Could not resolve host: github.com`, then `ipconfig /flushdns` restored access and fast-forward pull to `e92a74f5` succeeded. Research: Suitest documents VIDAA Ottium network screenshots only when DevTools is available via partner provisioning; not verified on consumer U7.6 or across third-party OTT apps, DRM may restrict content. | **Legacy 9222 and 9226 probes complete; L1 metadata PASS; L2 cross-app screen observation NOT ESTABLISHED.** Don't retest these ports, enable hidden developer features, or claim cross-app screenshot support. Ask manufacturer/VIDAA for an authorized U7.6 screen/focus API before investing in Ottium integration. |
| 2026-10-12 | Latest CI gate | GitHub workflow 38235271102 concluded `success` on manual VIDAA branch before owner APK import | Automated tests passed; neither certificate extraction from real owner APK nor physical TV interaction is exercised by CI |



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

- `src/jarvis/vidaa/manual.py`: operator-invoked CLI: `probe`, UPnP
  `identify`, local certificate-pair `certs` check, `pair`, `status`, `apps`,
  `key`, `launch`.
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

### VIDAA mutual-TLS certificate blocker (observed 2026-10-12)

The owner confirmed TCP reachability on port 36669. However the VIDAA client
itself failed to connect because `pyvidaa` could not locate a certificate/key
pair. This failure occurs **before PIN pairing**. A TCP response is not proof
of a successful MQTT TLS handshake. Repeating `git pull` or the PIN request
without the appropriate certificate will not resolve a missing-key condition.

The `pyvidaa` README says newer TV firmware requires a **mutual TLS client
certificate**, which is not distributed in the library. It identifies the
official VIDAA Android application's PKCS#12 keystore as a possible owner-
controlled source. Some older firmware can work without these files. We must
identify the actual device and transport protocol before treating modern mTLS
as established for this specific TV.

Manual diagnostic commands after pulling current branch:

```powershell
.\\.venv\\Scripts\\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 identify
.\\.venv\\Scripts\\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 certs
```

`identify` performs targeted UPnP descriptor probing (not pairing/control);
if it cannot read the description, do **not** conclude the endpoint isn't a
TV. `certs` reports file presence only, never prints certificate or private
key material.

**Obtaining missing credentials when required:** install the official VIDAA
mobile app via the TV's **Settings > Support > Mobile App** QR code, and if
there is an owner-controlled Android installation/APK available, follow the
upstream "Obtaining the client certificate" instructions to extract the APK's
client PKCS#12 keystore into local PEM cert/key files. The documented
locations may include `assets/client_mobile_android.p12` or an obfuscated
`res/*.p12` path in newer builds. Store locally in
`%USERPROFILE%\\.config\\pyvidaa\\certs`, under exactly
`vidaa_client.pem` and `vidaa_client.key`; do not commit, upload,
paste or redistribute key material. Private keys must have restricted
permissions. If there is no owner-sourced APK or the TV doesn't match the
supported protocol, do not invent a substitute client identity.

Upstream references:
- https://github.com/warrenrees/pyvidaa/blob/master/README.md#obtaining-the-client-certificate
- https://github.com/warrenrees/pyvidaa/blob/master/VIDAA_PROTOCOL_ANALYSIS.md
- https://www.vidaa.com/customer_support/how-do-i-install-the-vidaa-app/

### Offline certificate import from official Android app APK (not yet owner-tested)

The official Android app is [VIDAA Smart TV on Google Play](https://play.google.com/store/apps/details?id=com.universal.remote.multi)
(package `com.universal.remote.multi`), published by V America Operations
Inc. Only use an APK copied from the owner's/authorized Android app installation.
The target's UPnP protocol `3290` also uses dynamic MQTT credentials. The
manual client now reads the interface MAC from the **same targeted TV UPnP
descriptor** when available, so the owner normally does not have to type it.
The `identify` diagnostic reports only `mac_available`, without revealing
the interface MAC. If the targeted descriptor lacks one, the client fails
closed with a request to specify the MAC via `--mac` instead of silently using
legacy fixed MQTT credentials.

Google Play does **not** provide a simple direct APK download to Windows.
Avoid downloading random APKs/private keys from third-party upload websites.

An optional local-only importer has been added to this branch to avoid
hand-running OpenSSL and copying certificate/key files:

```powershell
# After obtaining a local authorized APK at a path YOU know:
git pull --ff-only origin feat/manual-vidaa-tv-control
.\\.venv\\Scripts\\python.exe -m jarvis.vidaa.import_certs --apk "$HOME\\Downloads\\vidaa_official.apk"
.\\.venv\\Scripts\\python.exe -m jarvis.vidaa.manual --host 192.168.1.10 certs
```

`vidaa_official.apk` is an example filename, not a file known to exist. On a
split-APK Android installation, the client keystore may reside in an APK
other than the base package; pass the APK that contains the documented P12
entry. The importer rejects unknown client identity, wrong RemoteCA signer,
expired certificates, malformed archives, oversized P12 entries, and
overwriting existing keys. It never downloads APKs or shares secret files.
It uses the upstream documented P12 store password internally, which is
not a personal credential. It writes `vidaa_client.pem` and
`vidaa_client.key` only under the current user's local pyvidaa cert directory;
the PEM private key is unencrypted because the library requires it, so Windows
user-profile permissions and backups must be protected. This is a local
engineering utility, not authorization to use unrelated devices.

The import only establishes locally present client credential files. It does
**not** prove that the TV accepted TLS, MQTT, PIN pairing or any command.
After import, retest `pair` with the actual TV ON and verify a PIN appears.
Do not attempt pairing before the importer reports success (or another trusted
cert/key pair is locally available).

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
