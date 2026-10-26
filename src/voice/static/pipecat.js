/* HomeTruth voice tour — Pipecat client. Speech, interruption and turn-taking run on the server (src/voice/pipecat_app.py);
   this page connects over SmallWebRTC (one click on Start, or pressing Enter in the box, which Chrome also needs before it
   may play sound), plays the bot's audio track, meters both audio tracks for the voice indicator, and hands the events the
   server sends as RTVI server messages to the shared renderer (ui.js) in the order they are spoken. */
import { PipecatClient } from 'https://cdn.jsdelivr.net/npm/@pipecat-ai/client-js@1.14.0/+esm';
import { SmallWebRTCTransport } from 'https://cdn.jsdelivr.net/npm/@pipecat-ai/small-webrtc-transport@1.11.0/+esm';

const $ = (s) => document.querySelector(s);
const ui = HTUI.create();
const el = Object.assign(ui.el, { connect: $('#connect'), connectLabel: $('#connect-label'), mic: $('#mic'), micLabel: $('#mic-label'), send: $('#send'), stop: $('#stop'),
  reset: $('#reset'), leave: $('#leave'), hint: $('#hint'), conn: $('#conn'), connText: $('#conn-text'), audio: $('#bot-audio') });
const S = { hello: null, client: null, connecting: false, ready: false, micWanted: true, hasMic: false, phase: 'idle', label: 'Ready', botSpeaking: false,
  expectAnswer: false, queued: null, turnT0: 0, firstEventMs: null, firstWordMs: null, events: 0, log: [], ac: null, meters: [] };
const latency = () => ui.latency(S.firstEventMs, S.firstWordMs);
const conn = (state, text) => { el.conn.dataset.state = state; el.connText.textContent = text; };
ui.phase('idle', 'Not connected');

