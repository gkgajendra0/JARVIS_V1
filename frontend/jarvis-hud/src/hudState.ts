/** Strict browser-facing projection: never spread arbitrary API objects. */
export type VoiceState = 'offline' | 'standby' | 'activating' | 'listening' | 'thinking' | 'speaking' | 'recovering';
export type WorkRow = {
  type: string; state: string; id?: string; progress?: number; approximate?: boolean;
  milestone?: string; etaLowSeconds?: number; etaHighSeconds?: number; modelTarget?: string;
};
export type HealthRow = { component: string; state: string };
export type FeatureKey = 'work' | 'vision' | 'memory' | 'learning' | 'hands' | 'research' | 'personal_context';
export type FeatureStatus = 'ready' | 'disabled' | 'unavailable' | 'degraded';
export type ModelRole = 'voice' | 'research' | 'work';
export type ModelSummary = { name: string; model?: string };
export type ActivityEvent = { id: number; at: string; kind: 'voice' | 'research' | 'capability'; state: string; label: string };
export type HudState = {
  connected: boolean; voice: VoiceState; work: WorkRow[]; health: HealthRow[];
  vision: 'offline' | 'standby' | 'active'; visionPeople: number | null;
  visionFrame: 'unknown' | 'fresh' | 'stale' | 'pending';
  visionTarget: 'unknown' | 'searching' | 'visible' | 'following';
  features: Partial<Record<FeatureKey, FeatureStatus>>;
  models: Partial<Record<ModelRole, ModelSummary>>;
  activity: ActivityEvent[]; attentionCount: number;
};

const VOICE: ReadonlySet<string> = new Set(['offline', 'standby', 'activating', 'listening', 'thinking', 'speaking', 'recovering']);
const WORK_TYPES: ReadonlySet<string> = new Set(['development', 'research', 'diagnostics', 'hands', 'monitoring', 'reminder', 'generic', 'external_acceptance']);
const WORK_STATES: ReadonlySet<string> = new Set(['queued', 'running', 'waiting_resource', 'waiting_dependency', 'waiting_until', 'waiting_for_owner', 'paused', 'retrying', 'completed', 'failed', 'cancelled']);
const MILESTONES: ReadonlySet<string> = new Set([
  'evidence_gathered', 'gathering_evidence', 'provider_pressure_before_evidence', 'queued', 'preparing_evidence',
  'isolated_commit_ready', 'diff_verified', 'tests_passed', 'implementation_written', 'repository_inspected',
  'workspace_prepared', 'preparing_workspace', 'advancing_recorded_steps', 'completed', 'failed', 'cancelled',
]);
const HEALTH_STATES: ReadonlySet<string> = new Set([
  'unknown', 'starting', 'healthy', 'degraded', 'failed', 'recovering', 'disabled',
  'unhealthy', 'unavailable', 'ok', 'warning', 'critical', 'stale',
]);
const FEATURE_KEYS: FeatureKey[] = ['work', 'vision', 'memory', 'learning', 'hands', 'research', 'personal_context'];
const FEATURE_STATES: ReadonlySet<string> = new Set(['ready', 'disabled', 'unavailable', 'degraded']);
const MODEL_ROLES: ModelRole[] = ['voice', 'research', 'work'];
const MODEL_TOKEN = /^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,79}$/;
const WORK_ID = /^work_[0-9a-f]{16}$/;
const COMPONENT = /^[a-zA-Z0-9_.:-]{1,48}$/;
const EVENT_AT = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;
const EVENT_LABELS: ReadonlySet<string> = new Set([
  'USER TURN', 'ASSISTANT REPLY', 'WEB RESEARCH', 'BROWSER ACTION',
  'FILE ACTION', 'SYSTEM ACTION', 'CAPABILITY ACTION',
]);
const EVENT_STATES: ReadonlySet<string> = new Set([
  'accepted', 'interrupted', 'succeeded', 'partial', 'denied', 'invalid', 'unavailable', 'failed',
  'web_researched', 'multi_source_researched', 'authoritative_source_present',
  'insufficient_evidence', 'research_unavailable',
]);
const EVENT_KINDS: ReadonlySet<string> = new Set(['voice', 'research', 'capability']);
const MAX_STALE_MS = 10_000;

export const disconnected: HudState = {
  connected: false, voice: 'offline', work: [], health: [], vision: 'offline', visionPeople: null,
  visionFrame: 'unknown', visionTarget: 'unknown', features: {}, models: {}, activity: [], attentionCount: 0,
};
const record = (input: unknown): Record<string, unknown> | null => input !== null && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, unknown> : null;
const validCount = (value: unknown, max: number): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max;

