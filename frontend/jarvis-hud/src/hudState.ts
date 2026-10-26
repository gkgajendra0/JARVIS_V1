export type VoiceState = 'offline' | 'standby' | 'activating' | 'listening' | 'thinking' | 'speaking' | 'recovering';
export type WorkRow = { type: string; state: string };
export type HealthRow = { component: string; state: string };
export type HudState = { connected: boolean; voice: VoiceState; work: WorkRow[]; health: HealthRow[]; vision: 'offline' | 'standby' | 'active' };

const VOICE: ReadonlySet<string> = new Set(['standby', 'activating', 'listening', 'thinking', 'speaking', 'recovering']);
const WORK_TYPES: ReadonlySet<string> = new Set(['development', 'research', 'diagnostics', 'hands', 'monitoring', 'reminder', 'generic', 'external_acceptance']);
const WORK_STATES: ReadonlySet<string> = new Set(['queued', 'running', 'waiting_resource', 'waiting_dependency', 'waiting_until', 'waiting_for_owner', 'paused', 'retrying', 'completed', 'failed', 'cancelled']);
const HEALTH_STATES: ReadonlySet<string> = new Set(['unknown', 'starting', 'healthy', 'degraded', 'failed', 'recovering', 'disabled']);
const COMPONENT = /^[a-zA-Z0-9_.:-]{1,48}$/;
const MAX_STALE_MS = 10_000;

export const disconnected: HudState = { connected: false, voice: 'offline', work: [], health: [], vision: 'offline' };
const record = (input: unknown): Record<string, unknown> | null => input !== null && typeof input === 'object' && !Array.isArray(input) ? input as Record<string, unknown> : null;

export function parseSnapshot(data: unknown): HudState {
  const root = record(data);
  const voice = record(root?.voice);
  const name = voice?.state;
  if (root?.schema !== 1 || root.connected !== true || typeof name !== 'string' || !VOICE.has(name)) return disconnected;

  const work = Array.isArray(root.work) ? root.work.slice(0, 6).flatMap((input: unknown) => {
    const row = record(input);
    return typeof row?.type === 'string' && WORK_TYPES.has(row.type) && typeof row.state === 'string' && WORK_STATES.has(row.state)
      ? [{ type: row.type, state: row.state }] : [];
  }) : [];
  const health = Array.isArray(root.health) ? root.health.slice(0, 8).flatMap((input: unknown) => {
    const row = record(input);
    return typeof row?.component === 'string' && COMPONENT.test(row.component) && typeof row.state === 'string' && HEALTH_STATES.has(row.state)
      ? [{ component: row.component, state: row.state }] : [];
  }) : [];
  const vision = record(root.vision)?.state;
  return {
    connected: true, voice: name as VoiceState, work, health,
    vision: vision === 'active' || vision === 'standby' ? vision : 'offline',
  };
}

export function isFresh(receivedAt: number | null, now: number): boolean {
  return receivedAt !== null && now >= receivedAt && now - receivedAt <= MAX_STALE_MS;
}
