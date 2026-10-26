import assert from 'node:assert/strict';
import test from 'node:test';
import { isFresh, parseSnapshot } from './hudState.ts';

test('unavailable backend stays visibly disconnected', () => {
  const state = parseSnapshot(null);
  assert.equal(state.connected, false);
  assert.equal(state.voice, 'offline');
  assert.deepEqual(state.work, []);
  assert.deepEqual(state.health, []);
});

test('canonical voice and typed work pass through without command payload', () => {
  const state = parseSnapshot({
    schema: 1,
    connected: true,
    voice: { state: 'speaking', transcript: 'private' },
    work: [{ type: 'research', state: 'running', payload: 'private' }],
    health: [{ component: 'voice.runtime', state: 'healthy', secret: 'key' }],
    vision: { state: 'active', camera: 'do not show' },
  });
  assert.deepEqual(state.work, [{ type: 'research', state: 'running' }]);
  assert.deepEqual(state.health, [{ component: 'voice.runtime', state: 'healthy' }]);
  assert.equal(state.voice, 'speaking');
  assert.equal(state.vision, 'active');
  assert.equal(JSON.stringify(state).includes('private'), false);
});

test('unknown data, unexpected schema, and stale connection never render live', () => {
  assert.equal(parseSnapshot({ schema: 5, connected: true, voice: { state: 'speaking' } }).connected, false);
  assert.equal(parseSnapshot({ schema: 1, connected: true, voice: { state: 'admin' } }).connected, false);
  assert.equal(isFresh(1000, 9000), true);
  assert.equal(isFresh(1000, 12001), false);
  assert.equal(isFresh(null, 1000), false);
});
