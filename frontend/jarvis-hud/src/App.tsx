import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Activity, AudioLines, BrainCircuit, ChevronRight, CircleDot, Cpu, Eye, Layers3, LockKeyhole, MonitorDot, PanelLeftClose, PanelLeftOpen, Radar, RadioTower, ShieldAlert, ShieldCheck, Workflow } from 'lucide-react';
import ReactorFallback from './components/ReactorFallback';
import { disconnected, isFresh, parseSnapshot, type HudState } from './hudState';

type Connection = { snapshot: HudState; receivedAt: number | null };
const INITIAL: Connection = { snapshot: disconnected, receivedAt: null };
const ReactorScene = lazy(() => import('./components/ReactorScene'));

function useHudSnapshot(): HudState {
  const [connection, setConnection] = useState<Connection>(INITIAL);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    async function pull() {
      try {
        const response = await fetch('/api/snapshot', {
          cache: 'no-store', credentials: 'omit', signal: controller.signal,
        });
        if (!response.ok) throw new Error('UI bridge offline');
        const data = parseSnapshot(await response.json());
        if (active) setConnection({ snapshot: data, receivedAt: Date.now() });
      } catch {
        if (active) setConnection(INITIAL);
      }
    }
    void pull();
    const poll = window.setInterval(() => void pull(), 2_000);
    const clock = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => { active = false; controller.abort(); window.clearInterval(poll); window.clearInterval(clock); };
  }, []);
  return isFresh(connection.receivedAt, now) ? connection.snapshot : disconnected;
}

const STATE_LABELS: Record<HudState['voice'], string> = {
  offline: 'VOICE OFFLINE', standby: 'STANDBY', activating: 'ACTIVATING',
  listening: 'LISTENING', thinking: 'PROCESSING', speaking: 'RESPONDING',
  recovering: 'RECOVERING',
};

function ModuleCard({ title, index, icon, children, quiet = false }: {
  title: string; index: string; icon: React.ReactNode; children: React.ReactNode; quiet?: boolean;
}) {
  return (
    <section className={`module-card ${quiet ? 'module-card-quiet' : ''}`}>
      <div className="card-header"><span className="card-index">{index}</span><span className="card-title">{icon}{title}</span><span className="card-bracket">[ + ]</span></div>
      <div className="card-content">{children}</div>
      <div className="corner corner-tl"/><div className="corner corner-tr"/><div className="corner corner-bl"/><div className="corner corner-br"/>
    </section>
  );
}

function Marker({ live }: { live: boolean }) { return <span className={`status-marker ${live ? 'active' : ''}`} aria-hidden="true"/>; }

function LabelRow({ label, value, active = false }: { label: string; value: string; active?: boolean }) {
  return <div className="data-row"><span>{label}</span><span className={active ? 'data-active' : ''}>{value}</span></div>;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="empty-state"><span className="empty-hex"><CircleDot size={20} strokeWidth={1}/></span><span>{children}</span></div>;
}

function Estimate({ progress, approximate, milestone, etaLowSeconds, etaHighSeconds }: {
  progress?: number; approximate?: boolean; milestone?: string; etaLowSeconds?: number; etaHighSeconds?: number;
}) {
  if (progress === undefined && !milestone) return null;
  const eta = etaLowSeconds !== undefined && etaHighSeconds !== undefined
    ? `${Math.ceil(etaLowSeconds / 60)}–${Math.ceil(etaHighSeconds / 60)} MIN` : null;
  return <div className="work-estimate">
    <div className="estimate-meta"><span>{milestone?.replaceAll('_', ' ') ?? 'Progress'}</span>{progress !== undefined && <strong>{approximate ? '≈' : ''}{progress}%</strong>}</div>
    {progress !== undefined && <div className="estimate-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Canonical work progress"><span style={{ width: `${progress}%` }}/></div>}
    {eta && <small>ESTIMATED {eta}</small>}
  </div>;
}

function FeatureRow({ label, status }: { label: string; status: string | undefined }) {
  return <div className="feature-row"><span>{label}</span><strong className={`feature-${status ?? 'unknown'}`}>{status ?? 'NOT REPORTED'}</strong></div>;
}

