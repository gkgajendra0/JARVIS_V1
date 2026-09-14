# Pocket 3 BLE Startup Acceptance — 2026-09-14

Status: **ACCEPTED**

PR: **#40**

Protected-main merge: `fcb87500b0cf7e431f9f76077aa1fad8234db53f`

## Problem closed

Pocket 3 native tracking could work correctly after connection but intermittently miss the first startup pairing response. A long failed attempt could also make reconnect timing ineffective because its cooldown had started before the attempt finished.

## Accepted startup sequence

1. Subscribe to FFF4 notifications.
2. Require a valid inbound DUML frame as evidence that the Pocket control service is ready.
3. Send the existing session wake.
4. Preserve the hardware-proven 0.4 second settle.
5. Arm pairing.
6. Preserve the 0.2 second settle.
7. Send the existing JARVIS pairing message.
8. Obtain Pocket Wi-Fi details.
9. Wake the Pocket Wi-Fi AP and preserve the accepted 2 second settle.
10. Continue into the existing Windows Wi-Fi, TCP/UDP, A6 and native tracking path.

## Accepted recovery behavior

- BLE readiness, pairing and Wi-Fi-detail waits unwind when JARVIS is stopping.
- One synchronous BLE provisioning batch is bounded to two attempts.
- Reconnect cooldown starts when a failed attempt actually finishes.
- A slow successful connection discards the old pre-connection frame; OWNER targeting resumes on a fresh vision frame.
- A6 target semantics, native tracking trust and post-provisioning transport behavior are unchanged.

## Acceptance evidence

Owner-machine startup produced the intended sequence: BLE protocol ready, Wi-Fi AP settle, native datalink ready, native owner transport connected, A6 direct acknowledgement, trusted native lock, then successful startup greeting.

The exact PR #40 head passed the repository CI before merge.
