# Mark I Reactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan. TDD and verification-before-completion govern all tasks.

**Spec:** `docs/superpowers/specs/2026-10-26-mark-i-reactor-design.md`

**Goal:** Keep the existing JARVIS HUD and bridge, but remodel the reactor as
an industrial Mark I replica that can ship as offline built assets.

**Global constraints:** No voice/backend contract changes, external model
download, new dependency, new permissions, or GPU-only functionality.

**Review focus:** (1) no accidental mesh rotation; (2) outer coil count and
positions; (3) legible blue/white emitter; (4) fallback still useful without
WebGL; (5) no changes to unrelated packaged assets or runtime features.

---

### Task 1: Extract and test the Mark I detail layout

**Files:** Create `frontend/jarvis-hud/src/markIReactor.ts`,
`frontend/jarvis-hud/src/markIReactor.test.ts`; modify
`frontend/jarvis-hud/package.json`.

**Interfaces:** `MARK_I_BUNDLE_COUNT`, `MARK_I_TURNS_PER_BUNDLE`,
`getMarkICoilTransforms()`, `getMarkIFastenerPositions()`.

- [ ] Write Node tests asserting ten coil groups, dense symmetric winding
      placement at the housing radius, distinct fasteners and no 3D-only
      dependency, then run `npm test` to observe the missing module failure.
- [ ] Implement geometry coordinates as deterministic, pure TypeScript;
      include test in npm's test command.
- [ ] Run `npm test` and `npm run typecheck`; commit the focused change.

### Task 2: Remodel the 3D and low-GPU reactor

**Files:** Modify `frontend/jarvis-hud/src/components/ArcReactor.tsx` and
`frontend/jarvis-hud/src/components/ReactorFallback.tsx`.

**Consumes:** Task 1's static layout helpers.

- [ ] Write a red test for a pure Mark I configuration invariant needed by
      the view (static housing, defined annular light radii), run it red.
- [ ] Add the invariant and use it; install rough dark steel and aluminum
      housings, layered stepped rings, exposed coil retainers, radial supports,
      fasteners, a detailed recessed emitter, and emissive diffusers. Remove
      continuous assembly/shroud rotation but retain light-state changes.
- [ ] Update CSS fallback to show the ten-pack and ring-based construction.
- [ ] Run `npm test` and `npm run build`; commit the source change.

### Task 3: Bundle, inspect, and verify

**Files:** Generated `src/jarvis/ui/assets/` and related bundle manifest;
update `docs/JARVIS_HYBRID_HUD.md` with visual acceptance notes.

- [ ] Build the production bundle and confirm no remote geometry dependence.
- [ ] Run `npm test`, `npm run build`, Python UI tests if available, and check
      git diff to ensure the runtime bridge was not edited.
- [ ] Commit generated assets; leave merge to owner approval.

