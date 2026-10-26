# JARVIS Hybrid Holographic HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an opt-in read-only React/WebGL JARVIS HUD built from the two selected repositories, without replacing the production Python runtime.

**Architecture:** A Vite SPA packaged in `src/jarvis/ui/assets` consumes a bounded local HTTP snapshot. Existing runtime owners furnish status through an optional provider; no frontend voice/AI/memory commands are imported.

**Tech Stack:** Python 3.11+ stdlib server; React 18, TypeScript, Vite, Three/R3F, Framer Motion, Tailwind; pytest, Vitest, Playwright smoke.

**Spec:** `docs/superpowers/specs/2026-10-26-hybrid-hud-design.md`

## Global Constraints

- `JARVIS_V1` stays the runtime source of truth and has no active UI on `main`.
- The rejected PR #297 visuals are excluded; only #1/#2 MIT-licensed visual source is adapted with notices.
- Bind HTTP only to `127.0.0.1` and expose GET/HEAD only, never secrets or transcripts.
- Runtime integration is opt-in; failures must not affect LiveKit voice or Work.
- Do not merge protected main without owner Windows acceptance.

## Review Focus

1. Forged Host/path/POST requests must not access private content or execute anything.
2. Runtime absence/restart must show disconnected rather than fabricated live status.
3. Oversized/unexpected backend data must be omitted from the public projection.
4. WebGL failure/reduced motion must leave a usable HUD.
5. Lifecycle from standby through speech/recovery must not attach a second microphone.

---

### Task 1: Local read-only projection and HTTP boundary

**Files:** Create `src/jarvis/ui/hub.py`, `server.py`, `__init__.py`; test `tests/test_hybrid_ui.py`.

**Interfaces:** `UISnapshotHub.snapshot() -> dict`, `create_ui_server(hub, port=8765) -> ThreadingHTTPServer`.

- [x] Write tests for disconnected initial snapshot, bounded voice/work/health/vision, Host/path/verb rejection.
- [x] Run tests and confirm RED before implementation.
- [x] Implement hub with provider isolation and a stdlib static/API server.
- [x] Run tests GREEN; commit.

### Task 2: Opt-in production status wiring and standalone CLI

**Files:** Create `src/jarvis/ui/runtime.py`, `__main__.py`; modify `src/jarvis/voice/canonical_active_speaker_runtime.py`, `src/jarvis/voice/production_runtime.py`, `pyproject.toml`; extend test.

**Interfaces:** `start_ui_if_enabled(voice_runtime, work_runtime, self_awareness) -> UIService | None`; `UIService.close()`; `presentation_voice_state` property.

- [x] Add tests proving default-off, independent UI failure, real-state mapping; confirm RED.
- [x] Implement lifecycle-aware snapshot provider, standalone CLI and optional startup/shutdown hooks.
- [x] Run focused tests GREEN and commit.

### Task 3: Hybrid React HUD frontend

**Files:** Create `frontend/jarvis-hud` Vite project with imported/adapted #1 reactor scene and #2 HUD shell, state projection, tests and CSS; `THIRD_PARTY_NOTICES.md`.

**Interfaces:** `/api/snapshot` schema 1; `resolveHudState(snapshot)` pure mapping; browser polls read-only and handles disconnection.

- [x] Write Node native test failures for status mapping, stale data and privacy/redaction; confirm RED.
- [x] Adapt #1 reactor files, #2 geometric HUD layout/cards, compose a responsive/accessible UI. Remove donor chat/STT/TTS/LLM/memory/mock telemetry.
- [x] Run Node tests, typecheck and production build. (No Vitest dependency needed.)

### Task 4: Packaging and visual/runtime smoke

**Files:** Modify package data / static-serving logic as necessary; create packaged `src/jarvis/ui/assets`, README runbook and screenshot smoke.

**Interfaces:** `jarvis-ui --open-browser` starts offline preview without cloud dependencies; `JARVIS_UI_ENABLED=true jarvis-voice` serves live read-only HUD.

- [x] Add tests proving a GET-only origin-checked server and packaged assets; confirm RED.
- [x] Build/copy the offline static bundle, run CLI/API and capture wheel package contents.
- [ ] Capture Playwright screenshots at 3440x1440, 1920x1080 and 390x844 on GitHub Actions (local browser download failed).
- [x] Run focused integration tests, pinned Ruff checks, and review diff against spec. Full suite collection blocked locally by missing heavy runtime dependencies.
- [ ] Commit/push feature branch and open a draft PR; leave protected main untouched.
