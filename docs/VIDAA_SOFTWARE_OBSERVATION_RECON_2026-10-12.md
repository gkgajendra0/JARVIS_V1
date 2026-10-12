# VIDAA software-only UI observation reconnaissance — 2026-10-12

## Owner goal

Enable JARVIS to **observe what is happening on the TV** between remote
actions, so it can select a profile, search for a title, choose a result,
and confirm playback across JioHotstar, Netflix, Prime Video, etc., without
a separately authored fragile sequence for each app.

The owner's Hisense U7N VIDAA TV already passed physical acceptance for
MQTT/TLS pairing, remote keys, low-latency persistent connection, app listing,
app launching (JioHotstar), and reconnecting using saved credentials.

**Critical distinction:** those tests verify CONTROL, not screen OBSERVATION.
The existing one-run `acceptance` command checks remote controls only; it
does not inspect the streaming-app UI or prove a film is playing.

## What is known from public protocol documentation

1. The upstream `pyvidaa` Python SDK exposes read-only `get_state`,
   `get_tv_info`, `get_device_info`, `get_capability`, `get_sources`,
   `get_apps`, volume, and remote actions. We have not found a documented
   screenshot, accessibility tree, focused-UI-element, or streaming-app
   playback-state interface there.
   Source: https://github.com/warrenrees/pyvidaa/blob/master/docs/API.md
2. VIDAA's *older U4* WebApp technical guide describes application
   remote debugging services at `http://TV_IP:9226` or `:9222` depending
   on legacy chipset, after developer mode has been enabled. This is web-app inspection, not a guaranteed general
   screenshot service and not proof of access to proprietary streaming apps.
   Source: https://www.vidaa.com/wp-content/uploads/2020/12/WebApp_Development_Guide_for_VIDAA.pdf
3. The separate VIDAA application-testing vendor Suitest supports
   device-specific developer inspection in partner/testing setups and
   requires DevTools and app setup. Its documentation distinguishes Ottium
   and application instrumentation; it does not establish unprivileged
   cross-app screen access on a consumer U7N.
   Sources: https://suite.st/docs/devices/vidaa/ and
   https://suite.st/docs/application/setting-up-vidaa-apps/
4. Hisense India lists the 55U7N operating system as **VIDAA U7.6**,
   whereas the public developer-guide ports concern older VIDAA devices.
   Source: https://www.hisense-india.com/tv-series/mini-led/hisense-139-cm-55-inch-4k-ultra-hd-mini-led-55u7n
5. VIDAA U7N screen sharing is described as Android-device-to-TV mirroring,
   not as a reverse TV-to-PC screen-feed API.
   Source: https://www.hisense-india.com/tv-series/mini-led/hisense-139-cm-55-inch-4k-ultra-hd-mini-led-55u7n
   Source: https://s45rlq5r-0.suitest.tv/docs/devices/vidaa/

Do **not** confuse other TV operating systems' tools (Android ADB,
Samsung Tizen debugger, LG webOS screenshot APIs) with VIDAA capabilities.

## Safe probe implemented

