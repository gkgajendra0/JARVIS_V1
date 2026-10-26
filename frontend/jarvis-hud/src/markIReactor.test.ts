import assert from 'node:assert/strict';
import test from 'node:test';
import {
  MARK_I_BUNDLE_COUNT,
  MARK_I_TURNS_PER_BUNDLE,
  getMarkICoilTransforms,
  getMarkIFastenerPositions,
  getMarkIEmitterRings,
  getMarkIBraceAngles,
} from './markIReactor.ts';

test('Mark I windings have ten individually packed, evenly spaced copper bundles', () => {
  const turns = getMarkICoilTransforms();
  assert.equal(MARK_I_BUNDLE_COUNT, 10);
  assert.ok(MARK_I_TURNS_PER_BUNDLE >= 10);
  assert.equal(turns.length, MARK_I_BUNDLE_COUNT * MARK_I_TURNS_PER_BUNDLE);

  for (let bundle = 0; bundle < MARK_I_BUNDLE_COUNT; bundle++) {
    const pack = turns.filter((turn) => turn.bundleIndex === bundle);
    assert.equal(pack.length, MARK_I_TURNS_PER_BUNDLE);
    assert.equal(new Set(pack.map((turn) => turn.turnIndex)).size, MARK_I_TURNS_PER_BUNDLE);
    for (const turn of pack) {
      const radius = Math.hypot(turn.position[0], turn.position[1]);
      assert.ok(Math.abs(radius - 2.46) < 0.001);
      assert.equal(turn.position[2], 0.05);
    }
    const start = pack[0].angle;
    const end = pack[pack.length - 1].angle;
    assert.ok(Math.abs((start + end) / 2 - (bundle * Math.PI * 2) / 10) < 1e-10);
  }
});

test('front-face bolt pattern has pairs of independent hardware around the steel rim', () => {
  const bolts = getMarkIFastenerPositions();
  assert.equal(bolts.length, MARK_I_BUNDLE_COUNT * 2);
  assert.equal(new Set(bolts.map(({ angle }) => angle.toFixed(5))).size, bolts.length);
  for (const bolt of bolts) {
    assert.ok(Math.abs(Math.hypot(bolt.position[0], bolt.position[1]) - 3.06) < 0.001);
    assert.equal(bolt.position[2], 0.74);
  }
});

test('Mark I emitter has concentric rings within the coil envelope and fixed structural braces', () => {
  const rings = getMarkIEmitterRings();
  assert.ok(rings.length >= 3);
  assert.ok(rings.every((ring) => ring > 0.8 && ring < 2));
  assert.ok(rings.every((ring, i) => i === 0 || ring > rings[i - 1]));

  const braces = getMarkIBraceAngles();
  assert.equal(braces.length, 3);
  assert.ok(braces.every((angle, i) => Math.abs(angle - (i * Math.PI * 2) / 3) < 1e-10));
});
