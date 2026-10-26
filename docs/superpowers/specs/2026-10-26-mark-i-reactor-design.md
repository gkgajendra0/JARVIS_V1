# Mark I Reactor Visual Refresh — Design

## Intent

The owner selected **Option A**, the rough, cave-built circular arc reactor
from *Iron Man* (2008), for the existing JARVIS hybrid HUD. The goal is a
recognisable physical prop with credible materials and exposed construction,
not a generic animated science-fiction emblem.

## Scope

- Preserve JARVIS's existing Python/LiveKit runtime, read-only bridge, layout,
  state mappings, camera orbit, and GPU fallback controls.
- Keep the housing circular and relatively static. Ten densely wound copper
  coil packs, visible winding retainers, bolts, braces, stepped steel housings,
  dark recesses, fine central grille and concentric blue-white diffusers supply
  the screen-prop character.
- Favor rough blackened steel, brushed aluminum, and warm copper over shiny
  chrome. Add restrained mechanical detail and soft light falloff; state and
  audio may vary emission, but no permanent spinning ring/rotor.
- Keep offline bundled geometry/materials; no remote assets or copyrighted
  textures. Support low-GPU and reduced-motion modes with matching schematic.
- Keep acceptable frame time: reuse common geometry, avoid per-frame mesh
  allocations, and retain the existing capped canvas DPR.

## Approaches considered

1. **Mark I cave-built (selected):** exposed coil windings and irregular
   industrial detailing; best matches the requested original movie device.
2. **Mark II polished circular:** polished enclosure and cleaner engineering,
   but it loses the improvised 2008 look.
3. **Later triangular reactor:** substantially different movie generation,
   explicitly not the owner's selected original.

## Acceptance

- Ten copper packs with multiple turns and supporting structure, perceptible
  emitter ring/grille, a non-rotating housing, and visible depth on camera orbit.
- Power colors still follow existing `idle`, `listening`, `thinking`, `speaking`.
- The fallback mirrors ten packs and the concentric emitter, without WebGL.
- Typecheck/build, Node unit tests and available Python UI tests are green.
- The committed static bundle allows Windows to preview without Node.

This is a geometry/material reinterpretation of the 2008 prop, not a licensed
film mesh, and the user must visually accept it before merge.
