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
2. VIDAA's *older U4* WebApp technical guide describes an application
   remote debugging service at `http://TV_IP:9226` after developer mode
   has been enabled. This is web-app inspection, not a guaranteed general
   screenshot service and not proof of access to proprietary streaming apps.
   Source: https://www.vidaa.com/wp-content/uploads/2020/12/WebApp_Development_Guide_for_VIDAA.pdf
3. The separate VIDAA application-testing vendor Suitest supports some
   device-specific developer inspection in partner/testing setups and
   requires device setup; this doesn't establish unprivileged full-screen
   access on the owner's modern U7N.
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
- Checks **only documented legacy port 9226**, with short TCP timeout and
  a bounded read-only `GET /json/version` request. Does not execute JS,
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
| L1 | Read-only TV metadata (state/device/capability) | Await owner probe |
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
