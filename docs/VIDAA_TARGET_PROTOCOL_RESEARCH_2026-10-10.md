# VIDAA local-control candidates — offline research only (2026-10-10)

**Status: unverified external leads, not target attestation or execution authority.**

Original GICC owner objective: control *the actual owner television* and
continue the original movie request after an approved capability is built.
The original Roku ECP architecture is incompatible with an unverified VIDAA
target; no Roku endpoint, port, app ID, login or external control permission
may be guessed from model text or project documentation.

## Findings from independent community implementations

1. [vidaa-control](https://github.com/tombabolewski/vidaa-control)
   (Python library / Home Assistant integration) documents local MQTT **over
   TLS**, commonly using TCP 36669; SSDP/UDP discovery; firmware-generation
   detection; TV-screen PIN pairing; app enumeration and launch; remote keys.
   These are library claims, not official proof that the owner's U7N accepts
   those operations or that Hotstar is launchable by identifier.
2. [ha-vidaa-tv](https://github.com/techmarkai/ha-vidaa-tv)
   documents a **plain MQTT, no PIN** path on the same port for other VIDAA
   deployments. That directly conflicts with a universal TLS/PIN assumption.
   A different remote-control implementation or older firmware may behave
   differently. Its embedded service credentials must **not** become a
   fallback in JARVIS without separate security review and owner permission.
3. [vidaa-control protocol notes](https://github.com/tombabolewski/vidaa-control/blob/main/docs/PROTOCOL.md)
   describe firmware-dependent topics, token issuance, and restrictions on
   wildcard subscriptions. This does **not** establish a supported protocol
   on the owner's specific hardware or any authenticated command result.

## Governed acquisition implications

- **Discovery protocol is not control protocol.** UPnP/DNS-SD/SSDP sightings
  from Windows do not establish MQTT service reachability, authentication,
  or compatibility. They remain unverified hints in GICC.
- **No blind transport fallback.** Never silently try unsecured MQTT,
  service passwords, broadcast scans, or new endpoints when TLS,
  authentication, model proof or pairing fails. Require separate reviewed
  scopes and explicit owner authorization for any later probe/pairing.
- **Canonical target evidence.** Verify model/firmware on the actual
  identified entity, then inspect the supported control protocol through
  approved methods before selecting/adapting a target-specific SDK. Preserve
  concrete protocol and evidence provenance as append-only reviewed data.
- **Device-control proof.** After permitted pairing, query the app inventory
  and verify the actual local Hotstar application rather than assuming a
  preloaded ID. A remote-key response alone does not verify playback.
  The final user goal needs genuine observed on-screen/app/playback effect.
- **Security.** Never print tokens/PINs or save them in general goal logs;
  use the existing secret storage and AuthorityService/permit gates. No
  code in this research note authorizes a network connection.
- **Offline tests.** Add conflicting TLS/plain and PIN/no-PIN observations,
  no-app-found, wrong-device, stale-credential and false-positive playback
  cases to acquisition verification before owner-machine acceptance.

## Explicitly outstanding

At this checkpoint there is **no corroborated live owner-TV protocol,
firmware, authenticated session, Hotstar launch identifier or playback
effect**. The normal user should not have to type an IP address, download
a debug utility or choose a protocol; JARVIS should discover and research
through approved bounded methods, asking the owner only for genuine
permission, pairing and physical confirmation.
