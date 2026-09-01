# ADR-012 — Persistent Machine Configuration and Startup Preflight

**Status:** Accepted — implementation integrated, real-machine startup acceptance pending  
**Date:** 2026-09-01

## Context

JARVIS had accumulated a large set of environment-variable prerequisites for normal startup: wake-model paths, audio devices, provider selection, vision switches, speaker-shadow switches, and active-speaker model paths. During development these values were repeatedly reconstructed in PowerShell and some audio devices were stored as volatile PortAudio numeric indexes.

That operating model is not acceptable for a personal assistant. Normal use must not depend on remembering chat history or reproducing a long block of shell configuration before every launch.

The Windows audio work also proved that PortAudio indexes are unstable when devices/default endpoints change. A persisted `index:N` is therefore not a machine identity.

A first real-machine startup acceptance attempt exposed a second configuration problem: the persisted machine profile correctly selected the NVIDIA/TV output, but the launching process still inherited an old Tribit `JARVIS_AUDIO_OUTPUT_DEVICE` value. Because the initial implementation let ambient `JARVIS_*` environment values override the persisted profile automatically, preflight selected the stale Bluetooth value and blocked startup. This proved that normal operation cannot treat inherited runtime variables as higher priority than an accepted machine profile.

## Decision

Adopt a two-class configuration model.

### Non-secret machine configuration

Persist machine-specific, non-secret JARVIS settings in a local JSON profile:

```text
%LOCALAPPDATA%\JARVIS\machine.json
```

The location may be overridden with `JARVIS_MACHINE_CONFIG` for diagnostics/tests.

The file has a schema version and an explicit allow-list. It may contain stable audio selectors, model paths, provider choice, and feature switches. It may not contain provider API keys or arbitrary environment variables.

### Secrets

Provider credentials remain outside the machine JSON and are read only from the process/Windows user environment:

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`

### Configuration precedence

For persisted non-secret JARVIS runtime settings, the machine profile is authoritative by default.

Normal precedence is:

```text
persisted machine setting
        ↓
process environment value only when the setting is absent
        ↓
