# JARVIS V1 Current Architecture

This document describes **only architecture that actually exists and has been accepted** in the current V1 repository. Future systems belong in `PRODUCT.md` and `ROADMAP.md`, not here.

## Current Accepted Baseline

Repository baseline commit:

`c626d863b5be7821da467175a0c466fdd90ca185` — `Bootstrap clean JARVIS V1 foundation`

Current runtime is intentionally minimal.

```text
python -m jarvis
    |
    v
JarvisConfig.from_environment()
    |
    v
configure_logging(...)
    |
    v
JarvisApp()
    |
    +--> start()
    |
    +--> stop()
```

## Current Components

### `src/jarvis/app.py`

`JarvisApp` is the current application composition/lifecycle root.

Current responsibility:

- own the minimal synchronous application lifecycle;
- expose running/stopped state;
- perform no model, audio, network, memory, or capability work.

### `src/jarvis/config.py`

`JarvisConfig` owns the currently supported environment-backed application configuration.

Current configuration is intentionally small: logging level only.

### `src/jarvis/logging_config.py`

Owns basic console logging setup.

### `src/jarvis/__main__.py`

Owns the current CLI entrypoint for `python -m jarvis` and composes configuration, logging, and `JarvisApp` lifecycle.

### `src/jarvis/__init__.py`

Exposes the current small public package surface without side-effectful provider/audio/model imports.

## Current Runtime Dependencies

There are no production runtime dependencies beyond Python standard-library code in the baseline.

The development/test dependency is pytest.

## Current State Ownership

At the current baseline:

- application lifecycle state -> `JarvisApp`;
- environment configuration -> `JarvisConfig`;
- logging setup -> `logging_config`;
- conversation state -> not implemented;
- personal context -> not implemented;
- persistent memory -> not implemented;
- authority/permission state -> not implemented;
- capability runtime -> not implemented;
- knowledge/research runtime -> not implemented;
- voice/audio runtime -> not implemented;
- UI/HUD -> not implemented.

## Current Invariants Proven by Tests

The baseline tests establish that:

- the app can be constructed stopped;
- start/stop transitions are stable and idempotent;
- package import has no network/audio/model import side effects;
- no blocked external provider/audio/model modules are pulled in by importing the package.

## Architecture Update Rule

This file changes only after a product slice has been implemented, validated, and accepted.

Do not pre-document speculative Step-2/Step-10/etc. architecture here. If Step 1 later introduces `ConversationSession`, an interaction service, and provider adapters, they are added here only after that architecture is actually accepted.