export default function App() {
  const hud = useHudSnapshot();
  const [lowPower, setLowPower] = useState(false);
  const [showPanels, setShowPanels] = useState(true);
  const [reduceMotion, setReduceMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const ticker = window.setInterval(() => setClock(new Date()), 1_000);
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const listener = (event: MediaQueryListEvent) => setReduceMotion(event.matches);
    query.addEventListener('change', listener);
    return () => { window.clearInterval(ticker); query.removeEventListener('change', listener); };
  }, []);

  const label = hud.connected ? STATE_LABELS[hud.voice] : 'NO RUNTIME';
  const connected = hud.connected;
  const render3D = !lowPower && !reduceMotion;
  const reactorState = hud.voice === 'speaking' || hud.voice === 'listening' || hud.voice === 'thinking'
    ? hud.voice : 'idle';
  const activeCount = useMemo(() => hud.work.filter(item => ['running', 'retrying'].includes(item.state)).length, [hud.work]);
  const mostRecentActivity = hud.activity[0];
  const voiceModel = hud.models.voice;

  return (
    <main className={`jarvis-app state-${hud.voice} ${showPanels ? '' : 'panels-hidden'}`}>
      <div className="background-grid" aria-hidden="true"/><div className="atmosphere" aria-hidden="true"/>
      <div className="scanline-overlay" aria-hidden="true"/>
      <header className="topbar">
        <div className="wordmark"><div className="wordmark-icon"><span>J</span></div><div><strong>J.A.R.V.I.S.</strong><small>PERSONAL INTELLIGENCE SYSTEM</small></div></div>
        <div className="header-center"><span className="header-dash"/> NEURAL INTERFACE <span className="header-revision">// UI 01</span></div>
        <div className="header-right"><span className="live-header"><Marker live={connected}/>{connected ? 'SYSTEM LINKED' : 'PREVIEW / NO RUNTIME'}</span><time dateTime={clock.toISOString()}>{clock.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time></div>
      </header>

      <div className="workspace">
        <aside className="sidebar sidebar-left" aria-label="Runtime and Work status">
          <div className="rail-tag">01 / CORE DIAGNOSTICS</div>
          <ModuleCard title="RUNTIME LINK" index="SYS.01" icon={<Activity size={13}/>}>
            <div className="signal-block"><div><div className="block-eyebrow">VOICE STATUS</div><div className="signal-value"><Marker live={connected}/>{label}</div></div><AudioLines className="signal-icon" size={28} strokeWidth={1}/></div>
            <div className="fine-separator"/>
            <LabelRow label="SOURCE" value={connected ? 'CANONICAL JARVIS' : 'NOT CONNECTED'}/>
            <LabelRow label="CHANNEL" value="LOCAL · READ ONLY" active={connected}/>
            <LabelRow label="VOICE INPUT" value="EXTERNAL RUNTIME"/>
            {voiceModel && <LabelRow label="VOICE CONFIG" value={voiceModel.name.toUpperCase()} active/>}
            {voiceModel?.model && <LabelRow label="MODEL CONFIG" value={voiceModel.model}/>}
          </ModuleCard>
          <ModuleCard title="WORK MATRIX" index="SYS.02" icon={<Workflow size={13}/>}>
            <div className="card-kpi"><div><span className="kpi-number">{String(hud.work.length).padStart(2, '0')}</span><span className="kpi-caption">RECENT WORK ITEMS</span></div><div className="kpi-supplement"><strong>{String(activeCount).padStart(2, '0')}</strong><small>ACTIVE</small></div></div>
            {hud.work.length > 0 ? <div className="entry-list">{hud.work.map((item, index) => <div className={`work-entry ${item.state === 'waiting_for_owner' ? 'work-attention' : ''}`} key={item.id ?? `${item.type}-${item.state}-${index}`}><span className="work-glyph"><ChevronRight size={12}/></span><div className="work-content"><strong>{item.type.replaceAll('_', ' ')}</strong><small>{item.state.replaceAll('_', ' ')}</small><Estimate progress={item.progress} approximate={item.approximate} milestone={item.milestone} etaLowSeconds={item.etaLowSeconds} etaHighSeconds={item.etaHighSeconds}/>{item.modelTarget && <small className="route-detail">ROUTE DECISION · {item.modelTarget}</small>}</div></div>)}</div> : <EmptyState>{!connected ? 'Work data appears when JARVIS is running' : hud.features.work === 'disabled' ? 'Work orchestration is disabled' : 'No recent work reported'}</EmptyState>}
          </ModuleCard>
          {hud.attentionCount > 0 && <div className="attention-card" role="status"><ShieldAlert size={19}/><div><strong>JARVIS NEEDS YOU</strong><p>{hud.attentionCount} mission{hud.attentionCount === 1 ? '' : 's'} waiting for owner input through JARVIS's existing interaction flow.</p></div></div>}
          <div className="rail-footnote"><ShieldCheck size={14}/> THIS DISPLAY HAS NO COMMAND AUTHORITY</div>
        </aside>

        <section className="core-stage" aria-label="JARVIS core visualizer">
          <div className="center-topline"><span>FIG / 01</span><span>ARC REACTOR INTERFACE</span><span>{render3D ? '3D ENGINE ACTIVE' : 'LOW GPU VISUAL'}</span></div>
          <div className="core-frame">
            <div className="core-orbit orbit-one" aria-hidden="true"/><div className="core-orbit orbit-two" aria-hidden="true"/>
            <div className="core-crosshair crosshair-h" aria-hidden="true"/><div className="core-crosshair crosshair-v" aria-hidden="true"/>
            <div className="orbit-label orbit-label-left">ENERGY SYSTEM<br/>VISUALIZATION</div>
            <div className="orbit-label orbit-label-right">LOCAL LINK<br/>PROTOCOL 01</div>
            <div className="reactor-viewport">{render3D ? <Suspense fallback={<ReactorFallback reason="Preparing graphics engine."/>}><ReactorScene state={reactorState} taskComplexity={0} audioLevel={0}/></Suspense> : <ReactorFallback reason="Low-GPU / reduced-motion visual selected."/>}</div>
            <div className="orbital-notch notch-tl"/><div className="orbital-notch notch-tr"/><div className="orbital-notch notch-bl"/><div className="orbital-notch notch-br"/>
          </div>
          <div className="core-title"><div className="hero-eyebrow"><span className="bar-decoration"/> THE PERSONAL INTELLIGENCE SYSTEM <span className="bar-decoration"/></div><h1>JARVIS<span className="title-period">.</span></h1><div className="core-state" aria-live="polite"><span className="core-state-line"/><Marker live={connected}/>{label}<span className="core-state-line"/></div></div>
          {mostRecentActivity && <div className="latest-activity" aria-live="off"><Activity size={13}/><span>LAST EVENT · {mostRecentActivity.label}</span><span className="latest-state">{mostRecentActivity.state.replaceAll('_', ' ')}</span></div>}
          <div className="core-bottomline"><span>[ 0x01 ] VISUAL PROJECTION</span><span>PRIMARY AUTHORITY / PYTHON RUNTIME</span></div>
        </section>

        <aside className="sidebar sidebar-right" aria-label="System health and vision status">
          <div className="rail-tag">02 / SUBSYSTEM MONITOR</div>
          <ModuleCard title="COMPONENT HEALTH" index="MON.01" icon={<Cpu size={13}/>}>
            <div className="health-banner"><div className="radar-motif"><span/><span/><span/></div><div><small>HEALTH SNAPSHOT</small><strong>{hud.health.length ? `${hud.health.length} COMPONENTS` : 'UNAVAILABLE'}</strong></div></div>
            {hud.health.length > 0 ? <div className="health-list">{hud.health.map((item, index) => <div className="health-entry" key={`${item.component}-${index}`}><div><span className="health-dot"/><span>{item.component.replaceAll('_', ' ')}</span></div><strong className={`health-${item.state}`}>{item.state.toUpperCase()}</strong></div>)}</div> : <EmptyState>{connected ? 'No health snapshot supplied' : 'Waiting for local runtime health'}</EmptyState>}
          </ModuleCard>
          <ModuleCard title="VISION SENSOR" index="MON.02" icon={<Eye size={13}/>} quiet>
            <div className="vision-row"><div className="vision-symbol"><Eye size={28} strokeWidth={1}/></div><div><small>CAMERA SERVICE</small><strong>{hud.vision === 'active' ? 'ACTIVE' : hud.features.vision === 'disabled' ? 'DISABLED' : 'OFFLINE'}</strong><span>STATUS ONLY · NO VIDEO</span></div><Marker live={hud.vision === 'active'}/></div>
            {hud.vision === 'active' && <div className="vision-detail"><LabelRow label="FRAME" value={hud.visionFrame.toUpperCase()}/><LabelRow label="TARGET" value={hud.visionTarget.toUpperCase()}/>{hud.visionPeople !== null && <LabelRow label="VISIBLE TRACKS" value={String(hud.visionPeople)}/>}</div>}
          </ModuleCard>
          <ModuleCard title="INTELLIGENCE" index="MON.03" icon={<BrainCircuit size={13}/>} quiet>
            <div className="feature-list">
              <FeatureRow label="RESEARCH" status={hud.features.research}/>
              <FeatureRow label="HANDS" status={hud.features.hands}/>
              <FeatureRow label="PERSONAL CONTEXT" status={hud.features.personal_context}/>
              <FeatureRow label="LEARNING" status={hud.features.learning}/>
            </div>
            {hud.models.research && <div className="model-detail"><RadioTower size={12}/><span>SEARCH · {hud.models.research.name}</span></div>}
            {hud.models.work && <div className="model-detail"><Radar size={12}/><span>WORK CONFIG · {hud.models.work.name}{hud.models.work.model ? ` / ${hud.models.work.model}` : ''}</span></div>}
          </ModuleCard>
          <ModuleCard title="LIVE ACTIVITY" index="MON.04" icon={<Activity size={13}/>} quiet>
            {hud.activity.length ? <div className="activity-list">{hud.activity.map(event => <div className="activity-entry" key={event.id}><span className="activity-pin"/><div><strong>{event.label}</strong><small>{event.state.replaceAll('_', ' ')}</small></div><time dateTime={event.at}>{event.at.slice(11,16)}Z</time></div>)}</div> : <EmptyState>{connected ? 'No recent operations reported' : 'Activity appears with a live JARVIS session'}</EmptyState>}
          </ModuleCard>
          <div className="security-note"><LockKeyhole size={17}/><div><strong>CANONICAL BOUNDARY</strong><p>Memory, execution, identity and voice remain inside your original JARVIS.</p></div></div>
        </aside>
      </div>

      <footer className="bottom-bar"><div className="bottom-left"><span className="footer-diamond"/><span>JARVIS / HUD INTERFACE</span><span className="footer-separator">//</span><span>CANONICAL · READ ONLY</span>{hud.attentionCount > 0 && <span className="footer-attention"><ShieldAlert size={12}/> OWNER INPUT NEEDED</span>}</div><div className="bottom-controls"><button type="button" onClick={() => setShowPanels(v => !v)} aria-pressed={!showPanels} title="Toggle status panels">{showPanels ? <PanelLeftClose size={14}/> : <PanelLeftOpen size={14}/>} {showPanels ? 'FOCUS MODE' : 'SHOW PANELS'}</button><button type="button" onClick={() => setLowPower(v => !v)} aria-pressed={lowPower} title="Toggle lightweight visual"><Layers3 size={14}/>{lowPower ? 'GPU: LOW' : 'GPU: AUTO'}</button></div><div className="bottom-right"><MonitorDot size={14}/><span>LOCAL INTERFACE</span><span className="revision">/ V2</span></div></footer>
      <div className="edge-ruler ruler-left" aria-hidden="true"/><div className="edge-ruler ruler-right" aria-hidden="true"/>
    </main>
  );
}