export function parseSnapshot(data: unknown): HudState {
  const root = record(data);
  const name = record(root?.voice)?.state;
  if (root?.schema !== 2 || root.connected !== true || typeof name !== 'string' || !VOICE.has(name)) return disconnected;

  const work: WorkRow[] = Array.isArray(root.work) ? root.work.slice(0, 6).flatMap((input: unknown) => {
    const row = record(input);
    if (typeof row?.type !== 'string' || !WORK_TYPES.has(row.type) || typeof row.state !== 'string' || !WORK_STATES.has(row.state)) return [];
    const item: WorkRow = { type: row.type, state: row.state };
    if (typeof row.id === 'string' && WORK_ID.test(row.id)) item.id = row.id;
    if (validCount(row.progress, 100) && typeof row.approximate === 'boolean') {
      item.progress = row.progress;
      item.approximate = row.approximate;
    }
    if (typeof row.milestone === 'string' && MILESTONES.has(row.milestone)) item.milestone = row.milestone;
    if (typeof row.model_target === 'string' && MODEL_TOKEN.test(row.model_target)) item.modelTarget = row.model_target;
    if (validCount(row.eta_low_seconds, 604800)) item.etaLowSeconds = row.eta_low_seconds;
    if (validCount(row.eta_high_seconds, 604800)) item.etaHighSeconds = row.eta_high_seconds;
    return [item];
  }) : [];

  const health: HealthRow[] = Array.isArray(root.health) ? root.health.slice(0, 8).flatMap((input: unknown) => {
    const row = record(input);
    return typeof row?.component === 'string' && COMPONENT.test(row.component) && typeof row.state === 'string' && HEALTH_STATES.has(row.state)
      ? [{ component: row.component, state: row.state }] : [];
  }) : [];

  const features: HudState['features'] = {};
  const rawFeatures = record(root.features);
  for (const key of FEATURE_KEYS) {
    const state = rawFeatures?.[key];
    if (typeof state === 'string' && FEATURE_STATES.has(state)) features[key] = state as FeatureStatus;
  }

  const models: HudState['models'] = {};
  const rawModels = record(root.models);
  for (const role of MODEL_ROLES) {
    const entry = record(rawModels?.[role]);
    const modelName = entry?.name;
    if (typeof modelName !== 'string' || !MODEL_TOKEN.test(modelName)) continue;
    const item: ModelSummary = { name: modelName };
    if (typeof entry?.model === 'string' && MODEL_TOKEN.test(entry.model)) item.model = entry.model;
    models[role] = item;
  }

  const rawVision = record(root.vision);
  const vision = rawVision?.state === 'active' || rawVision?.state === 'standby' ? rawVision.state : 'offline';
  const people = rawVision?.people;
  const target = rawVision?.target;
  const rawFrame = rawVision?.frame;
  const visionFrame = rawFrame === 'fresh' || rawFrame === 'stale' || rawFrame === 'pending' ? rawFrame : 'unknown';
  const frameUnavailable = visionFrame === 'stale' || visionFrame === 'pending';
  const visionTarget = !frameUnavailable && (target === 'searching' || target === 'visible' || target === 'following') ? target : 'unknown';

  const activity: ActivityEvent[] = Array.isArray(root.activity) ? root.activity.slice(0, 12).flatMap((input: unknown) => {
    const row = record(input);
    if (
      !validCount(row?.id, Number.MAX_SAFE_INTEGER) || row.id === 0 ||
      typeof row.at !== 'string' || !EVENT_AT.test(row.at) ||
      typeof row.kind !== 'string' || !EVENT_KINDS.has(row.kind) ||
      typeof row.state !== 'string' || !EVENT_STATES.has(row.state) ||
      typeof row.label !== 'string' || !EVENT_LABELS.has(row.label)
    ) return [];
    return [{ id: row.id, at: row.at, kind: row.kind as ActivityEvent['kind'], state: row.state, label: row.label }];
  }) : [];

  return {
    connected: true, voice: name as VoiceState, work, health, vision,
    visionPeople: !frameUnavailable && validCount(people, 99) ? people : null,
    visionFrame, visionTarget, features, models, activity,
    attentionCount: work.filter(item => item.state === 'waiting_for_owner').length,
  };
}

export function isFresh(receivedAt: number | null, now: number): boolean {
  return receivedAt !== null && now >= receivedAt && now - receivedAt <= MAX_STALE_MS;
}
