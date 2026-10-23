"use strict";
// JARVIS Visual Companion: deliberately read-only. No app action/API mutation
// is dispatched by this browser. All external evidence comes from a trusted
// loopback snapshot. All text is rendered using textContent.
const el = (id) => document.getElementById(id);
const model = {
  snapshot: {schema: 1, seq: 0, runtime_connected: false, voice_state: "offline", panels: [], work: [], vision: {connected:false,running:false}, health: []},
  local: new Map(),
  pinned: new Map(),
  dismissed: new Map(),
  demo: false,
  currentView: "ambient",
  lastSequence: -1,
  quality: "cinematic",
};
const icons = {work:"▤", research:"◎", document:"▧", vision:"◉", system:"◇", alert:"!", info:"✦"};
const names = {
  work:"Background work", research:"Research", document:"Files & documents",
  vision:"Vision & cameras", system:"System health", alert:"Attention required", info:"Context"
};
let toastTimeout = null;
function toast(message) {
  const node = el("toast");
  node.textContent = message;
  node.classList.add("visible");
  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => node.classList.remove("visible"), 2700);
}
function clock() {
  const date = new Date();
  el("localClock").textContent = date.toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"});
}
function paragraph(text, className="") {
  const p=document.createElement("p"); p.textContent=text;
  if(className) p.className=className;
  return p;
}
function makeButton(text,label,handler) {
  const b=document.createElement("button"); b.type="button"; b.textContent=text;
  b.setAttribute("aria-label",label); b.title=label;
  b.addEventListener("click",handler); return b;
}
function panelFromType(type) {
  const now=Date.now()/1000;
  const live=model.snapshot.runtime_connected;
  let summary="";
  if(type==="vision" && live){
    const vision=model.snapshot.vision||{};
    summary=vision.connected
      ? (vision.running?"Vision processing is active. ":"Vision processing is not running. ")+
        "Active source: "+String(vision.active_source||"unknown")+
        ". No camera frames or identities are transmitted to this UI."
      : "The Jarvis vision diagnostics feed is unavailable.";
  } else if(type==="system" && live){
    const items=model.snapshot.health||[];
    summary=items.length
      ? "Live, sanitized Self Model health states from Jarvis. Detailed incident and private diagnostic data remain in the governed runtime."
      : "Jarvis is linked, but component-health diagnostics are unavailable.";
  } else if(type==="work") summary=live
    ? "Showing current canonical background WorkItem state. Task descriptions are omitted until their permission boundary is wired."
    : "Jarvis's runtime WorkStore is not connected. Start the opted-in voice runtime to view real task states.";
  else if(type==="system") summary=live
    ? "The voice runtime is connected. Full component-health evidence is not yet published to this visual adapter."
    : "Runtime health feed is offline. This UI is not reporting machine health.";
  else if(type==="vision") summary="Camera frames and tracking evidence are not exposed by this first UI slice. No live camera view is active.";
  else if(type==="research") summary="No source-grounded research result has been published to this visual adapter. Ask Jarvis to research it using its existing voice/tools.";
  else if(type==="document") summary="Document content requires an authorized file capability read. This UI does not inspect your files automatically.";
  else summary="No context is available from the approved adapter.";
  return {id:"manual."+type,type,title:names[type]||"Context",summary,source:"local_ui",priority:2,observed_at:now,expires_at:now+1200};
}
function setRadialMenu(open) {
  el("orbToggle").setAttribute("aria-expanded",String(open));
  el("radialMenu").setAttribute("aria-hidden",String(!open));
  el("radialMenu").inert=!open;
  el("orbToggle").parentElement.classList.toggle("menu-open",open);
}
function showType(type) {
  setRadialMenu(false);
  if(!Object.hasOwn(names,type) || type==="alert" || type==="info") {
    toast("Choose Work, Research, Vision, Files, or System.");return;
  }
  const panel=panelFromType(type);
  model.local.set(panel.id,panel);
  model.dismissed.delete(panel.id);
  model.currentView="context";
  render();
}
function goHome() {
  setRadialMenu(false);
  model.local.clear();
  // Returning to ambient mode dismisses currently projected runtime cards
  // locally, never in Jarvis's canonical subsystem. Freshly observed events
  // can still reopen a relevant hologram without another browser command.
  for(const p of model.snapshot.panels||[]) {
    if(!model.pinned.has(p.id))model.dismissed.set(p.id,p.observed_at);
  }
  model.currentView="ambient";
  render();
}
function isVisiblePanel(p,now) {
  if(p.expires_at <= now) return model.pinned.has(p.id) && p.source==="local_ui";
  const dismissedAt=model.dismissed.get(p.id);
  return dismissedAt === undefined || dismissedAt < p.observed_at;
}
function currentPanels() {
  const now=Date.now()/1000;
  const collection=new Map();
  for(const p of model.snapshot.panels||[]) {
    if(p && typeof p.id==="string" && isVisiblePanel(p,now)) collection.set(p.id,p);
  }
  for(const [id,p] of model.local) {
    if(isVisiblePanel(p,now)) collection.set(id,p);
    else if(!model.pinned.has(id)) model.local.delete(id);
  }
  for(const [id,p] of model.pinned) {
    if(!collection.has(id)) {
      // Only local UI items are retainable past a data lease. No private data.
      if(p.source==="local_ui") collection.set(id,p);
      else model.pinned.delete(id);
    }
  }
  const all=[...collection.values()].sort((a,b) =>
    Number(model.pinned.has(b.id))-Number(model.pinned.has(a.id)) ||
    (b.priority||0)-(a.priority||0) ||
    (b.observed_at||0)-(a.observed_at||0));
  const pinned=all.filter(p=>model.pinned.has(p.id));
  const unpinned=all.filter(p=>!model.pinned.has(p.id)).slice(0,2);
  return [...pinned,...unpinned].slice(0,4);
}
function buildPreviewVisual(p) {
  if(p.source!=="demo")return null;
  const outer=document.createElement("div");
  outer.className="holo-preview";
  if(p.type==="research") {
    const stats=document.createElement("div");stats.className="holo-telemetry";
    for(const [amount,label] of [["03","SOURCES"],["07","LINKS"],["01","FOCUS"]]) {
      const stat=document.createElement("div");stat.className="holo-stat";
      const strong=document.createElement("strong");strong.textContent=amount;
      const small=document.createElement("span");small.textContent=label;
      stat.append(strong,small);stats.append(stat);
    }
    const item=document.createElement("div");item.className="holo-source-row";
    const symbol=document.createElement("div");symbol.className="holo-source-icon";symbol.textContent="⟡";
    const details=document.createElement("div");details.className="holo-source-text";
    const a=document.createElement("strong");a.textContent="Contextual source projection";
    const b=document.createElement("small");b.textContent="Design preview • no live research queried";
    details.append(a,b);item.append(symbol,details);
    outer.append(stats,item);
  } else {
    const telemetry=document.createElement("div");telemetry.className="holo-activity";
    const top=document.createElement("div");top.className="holo-activity-head";
    const title=document.createElement("span");title.textContent="PANEL MATERIALIZATION";
    const pct=document.createElement("span");pct.textContent="PREVIEW";
    top.append(title,pct);
    const progress=document.createElement("div");progress.className="holo-progress";
    const fill=document.createElement("span");fill.style.width="76%";
    progress.append(fill);
    const bars=document.createElement("div");bars.className="holo-signal";
    for(let i=0;i<18;i++) {
      const b=document.createElement("span");
      b.style.height=(18+((i*37+19)%72))+"%";
      bars.append(b);
    }
    const status=document.createElement("div");status.className="holo-pulse-badge";
    status.textContent="PROJECTION CHANNEL • SIMULATED";
    telemetry.append(top,progress,bars,status);outer.append(telemetry);
  }
  return outer;
}
function renderCard(p) {
  const card=document.createElement("article");
  card.className="context-card";
  if(p.priority===3)card.classList.add("high-priority");
  card.dataset.signature=JSON.stringify([
    p.title,p.summary,p.source,p.priority,model.pinned.has(p.id),
    p.sources||[],
    p.type==="work"?model.snapshot.work:[],
    p.type==="vision"?model.snapshot.vision:{},
    p.type==="system"?model.snapshot.health:[]
  ]);
  card.dataset.panelId=p.id;
  const header=document.createElement("header");
  const heading=document.createElement("div");heading.className="card-heading";
  const icon=document.createElement("span");icon.className="card-icon";icon.textContent=icons[p.type]||"◇";
  const title=document.createElement("span");title.className="card-title";title.textContent=p.title;
  heading.append(icon,title);
  const actions=document.createElement("div");actions.className="card-actions";
  const pin=makeButton("♧",model.pinned.has(p.id)?"Unpin panel":"Pin panel",()=>{
    if(model.pinned.has(p.id))model.pinned.delete(p.id);
    else model.pinned.set(p.id,{...p});
    render();
  });
  if(model.pinned.has(p.id))pin.classList.add("active-pin");
  const close=makeButton("×","Dismiss panel",()=>{
    model.dismissed.set(p.id,p.observed_at);
    model.pinned.delete(p.id);
    model.local.delete(p.id);
    render();
  });
  actions.append(pin,close);header.append(heading,actions);card.append(header);
  const body=document.createElement("div");body.className="card-body";
  const eyebrow=document.createElement("div");eyebrow.className="card-eyebrow";
  eyebrow.textContent=p.source==="demo"?"DEMO CONTENT":
    p.source==="research_result"?"GROUNDED RESEARCH TOOL OUTPUT":
    p.type==="work"&&model.snapshot.runtime_connected?"CANONICAL WORK STATUS":
    p.type==="vision"&&model.snapshot.vision?.connected?"LIVE CAMERA DIAGNOSTICS":
    p.type==="system"&&model.snapshot.health?.length?"LIVE SELF MODEL HEALTH":"VISUAL CONTEXT";
  body.append(eyebrow,paragraph(p.summary));
  const visual=buildPreviewVisual(p);
  if(visual)body.append(visual);
  if(p.type==="research" && p.source==="research_result"){
    const sourceList=document.createElement("div");sourceList.className="live-source-list";
    for(const source of (Array.isArray(p.sources)?p.sources:[]).slice(0,5)){
      if(!source || typeof source.title!=="string" || typeof source.url!=="string")continue;
      let valid;
      try{
        valid=new URL(source.url);
        if(valid.protocol!=="https:" || valid.username || valid.password || valid.port)continue;
      }catch(_){continue;}
      const link=document.createElement("a");
      link.className="live-source";link.href=valid.href;
      link.target="_blank";link.rel="noopener noreferrer";
      const label=document.createElement("strong");label.textContent=source.title;
      const domain=document.createElement("small");domain.textContent=source.domain||valid.hostname;
      link.append(label,domain);sourceList.append(link);
    }
    if(sourceList.children.length)body.append(sourceList);
  }
  if(p.type==="vision" && p.source!=="demo"){
    const vision=model.snapshot.vision||{};
    const telemetry=document.createElement("div");telemetry.className="live-status-stack";
    const line=document.createElement("div");line.className="live-status-row";
    const label=document.createElement("span");label.textContent="CAMERA DIAGNOSTICS";
    const state=document.createElement("strong");state.textContent=
      vision.connected?(vision.running?"RUNNING":"STOPPED"):"UNAVAILABLE";
    line.append(label,state);telemetry.append(line);
    if(vision.connected){
      const detail=document.createElement("div");detail.className="live-status-row";
      const name=document.createElement("span");name.textContent="ACTIVE CAMERA";
      const value=document.createElement("strong");
      value.textContent=String(vision.active_source||"unknown").toUpperCase();
      detail.append(name,value);telemetry.append(detail);
    }
    body.append(telemetry);
  }
  if(p.type==="system" && p.source!=="demo"){
    const statuses=Array.isArray(model.snapshot.health)?model.snapshot.health:[];
    const container=document.createElement("div");container.className="live-health-list";
    for(const item of statuses.slice(0,10)){
      const row=document.createElement("div");row.className="live-status-row";
      const name=document.createElement("span");name.textContent=item.component||"component";
      const state=document.createElement("strong");state.textContent=
        String(item.state||"unknown").toUpperCase();
      row.append(name,state);container.append(row);
    }
    if(container.children.length)body.append(container);
  }
  if(p.type==="work" && model.snapshot.work.length && p.source!=="demo") {
    const list=document.createElement("div");list.className="work-list";
    for(const item of model.snapshot.work.slice(0,8)) {
      const row=document.createElement("div");row.className="work-row";
      const title=document.createElement("strong");title.textContent=item.kind+" · "+item.id.slice(0,15);
      const status=document.createElement("em");status.textContent=item.state.replaceAll("_"," ").toUpperCase();
      row.append(title,status);list.append(row);
    }
    body.append(list);
  }
  card.append(body);
  const foot=document.createElement("footer");foot.className="card-note";
  const origin=document.createElement("span");
  origin.textContent=p.source==="demo"?"SAMPLE • NOT LIVE":
    p.source==="research_result"?"LIVE TOOL SOURCES • UNTRUSTED PAGES":
    p.source==="local_ui"?"UI SELECTION • RUNTIME READ-ONLY":
    "JARVIS RUNTIME • SUBJECT TO FRESHNESS";
  if(p.source==="demo")origin.className="sample";
  const ts=document.createElement("span");
  ts.textContent=Number.isFinite(p.observed_at)?new Date(p.observed_at*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"";
  foot.append(origin,ts);card.append(foot);
  return card;
}
const svgNS="http://www.w3.org/2000/svg";
const beamGroups=new Map();
const closingAnimations=new WeakMap();
let projectionTimer=null;
let beamRaf=0;
function projectionGlow(){
  const app=el("app");
  app.classList.remove("is-projecting");
  // Force a new flash cycle on each deliberate reveal.
  void app.offsetWidth;
  app.classList.add("is-projecting");
  if(projectionTimer!==null)clearTimeout(projectionTimer);
  projectionTimer=setTimeout(()=>app.classList.remove("is-projecting"),960);
}
function moveFromOrb(card,reverse=false){
  if(reduced.matches||model.quality==="eco")return null;
  const orb=el("orbCanvas").getBoundingClientRect();
  const rect=card.getBoundingClientRect();
  const offsetX=(orb.left+orb.width/2)-(rect.left+rect.width/2);
  const offsetY=(orb.top+orb.height/2)-(rect.top+rect.height/2);
  // The border begins as a small beam at the orb, unfolds into a
  // horizontal line, then resolves as an entire holographic surface.
  const from={opacity:0, transform:"translate("+offsetX+"px,"+offsetY+"px) scale(.035)",clipPath:"inset(48% 48% 48% 48%)",filter:"brightness(2.6) blur(7px)"};
  const midpoint={opacity:1,transform:"translate("+(offsetX*.14)+"px,"+(offsetY*.14)+"px) scale(.62,.09)",clipPath:"inset(40% 0% 40% 0%)",filter:"brightness(2) blur(0px)",offset:.43};
  const to={opacity:1,transform:"translate(0px,0px) scale(1)",clipPath:"inset(0% 0% 0% 0%)",filter:"brightness(1) blur(0px)"};
  return card.animate(reverse?[to,midpoint,from]:[from,midpoint,to],{
    duration:reverse?520:830,
    easing:reverse?"cubic-bezier(.65,.05,.82,.3)":"cubic-bezier(.15,.83,.22,1)",
    fill:"both"
  });
}
function svgNode(tag,cls) {
  const node=document.createElementNS(svgNS,tag);
  if(cls)node.setAttribute("class",cls);
  return node;
}
function updateProjectionBeams() {
  beamRaf=0;
  const surface=el("projectionLinks");
  const frame=el("layout").getBoundingClientRect();
  const orb=el("orbCanvas").getBoundingClientRect();
  if(frame.width<1||frame.height<1||window.innerWidth<=740){
    for(const group of beamGroups.values())group.remove();
    beamGroups.clear();
    return;
  }
  surface.setAttribute("viewBox","0 0 "+frame.width+" "+frame.height);
  const ox=orb.left+orb.width/2-frame.left;
  const oy=orb.top+orb.height/2-frame.top;
  const current=new Set();
  for(const card of el("cards").children) {
    if(card.classList.contains("is-closing"))continue;
    const id=card.dataset.panelId;
    current.add(id);
    const box=card.getBoundingClientRect();
    const targetX=box.left+box.width/2-frame.left;
    const targetY=box.top+box.height/2-frame.top;
    const left=targetX<ox;
    const sx=ox+(left?-1:1)*orb.width*.43;
    const sy=oy+(targetY-oy)*.2;
    const ex=targetX+(left?1:-1)*box.width*.48;
    const ey=targetY;
    const bend=(ex-sx)*.52;
    const path="M "+sx+" "+sy+" C "+(sx+bend)+" "+sy+" "+(ex-bend*.4)+" "+ey+" "+ex+" "+ey;
    let group=beamGroups.get(id);
    if(!group){
      group=svgNode("g","projection-link");
      group.dataset.id=id;
      const glow=svgNode("path","projection-beam-glow");
      const line=svgNode("path","projection-beam");
      const cap=svgNode("circle","projection-beam-pulse");
      cap.setAttribute("r","3.5");
      const rim=svgNode("circle","projection-endcap");
      rim.setAttribute("r","8");
      group.append(glow,line,cap,rim);
      el("beamLayer").append(group);
      beamGroups.set(id,group);
      if(!reduced.matches && model.quality!=="eco"){
        group.animate([{opacity:0},{opacity:1}],{duration:540,easing:"ease-out",fill:"both"});
      }
    }
    const [glow,line,cap,rim]=group.children;
    glow.setAttribute("d",path);line.setAttribute("d",path);
    cap.setAttribute("cx",String(ex));cap.setAttribute("cy",String(ey));
    rim.setAttribute("cx",String(ex));rim.setAttribute("cy",String(ey));
  }
  for(const [id,group] of beamGroups){
    if(!current.has(id)){group.remove();beamGroups.delete(id);}
  }
}
function scheduleBeams(){
  if(beamRaf)return;
  beamRaf=requestAnimationFrame(updateProjectionBeams);
}
function reconcileCards(panels){
  const cards=el("cards");
  const desired=new Map(panels.map((p,i)=>[p.id,{p,slot:i}]));
  let anyNew=false;
  for(const node of [...cards.children]){
    const id=node.dataset.panelId;
    if(desired.has(id)){
      const exitAnimation=closingAnimations.get(node);
      if(exitAnimation){
        exitAnimation.cancel();
        closingAnimations.delete(node);
      }
      node.classList.remove("is-closing");
      continue;
    }
    if(node.classList.contains("is-closing"))continue;
    node.classList.add("is-closing");
    const animation=moveFromOrb(node,true);
    if(animation){
      closingAnimations.set(node,animation);
      animation.finished.catch(()=>{}).then(()=>{
        // An interrupted dismissal must not delete a reopened context.
        if(!node.isConnected||!node.classList.contains("is-closing"))return;
        closingAnimations.delete(node);
        node.remove();
        if(!cards.children.length)el("layout").classList.remove("has-stage");
        scheduleBeams();
      });
    } else node.remove();
  }
  for(const [id,{p,slot}] of desired) {
    const signature=JSON.stringify([
      p.title,p.summary,p.source,p.priority,model.pinned.has(p.id),
      p.sources||[],
      p.type==="work"?model.snapshot.work:[],
      p.type==="vision"?model.snapshot.vision:{},
      p.type==="system"?model.snapshot.health:[]
    ]);
    const previous=[...cards.children].find(n=>n.dataset.panelId===id);
    if(previous){
      previous.dataset.slot=String(slot);
      if(previous.dataset.signature!==signature){
        const next=renderCard(p);next.dataset.slot=String(slot);
        previous.replaceWith(next);
      }
      continue;
    }
    const node=renderCard(p);
    node.dataset.slot=String(slot);
    cards.append(node);anyNew=true;
    const projection=moveFromOrb(node);
    if(projection){
      node.classList.add("is-materializing");
      projection.finished.catch(()=>{}).then(()=>{
        if(node.isConnected)node.classList.remove("is-materializing");
      });
    }
  }
  if(anyNew){projectionGlow();scheduleBeams();}
  if(!cards.children.length)el("layout").classList.remove("has-stage");
  scheduleBeams();
}
function render() {
  const panels=currentPanels();
  const active=panels.length>0;
  el("layout").classList.toggle("multi-projection",panels.length>2);
  if(active)el("layout").classList.add("has-stage");
  el("quietPrompt").hidden=active;
  el("stage").setAttribute("aria-hidden",String(!active && !el("cards").children.length));
  reconcileCards(panels);
  const connected=Boolean(model.snapshot.runtime_connected);
  el("connectionBadge").textContent=model.demo?"DEMO • SAMPLE DATA":connected?"JARVIS RUNTIME LINKED":"UI PREVIEW • NO RUNTIME";
  el("connectionBadge").classList.toggle("live",connected && !model.demo);
  const voice=model.demo?"demo":model.snapshot.voice_state||"offline";
  const labels={offline:"Runtime not connected",idle:"Standing by",activating:"Activating",listening:"Listening",thinking:"Thinking",speaking:"Speaking",error:"Provider unavailable",demo:"Preview animation"};
  el("voiceState").replaceChildren();
  const dot=document.createElement("span");dot.className="small-status";
  el("voiceState").append(dot,document.createTextNode(labels[voice]||"Standing by"));
  el("voiceState").classList.toggle("online",connected||model.demo);
  el("app").dataset.state=voice;
  el("stageTitle").textContent=panels.length===1?panels[0].title:"Right information. Right moment.";
  el("dockHeading").textContent=active?"PROJECTION ACTIVE":"AMBIENT MODE";
  el("dockStatus").textContent=active?"Context emerges from JARVIS":"Minimal by design";
  el("workCounter").textContent=connected ? model.snapshot.work.length+" RECENT WORK ITEMS" : "NO WORK FEED";
  el("modeHint").lastChild.textContent=active?" SPATIAL PROJECTION":" CONTEXT-AWARE INTERFACE";
  el("previewButton").classList.toggle("selected",model.demo);
  document.querySelectorAll(".rail-button[data-panel]").forEach(b=>b.classList.toggle("selected",panels.some(p=>p.type===b.dataset.panel)));
  document.querySelector(".rail-button[data-action=home]").classList.toggle("selected",!active);
  // Actual microphone/audio amplitude is not available here. We animate only
  // explicitly observed lifecycle states, never a fictitious live audio feed.
}
function parseCommand(input) {
  const value=input.toLowerCase().trim();
  if(!value)return;
  if(/\b(clear|close|home|ambient|hide)\b/.test(value)){goHome();return;}
  const matches=[
    ["work",/\b(work|tasks?|mission|progress)\b/],
    ["research",/\b(research|news|web|sources?|search)\b/],
    ["vision",/\b(camera|vision|webcam|pocket)\b/],
    ["document",/\b(file|code|repository|docs?|pdf|document)\b/],
    ["system",/\b(system|status|health|cpu|gpu|diagnostic)\b/],
  ];
  const found=matches.find(([,pattern])=>pattern.test(value));
  if(found)showType(found[0]);
  else toast("This only changes UI panels. Speak to Jarvis for actual actions.");
}
function toggleDemo() {
  model.demo=!model.demo;
  if(model.demo) {
    const now=Date.now()/1000;
    model.local.set("demo.research", {
      id:"demo.research",type:"research",title:"How contextual visuals appear",
      summary:"This is a fictional preview. In the real interface, validated source-grounded research will appear here only after a Jarvis capability publishes it.",
      source:"demo",observed_at:now,expires_at:now+900,priority:2
    });
    model.local.set("demo.work",{
      id:"demo.work",type:"info",title:"Panels adapt to conversation",
      summary:"Ask to see a file, work item or camera. Related panels can replace unpinned content. Pin what you want to keep. These examples are not live system data.",
      source:"demo",observed_at:now,expires_at:now+900,priority:1
    });
    toast("Sample-only preview enabled");
  } else {
    model.local.delete("demo.research");
    model.local.delete("demo.work");
    toast("Sample preview disabled");
  }
  render();
}
async function poll() {
  try {
    const response=await fetch("/api/snapshot",{cache:"no-store"});
    if(!response.ok)throw Error("offline");
    const snapshot=await response.json();
    if(snapshot.schema!==1||!Array.isArray(snapshot.panels)||!Array.isArray(snapshot.work))throw Error("invalid snapshot");
    if(!snapshot.vision || typeof snapshot.vision!=="object")snapshot.vision={connected:false,running:false};
    if(!Array.isArray(snapshot.health))snapshot.health=[];
    model.snapshot=snapshot;
    // Refresh manually opened status panels as canonical read-only evidence
    // changes, without replaying their orb-origin reveal animation.
    for(const [id,p] of model.local){
      if(["work","system","vision"].includes(p.type)){
        const updated=panelFromType(p.type);
        p.summary=updated.summary;
        model.local.set(id,p);
      }
    }
    // A topic that changes should replace transient unpinned context. The
    // server owns prioritization; the UI merely presents its bounded snapshot.
    render();
  } catch (_) {
    if(model.snapshot.runtime_connected || model.snapshot.voice_state!=="offline") {
      model.snapshot={schema:1,seq:0,runtime_connected:false,voice_state:"offline",panels:[],work:[],vision:{connected:false,running:false},health:[]};
      toast("JARVIS visual feed disconnected");
    }
    render();
  }
}
el("commandForm").addEventListener("submit",(event)=>{
  event.preventDefault();parseCommand(el("visualCommand").value);el("visualCommand").value="";
});
document.querySelectorAll(".rail-button[data-panel]").forEach(b=>b.addEventListener("click",()=>showType(b.dataset.panel)));
document.querySelector(".rail-button[data-action=home]").addEventListener("click",goHome);
el("orbToggle").addEventListener("click",()=>{
  const nowOpen=el("orbToggle").getAttribute("aria-expanded")!=="true";
  setRadialMenu(nowOpen);
  if(nowOpen)projectionGlow();
});
document.querySelectorAll("[data-orb-panel]").forEach(button=>{
  button.addEventListener("click",()=>showType(button.dataset.orbPanel));
});
el("backHome").addEventListener("click",goHome);
el("previewButton").addEventListener("click",toggleDemo);
el("clearButton").addEventListener("click",()=>{
  model.local.clear();
  for(const p of model.snapshot.panels) {
    if(!model.pinned.has(p.id))model.dismissed.set(p.id,p.observed_at);
  }
  render();
});
el("helpButton").addEventListener("click",()=>el("helpDialog").showModal());
el("closeHelp").addEventListener("click",()=>el("helpDialog").close());
document.addEventListener("keydown",(event)=>{
  if(event.key==="Escape" && el("orbToggle").getAttribute("aria-expanded")==="true"){
    setRadialMenu(false);event.preventDefault();return;
  }
  if(event.ctrlKey && event.key.toLowerCase()==="k"){event.preventDefault();el("visualCommand").focus();}
  if(event.key==="Escape" && !el("helpDialog").open && document.activeElement!==el("visualCommand"))goHome();
});
// ---- Animated offline-capable Canvas2D orb (no CDN and no heavy 3D engine). ----
const canvas=el("orbCanvas");
const ctx=canvas.getContext("2d",{alpha:true});
const reduced=window.matchMedia("(prefers-reduced-motion: reduce)");
const QUALITIES=["cinematic","balanced","eco"];
function savedQuality(){
  try{
    const saved=localStorage.getItem("jarvis.ui.visual-quality");
    return QUALITIES.includes(saved)?saved:"cinematic";
  }catch(_){return "cinematic";}
}
function applyQuality(next){
  model.quality=next;
  el("app").dataset.quality=next;
  el("motionButton").textContent="FX: "+next.toUpperCase();
  el("motionButton").setAttribute("aria-label","Visual effects quality: "+next);
  try{localStorage.setItem("jarvis.ui.visual-quality",next);}catch(_){/* optional preference */}
  resize();
}
el("motionButton").addEventListener("click",()=>{
  const index=QUALITIES.indexOf(model.quality);
  applyQuality(QUALITIES[(index+1)%QUALITIES.length]);
  toast("Visual effects: "+model.quality);
});
let width=440,height=440,prev=0,frame=0,phase=0;
const particles=Array.from({length:110},(_,i)=>({
  a:i*2.39996,r:.16+((i*31)%89)/115,s:.12+((i*13)%23)/65,
  size:.5+((i*19)%8)/8,offset:((i*71)%31)/10
}));
function resize() {
  const box=canvas.getBoundingClientRect();
  width=Math.max(1,Math.round(box.width));height=Math.max(1,Math.round(box.height));
  const dpr=Math.min(window.devicePixelRatio||1,model.quality==="eco"?1:1.75);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
  ctx.setTransform(dpr,0,0,dpr,0,0);
  draw(performance.now()/1000);
}
function draw(t) {
  const w=width,h=height,cx=w/2,cy=h/2,r=Math.min(w,h)*.405;
  ctx.clearRect(0,0,w,h);
  const state=el("app").dataset.state;
  const active=state==="speaking"||state==="listening",thinking=state==="thinking";
  const projecting=el("app").classList.contains("is-projecting");
  const energy=projecting?1.33:active?1.13:thinking?1.09:1;
  const breath=1+Math.sin(t*1.4)*.024;
  const halo=ctx.createRadialGradient(cx,cy,0,cx,cy,r*1.21);
  halo.addColorStop(0,"rgba(8,50,126,.11)");
  halo.addColorStop(.56,thinking?"rgba(87,43,164,.2)":"rgba(14,111,215,.15)");
  halo.addColorStop(.83,"rgba(40,162,241,.14)");
  halo.addColorStop(1,"rgba(11,127,202,0)");
  ctx.fillStyle=halo;ctx.beginPath();ctx.arc(cx,cy,r*1.21,0,Math.PI*2);ctx.fill();
  const surface=ctx.createRadialGradient(cx-r*.24,cy-r*.35,r*.04,cx,cy,r*breath);
  surface.addColorStop(0,"rgba(43,156,238,.40)");
  surface.addColorStop(.24,"rgba(12,68,147,.50)");
  surface.addColorStop(.67,thinking?"rgba(51,24,111,.63)":"rgba(4,27,76,.81)");
  surface.addColorStop(.92,"rgba(1,11,35,.94)");
  surface.addColorStop(1,"rgba(29,170,248,.29)");
  ctx.fillStyle=surface;ctx.beginPath();ctx.arc(cx,cy,r*breath,0,Math.PI*2);ctx.fill();
  ctx.save();ctx.beginPath();ctx.arc(cx,cy,r*.98,0,2*Math.PI);ctx.clip();
  ctx.globalCompositeOperation="screen";
  for(let j=0;j<9;j++){
    const y=cy+(j-4)*r*.145;
    const amp=r*(.07+.04*Math.sin(t*.85+j*1.2));
    ctx.beginPath();
    for(let i=0;i<=110;i++){
      const x=cx-r+i*r*2/110;
      const envelope=Math.sqrt(Math.max(0,1-((x-cx)/r)**2));
      const yy=y+Math.sin(i*.13+t*(j%2?-.65:.9)+j*.65)*amp*envelope;
      if(i===0)ctx.moveTo(x,yy);else ctx.lineTo(x,yy);
    }
    ctx.strokeStyle=j%3===0?"rgba(156,135,255,.24)":"rgba(46,192,253,.16)";
    ctx.lineWidth=.7+(j%3)*.32;ctx.stroke();
  }
  for(const p of particles){
    const a=p.a+t*p.s*(thinking?1.8:1);
    const rr=r*p.r;
    const xx=cx+Math.cos(a)*rr;
    const yy=cy+Math.sin(a*1.2+p.offset)*rr*.70;
    const alpha=.2+.4*(.5+.5*Math.sin(t*1.7+p.offset));
    ctx.beginPath();ctx.arc(xx,yy,p.size,0,Math.PI*2);
    ctx.fillStyle="rgba(122,217,255,"+alpha.toFixed(3)+")";ctx.fill();
  }
  // A second field of refracted filaments gives the core spherical depth.
  // Lower visual-quality modes reduce work and preserve voice latency.
  if(model.quality!=="eco"){
    const spokes=model.quality==="balanced"?22:42;
    for(let k=0;k<spokes;k++){
      const angle=(k/spokes)*Math.PI*2 + t*(k%2?-.018:.023);
      const radial=r*(.48+((k*17)%23)/60);
      const x1=cx+Math.cos(angle)*radial;
      const y1=cy+Math.sin(angle)*radial;
      const x2=cx+Math.cos(angle+.17)*radial*.89;
      const y2=cy+Math.sin(angle+.17)*radial*.89;
      ctx.beginPath();ctx.moveTo(x1,y1);
      ctx.quadraticCurveTo(cx,cy,x2,y2);
      ctx.strokeStyle=k%5===0?"rgba(161,142,255,.09)":"rgba(67,182,251,.047)";
      ctx.lineWidth=.6;
      ctx.stroke();
    }
  }
  ctx.restore();
  ctx.lineCap="round";
  for(let j=0;j<4;j++) {
    const offset=j*.039;
    const rr=r*(1+offset)*breath;
    const start=t*(j%2?-.1:.13)+j*1.6;
    ctx.beginPath();ctx.arc(cx,cy,rr,start,start+Math.PI*(.63+j*.04));
    ctx.strokeStyle=j===1?"rgba(155,141,254,.65)":"rgba(67,206,255,"+(.3+j*.13)+")";
    ctx.lineWidth=(j===0?2.6:1.05)*energy;ctx.shadowColor="#25bbff";ctx.shadowBlur=j===0?16:5;ctx.stroke();
  }
  ctx.shadowBlur=0;
  // Fresnel edge: the illuminated hemisphere seems glass-like rather than
  // a flat circle, and its changing rim follows the existing state signal.
  const fresnel=ctx.createRadialGradient(cx-r*.12,cy-r*.13,r*.60,cx,cy,r*1.012);
  fresnel.addColorStop(0,"rgba(0,90,160,0)");
  fresnel.addColorStop(.80,"rgba(15,100,200,.02)");
  fresnel.addColorStop(.95,thinking?"rgba(164,116,244,.23)":"rgba(75,198,253,.22)");
  fresnel.addColorStop(1,"rgba(122,224,255,.045)");
  ctx.beginPath();ctx.arc(cx,cy,r*breath,0,Math.PI*2);
  ctx.fillStyle=fresnel;ctx.fill();
  const glint=ctx.createRadialGradient(cx-r*.32,cy-r*.35,0,cx-r*.32,cy-r*.35,r*.6);
  glint.addColorStop(0,"rgba(191,239,255,.20)");glint.addColorStop(1,"rgba(0,138,255,0)");
  ctx.fillStyle=glint;ctx.beginPath();ctx.arc(cx-r*.32,cy-r*.35,r*.6,0,Math.PI*2);ctx.fill();
  // Orbital filaments move on tilted ellipses, creating parallax and a
  // holographic sense of depth without a heavyweight realtime 3D engine.
  if(model.quality!=="eco"){
    ctx.save();
    ctx.translate(cx,cy);
    for(let orbit=0;orbit<4;orbit++){
      ctx.save();
      ctx.rotate(t*(orbit%2?-.09:.07)+orbit*1.24);
      ctx.scale(1,.25+(orbit%3)*.11);
      ctx.beginPath();
      const start=t*(orbit%2?-.48:.31)+orbit*1.5;
      ctx.arc(0,0,r*(.65+orbit*.12),start,start+Math.PI*(.62+orbit*.08));
      ctx.strokeStyle=orbit===2?"rgba(179,135,255,.58)":"rgba(89,220,255,"+(.17+orbit*.09)+")";
      ctx.lineWidth=orbit%2?1.4:1;
      ctx.shadowColor="#3aceff";ctx.shadowBlur=orbit===1?18:8;
      ctx.stroke();
      ctx.restore();
    }
    ctx.restore();ctx.shadowBlur=0;
  }
  // Tiny visible orbit nodes brighten when a projection is materializing.
  for(let k=0;k<(model.quality==="eco"?4:11);k++){
    const a=t*(k%2?-.17:.21)+k*2.399;
    const rr=r*(.79+(k%4)*.088);
    const z=Math.sin(a+k*.61)*.44;
    const px=cx+Math.cos(a)*rr;
    const py=cy+Math.sin(a*1.17+k*.43)*rr*.36;
    ctx.beginPath();ctx.arc(px,py,1.1+(z+1)*.6,0,Math.PI*2);
    ctx.fillStyle="rgba(134,224,255,"+(.29+.37*(z+1)/2)+")";
    ctx.shadowColor="#6bdcff";ctx.shadowBlur=10;ctx.fill();
  }
  ctx.shadowBlur=0;
  const beacon=ctx.createRadialGradient(cx,cy,r*.02,cx,cy,r*.67);
  beacon.addColorStop(0,thinking?"rgba(174,124,255,.22)":"rgba(59,182,255,.17)");
  beacon.addColorStop(1,"rgba(0,115,235,0)");
  ctx.fillStyle=beacon;ctx.beginPath();ctx.arc(cx,cy,r*.67,0,Math.PI*2);ctx.fill();
}
function animate(now) {
  frame=requestAnimationFrame(animate);
  if(document.hidden||!ctx)return;
  if(reduced.matches){if(prev===0)draw(0);prev=1;return;}
  const limit=model.quality==="eco"?15:
    model.quality==="balanced"?30:
    (el("app").dataset.state==="idle"?40:60);
  if(now-prev<1000/limit)return;
  prev=now;
  draw(now/1000);
}
window.addEventListener("resize",()=>{resize();scheduleBeams();});
document.addEventListener("visibilitychange",()=>{prev=0;});
reduced.addEventListener("change",()=>{prev=0;draw(0);});
clock();setInterval(clock,10000);
applyQuality(savedQuality());
setRadialMenu(false);
render();resize();frame=requestAnimationFrame(animate);poll();setInterval(poll,1100);
