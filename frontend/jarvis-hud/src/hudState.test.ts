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
    schema: 2,
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
  assert.equal(parseSnapshot({ schema: 2, connected: true, voice: { state: 'admin' } }).connected, false);
  assert.equal(isFresh(1000, 9000), true);
  assert.equal(isFresh(1000, 12001), false);
  assert.equal(isFresh(null, 1000), false);
});

test('connected HUD preserves background work during voice outage', () => {
  const state = parseSnapshot({
    schema: 2, connected: true, voice: { state: 'offline' },
    work: [{
      id: 'work_1111111111111111', type: 'research', state: 'waiting_for_owner',
      progress: 70, approximate: true, milestone: 'evidence_gathered',
      eta_low_seconds: null, eta_high_seconds: null, request: 'private work request',
    }],
    features: { work: 'ready', memory: 'disabled', extra: 'private status' },
    models: { voice: { name: 'gemini', model: 'gemini-3.8-live', api_key: 'private' } },
    vision: { state: 'active', people: 3, target: 'visible', frame: 'private' },
    health: [{ component: 'voice.runtime', state: 'warning' }],
    activity: [{ id: 1, at: '2026-10-26T10:11:12Z', kind: 'research', state: 'web_researched', label: 'WEB RESEARCH', query: 'private' }],
  });
  assert.equal(state.connected, true);
  assert.equal(state.voice, 'offline');
  assert.equal(state.attentionCount, 1);
  assert.equal(state.work[0].progress, 70);
  assert.equal(state.work[0].milestone, 'evidence_gathered');
  assert.equal(state.models.voice?.model, 'gemini-3.8-live');
  assert.equal(state.features.memory, 'disabled');
  assert.equal(state.visionPeople, 3);
  assert.equal(state.visionTarget, 'visible');
  assert.equal(state.health[0].state, 'warning');
  assert.equal(state.activity[0].label, 'WEB RESEARCH');
  assert.equal(JSON.stringify(state).includes('private'), false);
});

test('malformed activity, milestone, provider, and counts are ignored', () => {
  const state = parseSnapshot({
    schema: 2, connected: true, voice: { state: 'standby' },
    work: [{ type: 'development', state: 'running', milestone: 'private_password', progress: 700 }],
    features: { memory: 'private', work: 'disabled' },
    models: { voice: { name: 'private key with spaces' } },
    vision: { state: 'active', people: 999, target: 'secret' },
    activity: [{ id: 1, at: '2026-10-26T10:11:12Z', kind: 'voice', state: 'accepted', label: 'private token' }],
  });
  assert.deepEqual(state.work, [{ type: 'development', state: 'running' }]);
  assert.equal(state.features.work, 'disabled');
  assert.equal(state.features.memory, undefined);
  assert.equal(state.models.voice, undefined);
  assert.equal(state.visionPeople, null);
  assert.equal(state.visionTarget, 'unknown');
  assert.deepEqual(state.activity, []);
});

test('vision reports following without claiming owner verification', () => {
  const state = parseSnapshot({
    schema: 2, connected: true, voice: { state: 'standby' },
    vision: { state: 'active', people: 1, target: 'following' },
  });
  assert.equal(state.visionTarget, 'following');
});

test('durable route decision appears only on its specific Work item', () => {
  const state = parseSnapshot({
    schema: 2, connected: true, voice: { state: 'standby' },
    work: [{
      id: 'work_2222222222222222', type: 'development', state: 'running',
      model_target: 'chatgpt_plan:gpt-6-astra', hidden_token: 'private',
    }],
  });
  assert.equal(state.work[0].modelTarget, 'chatgpt_plan:gpt-6-astra');
  assert.equal(JSON.stringify(state).includes('private'), false);
});

test('stale vision signal cannot retain apparent live target', () => {
  const state = parseSnapshot({
    schema: 2, connected: true, voice: { state: 'standby' },
    vision: { state: 'active', frame: 'stale', target: 'following', people: 1 },
  });
  assert.equal(state.visionFrame, 'stale');
  assert.equal(state.visionTarget, 'unknown');
  assert.equal(state.visionPeople, null);
});