default
```

A process may deliberately override an existing persisted machine setting only by explicitly enabling:

```text
JARVIS_RUNTIME_ENV_OVERRIDES=true
```

This opt-in diagnostic mode preserves targeted development overrides without allowing stale inherited variables to silently replace accepted machine state.

`JARVIS_MACHINE_CONFIG` remains a direct environment-controlled path selector because it chooses which machine profile is loaded rather than representing a persisted runtime setting.

Provider API keys remain normal environment-only secrets and are not affected by this precedence rule.

Legacy persistent non-secret `JARVIS_*` overrides should still be removed after migration so the Windows user environment remains clean, but stale values inherited by an already-running parent process can no longer break normal startup.

### Stable audio identity

`jarvis-setup` never persists PortAudio numeric indexes. It persists the already-supported stable selector form:

```text
name:<device friendly name>|hostapi:<PortAudio host API name>
```

On the current machine the intended production roles are:

- Pocket3 microphone, 48 kHz;
- NVIDIA/TV conversation output, 48 kHz.

Setup automatically prefers those known roles when uniquely detected. If it cannot safely infer a device, it presents only 48-kHz-compatible candidates for explicit selection.

### Managed LR-ASD asset

When Step-3 active-speaker shadow is enabled, `jarvis-setup` must not require the operator to manually locate or manage the LR-ASD checkpoint.

The accepted first active-speaker model is the official LR-ASD AVA checkpoint from the pinned upstream commit already recorded by the provider:

- file: `weight/pretrain_AVA.model`;
- upstream commit: `1b6dcd2d8fc2895683de6508ec6294ec47d388ca`;
- expected size: `3,426,337` bytes;
- expected Git blob SHA-1: `d724be582f6d34f1b099657235dedafa0668fd82`.

If no valid configured checkpoint exists, setup downloads that exact pinned asset into the local JARVIS model cache, verifies byte count and Git-blob identity before atomic promotion, and persists the resulting local path. A mismatched/tampered download fails closed.

### One-time setup command

Add:

```text
jarvis-setup
```

The command:

1. reuses valid stable existing settings;
2. ignores legacy `index:N` audio selectors;
3. validates the required wake model and automatically resolves the pinned LR-ASD asset when active-speaker shadow is enabled;
4. detects 48-kHz input/output devices;
5. records vision/speaker/active-speaker feature choices;
6. persists the non-secret machine profile;
7. runs startup preflight immediately.

`jarvis-setup --show` displays the persisted non-secret machine profile.

### Startup preflight

Every production `jarvis-voice` launch runs one consolidated preflight before opening the runtime. It reports all detected startup problems in one pass rather than failing sequentially through tracebacks.

Initial required checks include:

- wake model exists;
- selected realtime provider credential exists;
- configured conversation microphone resolves and accepts 48 kHz;
- configured conversation output resolves and accepts 48 kHz;
- speaker/vision feature dependencies are valid;
- LR-ASD model exists when active-speaker shadow is enabled.

A failed preflight blocks startup and tells the operator to run/fix `jarvis-setup`.

### One production voice entrypoint

`jarvis-voice` and the child process launched by `jarvis-dev` must execute the same module:

```text
jarvis.voice.production_runtime
```

`jarvis-dev` adds update/restart supervision only; it is not a separate voice architecture.

## Intended normal operation

After one-time setup and migration:

```powershell
cd C:\Users\gkgaj\Desktop\jarvis_v1
.\.venv\Scripts\Activate.ps1
jarvis-voice
```

Development-supervised operation after the active branch is merged to the configured supervisor branch:

```powershell
jarvis-dev
```

No routine wake-path, device-index, vision, or model-path shell reconstruction is required.

## Rejected alternatives

### Continue environment-only configuration

Rejected for normal operation. Environment overrides remain useful for diagnostics, but making them the sole durable machine state caused repeated startup friction and made operation depend on external notes/chat history.

### Ambient environment always overrides machine profile

Rejected after real-machine acceptance failure. A stale inherited Tribit selector overrode the correctly persisted NVIDIA/TV selector and blocked startup. Diagnostic overrides must therefore be explicit rather than ambient.

### Commit a `.env` file

Rejected. It creates secret-handling risk, encourages machine-specific repository state, and conflicts with the requirement that the repository stay clean and portable.

### Persist PortAudio indexes

Rejected. Real Windows testing demonstrated index drift when devices/default endpoints changed.

### Silently auto-select any available speaker

Rejected. Conversation AEC is only accepted on a 48-kHz output path; silently falling back to the 44.1-kHz Tribit Bluetooth endpoint would reintroduce the proven self-echo failure.

### Require manual LR-ASD checkpoint management

Rejected. The active-speaker provider already pins an exact official upstream checkpoint identity, so making normal setup depend on a remembered path creates unnecessary operator state. Setup owns acquisition and integrity verification of that non-secret model asset.

## Consequences

- Machine setup becomes an explicit product surface rather than chat/manual shell knowledge.
- Local non-secret configuration survives shell restarts and repo updates.
- API keys remain outside repository/local machine JSON.
- Startup errors become consolidated and actionable.
- Persisted machine state is protected from stale ambient runtime variables.
- Explicit `JARVIS_RUNTIME_ENV_OVERRIDES=true` remains available for deliberate diagnostics.
- Future hardware changes should be handled by rerunning `jarvis-setup`, not editing source code.
- The pinned LR-ASD checkpoint is automatically managed like other model assets rather than becoming another manual startup prerequisite.

## Acceptance gate

Before this ADR is marked fully human-accepted on the current PC:

1. install the updated editable package;
2. run `jarvis-setup` and confirm it persists stable Pocket3 + TV selectors and an integrity-verified local LR-ASD model path;
3. confirm legacy Windows User `JARVIS_*` runtime overrides are removed where present;
4. run `jarvis-voice` without manually setting JARVIS runtime configuration variables, even if the launching parent process still contains stale inherited values;
5. confirm startup preflight uses the persisted Pocket3 + TV configuration and the production runtime starts;
6. confirm `jarvis-dev` launches the same production runtime when tested on its configured branch.