// the renter id outlives the page (localStorage): the server keeps what this renter asked for last time under it (memory.py) and greets them with it
try { S.renter = localStorage.getItem('ht_renter'); } catch (e) {}
if (!S.renter) { S.renter = 'r-' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 24) : String(Date.now())); try { localStorage.setItem('ht_renter', S.renter); } catch (e) {} }
async function forgetMe() { try { await fetch('/api/forget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ renter: S.renter }) }); } catch (e) {} location.reload(); }
fetch('/api/hello?renter=' + encodeURIComponent(S.renter)).then((r) => r.json()).then((h) => {
  S.hello = h;
  if (h.memory && ui.remembered) ui.remembered(h.memory, { sameAgain: () => { if (!S.client || !S.ready) { S.queued = 'Same again'; ui.userSaid('Same again'); connect(); } else sendText('Same again'); }, forget: forgetMe });
  const fake = h.mode === 'fake-speech';
  S.micWanted = !fake;
  const voice = String(h.tts).match(/EN-US\.(\w+)/);
  const hears = /parakeet/i.test(h.stt) ? 'NVIDIA Parakeet' : h.stt;
  const speaks = /magpie/i.test(h.tts) ? 'Magpie' + (voice ? ' (' + voice[1] + ')' : '') : String(h.tts).split(',')[0];
  ui.meta('voice', fake ? `Typing mode · speaks with ${speaks}` : `Voice: ${hears} + ${speaks}`);
  ui.meta('parser', h.needs_parser === 'llm' ? `Needs read by Nemotron via ${String(h.llm).split(' · ')[0].replace(/ Runtime$/, '')}` : 'Needs read by rules');
  if (fake) el.hint.innerHTML = 'Press <b>Start</b> to connect. This server runs in typing mode: type what you need and the answers are spoken back.';
}).catch(() => { ui.note('Server unreachable'); conn('error', 'Server unreachable'); });

/* ---------------- audio metering for the voice indicator (local mic + bot track) ---------------- */
function meter(track, set) {
  try {
    S.ac = S.ac || new (window.AudioContext || window.webkitAudioContext)();
    const src = S.ac.createMediaStreamSource(new MediaStream([track])); const an = S.ac.createAnalyser(); an.fftSize = 512; src.connect(an);
    const buf = new Uint8Array(an.fftSize); S.meters.push({ an, buf, set, track });
    if (S.meters.length === 1) tick();
  } catch (e) { /* no metering: the indicator still animates by phase */ }
}
function tick() {
  S.meters = S.meters.filter((m) => m.track.readyState !== 'ended');
  for (const m of S.meters) { m.an.getByteTimeDomainData(m.buf); let sum = 0; for (let i = 0; i < m.buf.length; i++) { const v = (m.buf[i] - 128) / 128; sum += v * v; } m.set(Math.min(1, Math.sqrt(sum / m.buf.length) * 3.5)); }
  if (S.meters.length) requestAnimationFrame(tick); else { ui.level(0); ui.botLevel(0.5); }
}
function playBot() {  // Start was a click, so this normally just plays; if Chrome still blocks it, play on the next click or key
  el.audio.play().catch(() => {
    const retry = () => { el.audio.play().catch(() => {}); };
    document.addEventListener('pointerdown', retry, { once: true }); document.addEventListener('keydown', retry, { once: true });
  });
}

/* ---------------- events from the server, already in spoken order ---------------- */
function apply(ev) {
  if (!ev || !ev.type) return;
  S.events++; ui.events(S.events); S.log.push({ t: Date.now(), ev }); if (S.log.length > 200) S.log.shift();
  if (S.firstEventMs == null && S.turnT0) { S.firstEventMs = Math.round(performance.now() - S.turnT0); latency(); }
  switch (ev.type) {
    case 'state': S.phase = ev.phase; S.label = ev.label; ui.state(ev, !S.botSpeaking); break;
    case 'needs': ui.needs(ev); break;
    case 'source': ui.source(ev); break;
    case 'card': ui.card(ev.listing); break;
    case 'card_update': ui.cardUpdate(ev); break;
    case 'change': ui.change(ev); break;
    case 'highlight': ui.highlight(ev); break;
    case 'evidence': ui.evidence(ev); break;
    case 'ask': S.expectAnswer = true; break;
    case 'say': ui.caption(ev.text); break;
    case 'done':
      if (S.expectAnswer) { S.expectAnswer = false; S.phase = 'listening'; S.label = 'Your turn'; } else { S.phase = 'idle'; S.label = 'Ready'; }
      if (!S.botSpeaking) ui.phase(S.phase, S.label);
      break;
    case 'error': ui.error(ev.message); break;
  }
}
function startTurnClock() { S.turnT0 = performance.now(); S.firstEventMs = null; S.firstWordMs = null; latency(); }
function micLabel() {
  const on = !!(S.client && S.client.isMicEnabled);
  el.mic.classList.toggle('on', on); el.mic.setAttribute('aria-pressed', String(on)); el.micLabel.textContent = on ? 'Mic on' : 'Mic off';
  if (S.ready) conn('live', on ? 'Voice line live · mic on' : 'Voice line live · typing');
}
function setConnected(on) {
  el.connect.hidden = on; el.connect.disabled = false; el.connectLabel.textContent = 'Start';
  el.mic.hidden = !on; el.mic.disabled = !S.hasMic; el.hint.hidden = on; el.leave.hidden = !on;
  el.stop.disabled = !on; el.reset.hidden = !on; el.send.classList.toggle('primary', on);
}
async function micPresent() {
  try { return (await navigator.mediaDevices.enumerateDevices()).some((d) => d.kind === 'audioinput'); } catch (e) { return false; }
}
function sendText(t) {
  if (S.botSpeaking) ui.interrupt();
  startTurnClock(); ui.userSaid(t); ui.phase('thinking', 'Thinking');
  S.client.sendClientMessage('hometruth-text', { text: t });
}

async function fetchIceServers() {  // same list the server uses: STUN, or Cloudflare TURN credentials when the server has a TURN key (campus box behind NAT)
  try { const r = await fetch('/api/ice', { cache: 'no-store' }); if (!r.ok) return []; const j = await r.json(); return Array.isArray(j.iceServers) ? j.iceServers : []; }
  catch (_) { return []; }
}

function makeClient(useMic, iceServers) {
  // with ICE servers given, gather every candidate (incl. relay) before sending the offer, so the server can reach us through the NAT
  const transport = iceServers && iceServers.length ? new SmallWebRTCTransport({ iceServers, waitForICEGathering: true }) : new SmallWebRTCTransport();
  return new PipecatClient({
    transport, enableMic: useMic, enableCam: false,
    callbacks: {
      onTransportStateChanged: (s) => {
        if (s === 'error') conn('error', 'Connection error');
        else if (s === 'disconnected') { if (!S.connecting) conn('idle', 'Voice line not connected'); }
        else if (s !== 'ready') conn('connecting', 'Connecting…');
      },
      onConnected: () => { setConnected(true); micLabel(); },
      onDisconnected: () => {
        if (S.connecting) return;  // a failed first attempt; connect() decides what to show
        S.client = null; S.ready = false; setConnected(false); conn('idle', 'Voice line not connected'); ui.phase('idle', 'Not connected');
      },
      onBotReady: () => {
        S.ready = true; micLabel(); ui.phase('idle', 'Ready');
        S.client.sendClientMessage('hometruth-renter', { renter: S.renter });  // with a memory on file the server speaks first ("Welcome back…")
        if (S.queued) { const t = S.queued; S.queued = null; sendText(t); }
        else if (!(S.hello && S.hello.memory)) { ui.caption('What are you after?'); if (!(S.client && S.client.isMicEnabled)) el.text.focus(); }
      },
      onServerMessage: (data) => apply(data),
      onUserTranscript: (d) => { ui.transcript(d.text, !d.final); },
      onUserStartedSpeaking: () => { if (S.botSpeaking) ui.interrupt(); ui.phase('listening', 'Go ahead'); },
      onUserStoppedSpeaking: () => { startTurnClock(); ui.phase('thinking', 'Thinking'); },
      onBotStartedSpeaking: () => { S.botSpeaking = true; if (S.firstWordMs == null && S.turnT0) { S.firstWordMs = Math.round(performance.now() - S.turnT0); latency(); } ui.phase('speaking', 'Speaking'); },
      onBotStoppedSpeaking: () => { S.botSpeaking = false; ui.phase(S.phase, S.label); },
      onTrackStarted: (track, p) => {
        if (track.kind !== 'audio') return;
        if (p && p.local) { meter(track, ui.level); return; }
        el.audio.srcObject = new MediaStream([track]); playBot(); meter(track, ui.botLevel);
      },
      onMicUpdated: () => micLabel(),
      onError: (m) => ui.error((m && m.data && (m.data.error || m.data.message)) || 'Connection error'),
    },
  });
}
async function connect() {
  if (S.client || S.connecting) return;
  S.connecting = true; el.connect.disabled = true; el.connectLabel.textContent = 'Connecting…'; conn('connecting', 'Connecting…'); ui.phase('thinking', 'Connecting');
  S.hasMic = await micPresent();
  let useMic = S.micWanted && S.hasMic;
  if (S.micWanted && !S.hasMic) ui.note('No microphone found, so type instead.');
  const iceServers = await fetchIceServers();
  for (let attempt = 0; attempt < 2; attempt++) {
    const client = makeClient(useMic, iceServers); S.client = client;
    try { await client.connect({ webrtcRequestParams: { endpoint: '/api/offer' } }); S.connecting = false; return; }
    catch (e) {
      try { await client.disconnect(); } catch (_) { /* already gone */ }
      S.client = null;
      if (useMic) { useMic = false; S.hasMic = false; ui.note('Microphone unavailable, so type instead.'); continue; }  // retry once without the mic
      S.connecting = false; setConnected(false); conn('error', 'Could not connect');
      ui.error('Could not connect: ' + (e && e.message ? e.message : e));
      return;
    }
  }
}
el.connect.onclick = connect;
$('#composer').onsubmit = (e) => {
  e.preventDefault(); const t = el.text.value.trim(); if (!t) return;
  el.text.value = '';
  if (!S.client || !S.ready) { S.queued = t; ui.userSaid(t); connect(); return; }  // not connected yet: connect first, send when the bot is ready
  sendText(t);
};
el.mic.onclick = () => { if (!S.client) return; S.micWanted = !S.client.isMicEnabled; S.client.enableMic(S.micWanted); micLabel(); };
el.stop.onclick = () => { if (S.client) { S.client.sendClientMessage('hometruth-stop', {}); ui.interrupt(); } };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.client) { S.client.sendClientMessage('hometruth-stop', {}); ui.interrupt(); } });
el.reset.onclick = () => { if (S.client) S.client.sendClientMessage('hometruth-reset', {}); ui.clear(); ui.caption('New search. What are you after?'); ui.phase('idle', 'Ready'); };
el.leave.onclick = async () => {
  const c = S.client; S.client = null; S.ready = false;
  if (c) { try { await c.disconnect(); } catch (e) { /* already gone */ } }
  setConnected(false); conn('idle', 'Voice line not connected'); ui.phase('idle', 'Not connected');
};
window.HT = { S, ui, apply, connect };  // for debugging in the console; S.log holds the last 200 events