Owner-initiated, manual branch only:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_v1
git pull --ff-only origin feat/manual-vidaa-tv-control
.\.venv\Scripts\python.exe -m jarvis.vidaa.manual --host 192.168.1.6 --mac 50:ba:02:ae:0d:18 --protocol-version 3290 --persist-tokens observe
```

- Uses existing authenticated, saved VIDAA pairing; never requests PIN.
- Queries TV state, TV info, device info, capabilities with short timeouts.
- Reports only allowlisted field names and constrained state enums, NOT
  raw device IDs, certificates, device details, account data, or tokens.
- Checks **only documented legacy ports 9226 and 9222**, each with short
  TCP timeout and a bounded read-only `GET /json/version` request. Does not execute JS,
  enable developer settings, scan other ports, download DOM, or collect
  browser page URLs.
- A positive CDP handshake would be a *candidate inspector endpoint*, not
  proof that the streaming app is inspectable or screen-readable.
- An unavailable legacy debug port does **not** prove software UI observation
  is impossible. Other licensed methods or device-supported APIs may exist.
- Always reports `software_ui_navigation_ready: false` until software UI
  observation and focus determination are separately implemented and
  accepted on the owner's TV.

## Acceptance stages

| Stage | Meaning | Status |
|---|---|---|
| L0 | Authenticated TV control | Owner-verified PASS |
| L1 | Read-only TV metadata (state/device/capability) | Owner-verified PASS |
| L2 | Read-only UI representation (screen image or per-app DOM/accessibility tree) | Unverified |
| L3 | Identify focused element/search field/profile from observations | Not built |
| L4 | Closed-loop choose key, observe changed UI, recover safely | Not built |
| L5 | Title-selection and **actual playback** verification across services | Not built |

If L2 is unavailable, do not mislabel status metadata as screen visibility
or silently switch to camera observations without owner approval. Research
legal, authorized application integration alternatives before changing
architecture.

## Security constraints

Only the owner's verified private-IP TV; no port sweeps, service exploit,
developer-mode toggling, credential extraction, unapproved logging,
DRM bypass, or content capture. Never access streaming account secrets
or private page data. Stop at payment/OTP/PIN screens; require owner
approval for sensitive user actions.

## Next owner checkpoint

Run one read-only `observe` command, report diagnostic JSON. From real
results decide whether a legitimate on-device screen/DOM path exists,
what app scope it covers, and how to build a safe closed-loop UI observer.
Do not demand a separate video walkthrough for each streaming app.

## Owner observation — 2026-10-12 (verified on physical U7N)

Owner ran `observe` against the previously paired TV at its confirmed LAN
address, and reported:

- Outcome: `software_observation_probe_complete`.
- `tv_state.status=metadata_received`, `state_type=app`.
- TV info, device info, capability metadata were all received.
- First documented legacy debug port 9226:
  `unreachable_or_no_response`; inspector not confirmed.
- Screenshot, UI tree, focused element, movie playback: all
  `not_observed`.
- `software_ui_navigation_ready=false`.

**Interpretation:** L1 successful; L2 remains blocked/unproven.
Knowing `statetype=app` does NOT identify the JioHotstar profile,
search field, focused element, playing title or playback verification.
Legacy inspector port 9226 failed to respond; it is not proof that all
software-only observation methods are impossible.

The follow-up implementation checks **only the second documented legacy
port 9222**, without enabling developer modes or inspecting proprietary
streaming content. If neither responds, do not ask for more arbitrary port
scans or pretend an app API provides screenshots. Prefer legitimate
manufacturer/developer-supported cross-app observation mechanisms if available.
If none exists, present tradeoffs and obtain owner approval before switching
to a different input source (e.g. PC browser output) or external observation.


## Owner follow-up — second legacy inspector and GitHub connectivity

Owner directly tested `http://192.168.1.6:9222/json/version` using a
read-only PowerShell HTTP request, which returned `No usable inspector
response` and `InspectorConfirmed=False`. Together with the prior
9226 result, **both publicly documented legacy inspector ports are
nonresponsive/unusable under the TV's present configuration**.

The first subsequent `git pull` failed with DNS resolution error
`Could not resolve host: github.com`. Owner then ran
`ipconfig /flushdns` and successfully fast-forward pulled
`feat/manual-vidaa-tv-control` from `f27c137f` to `e92a74f5`.
GitHub connectivity was restored. The direct HTTP 9222 check was
already performed and need not be repeated.

This does not establish that U7.6 has no supported debug interface.
Do not request repeated probes of 9222/9226 or arbitrary port scans.

## Remaining legitimate software-only option: authorized Ottium/DevTools

Vendor documentation establishes a narrower path worth evaluating:

- **Suitest** documents direct network screenshot support for
  `VIDAA - Ottium`, but *not* for `VIDAA - Instrumentation library`.
  Protected DRM content may not appear even in network screenshots.
  Source: https://suitest.net/docs/video-capture/line-screenshots/
- Ottium on VIDAA requires **DevTools enabled first** using VIDAA
  partner documentation; a paired ordinary consumer remote interface
  alone does not grant this feature.
  Source: https://suitest.net/docs/devices/vidaa/
- VIDAA applications may require app-specific Ottium support or owner/
  developer-controlled instrumentation. For store-installed apps, Suitest
  mentions the instrumentation requirement. This does **not** prove
  Netflix, JioHotstar, Prime Video or TV launcher DOM/screen capture.
  Source: https://suitest.net/docs/application/setting-up-vidaa-apps/
- VIDAA partner resources are access-controlled and developer-mode
  provisioning may be unavailable to retail U7.6 users.
  Source: https://www.vidaa.com/partner-support/
- Manufacturer/VIDAA support can be contacted to ask whether there is
  an **official read-only remote screen or accessibility API on the
  Hisense 55U7N VIDAA U7.6** available to end-user-authorized
  integrations, plus availability across built-in third-party apps.
  Source: https://www.vidaa.com/destek/

**Decision gate:** Request manufacturer/vendor clarification on *retail
U7.6 access and cross-app support* before committing JARVIS to
Ottium or an external testing service. Do not request secrets,
unlock hidden services, install instruments in third-party apps,
capture DRM video, or claim real-time TV observation without owner's
successful verified screen/focus observation.

**Current acceptance:** L0 control PASS, L1 metadata PASS, L2 actual
screen/focus observation NOT AVAILABLE via tested interfaces, L3-L5
not implemented. The existing `observe` CLI and tests remain a
safe diagnostic; it is not a navigation engine.
