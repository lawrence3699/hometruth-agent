/* HomeTruth voice tour — browser side.
   Jobs: stream events from /api/turn, speak sentences in order (prefetched TTS), hand each event to the shared renderer (ui.js)
   in spoken order, listen with Web Speech API, and handle barge-in with an energy VAD + echo filters.
   The five interruption standards live here: see README. */
(() => {
'use strict';
const $ = (s) => document.querySelector(s);
const ui = HTUI.create();  // shared renderer (ui.js): listing wall, caption, needs, sources, cards, evidence, changes
const el = Object.assign(ui.el, { mic: $('#mic'), micLabel: $('#mic-label'), meter: $('#meter'), stop: $('#stop'), reset: $('#reset'), headphones: $('#headphones'), autolisten: $('#autolisten') });
const latency = () => ui.latency(S.firstEventMs, S.firstAudioMs);
const FILLERS = new Set(['yeah','yes','ok','okay','mm','mhm','uh','huh','right','sure','cool','got','it','i','see','alright','fine','yep','yup','hmm','oh','ah','nice','great','good','thanks','thank','you','aha','hm','yea','mmm']);
const S = {
  session: null, hello: null, gen: 0, ac: null, timeline: [], pumping: false, playing: false, streamOpen: false,
  currentSay: null, lastSaid: '', spokenIdx: null, currentListing: null, expectAnswer: false,
  turnT0: 0, firstEventMs: null, firstAudioMs: null, events: 0, micOn: false, pausedForUser: false, holdForFinal: false,
  resumeTimer: null, recog: null, recogWanted: false, speechStartT: 0, lastTurnText: '', interruptedFlag: false,
  lastBusy: null, pauseGuard: null,  // lastBusy: the server's last thinking/searching state, shown again between sentences while it is still working
  beatDone: null, beatTimer: null, stoppedAt: null, headphonesTouched: false, duckTimer: null, quietAt: 0,
};
// 10-28 (docs/12): duck-on-double-talk in speakers mode is on unless ?duck=0 or localStorage ht_duck=0
const DUCK = (() => { try { if (/[?&]duck=0\b/.test(location.search)) return false; return localStorage.getItem('ht_duck') !== '0'; } catch (e) { return true; } })();
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tokens = (t) => (t || '').toLowerCase().replace(/[^a-z0-9' ]+/g, ' ').split(/\s+/).filter(Boolean);
const busy = () => S.streamOpen || S.timeline.length > 0 || S.playing || !!S.currentSay;
function report(where, e) {  // a page that stops moving must leave a trace: console + runs/voice_log.jsonl (kind client_error)
  console.error(where, e);
  try { navigator.sendBeacon('/api/metric', new Blob([JSON.stringify({ kind: 'client_error', session: S.session, where, error: String((e && e.stack) || e).slice(0, 600) })], { type: 'application/json' })); } catch (err) {}
}
window.addEventListener('error', (e) => report('window', e.error || e.message));
window.addEventListener('unhandledrejection', (e) => report('promise', e.reason));
/* ---------------- session + server info ---------------- */
// every page load is a new conversation: the page starts at the home stage anyway, and a server session that still holds last
// time's plan would skip the welcome-back line (policy.py _search / welcome need a session with no plan yet); only the renter id persists
S.session = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
// the renter id outlives the session (localStorage): the server keeps what this renter asked for last time under it (memory.py) and greets them with it
try { S.renter = localStorage.getItem('ht_renter'); } catch (e) {}
if (!S.renter) { S.renter = 'r-' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 24) : String(Date.now())); try { localStorage.setItem('ht_renter', S.renter); } catch (e) {} }
S.welcomed = false;
fetch('/api/hello?renter=' + encodeURIComponent(S.renter)).then((r) => r.json()).then((h) => {
  S.hello = h; ui.meta('voice', `Voice: ${h.tts_backend === 'say' ? 'macOS say' : h.tts_backend}${h.voice ? ' (' + h.voice + ')' : ''}`);
  if (h.memory && ui.remembered) ui.remembered(h.memory, { sameAgain: () => sendTurn('Same again', 'text'), forget: forgetMe });
}).catch(() => { ui.note('Server unreachable'); });
async function forgetMe() { try { await fetch('/api/forget', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ renter: S.renter }) }); } catch (e) {} location.reload(); }
async function sendWelcome() {  // the server speaks first ("Welcome back. Last time it was … Same again?") once the renter has clicked something that lets the page play sound
  if (S.welcomed || !(S.hello && S.hello.memory) || busy() || S.lastTurnText) return;
  S.welcomed = true;
  const gen = ++S.gen; const ac = new AbortController(); S.ac = ac;
  S.turnT0 = performance.now(); S.firstEventMs = null; S.firstAudioMs = null; S.streamOpen = true;
  let resp;
  try { resp = await fetch('/api/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: S.session, renter: S.renter, welcome: true, source: 'memory' }), signal: ac.signal }); }
  catch (e) { if (gen === S.gen) S.streamOpen = false; return; }
  await readEvents(resp, gen, ac);
}


/* ---------------- TTS fetch with a small concurrency cap ---------------- */
let inflight = 0; const waiters = [];
const acquire = () => new Promise((r) => { if (inflight < 3) { inflight++; r(); } else waiters.push(() => { inflight++; r(); }); });
const release = () => { inflight--; const w = waiters.shift(); if (w) w(); };
const TTS_WAIT_MS = 12000;  // audio that has not arrived by then is read by the browser voice instead: one hung request must never freeze the turn
function ttsSignal(signal) { try { return AbortSignal.any ? AbortSignal.any([signal, AbortSignal.timeout(TTS_WAIT_MS)]) : signal; } catch (e) { return signal; } }
async function fetchTTS(text, signal, step, status) {  // step / status let the server pick the emotion tag for this sentence (tone.py, ElevenLabs only)
  if (S.hello && S.hello.tts_backend === 'browser') return null;
  await acquire();
  try {
    const r = await fetch('/api/tts?text=' + encodeURIComponent(text) + (step ? '&step=' + encodeURIComponent(step) : '') + (status ? '&status=' + encodeURIComponent(status) : ''), { signal: ttsSignal(signal) });
    if (r.status === 204 || !r.ok) return null; return await r.blob();
  }
  finally { release(); }
}

/* ---------------- player: Web Audio (HTMLAudio got paused by the embedded browser right after play()) ---------------- */
let browserDone = null;
const AC = window.AudioContext || window.webkitAudioContext;
let actx = null;
function ensureCtx() { if (!actx) actx = new AC(); if (actx.state === 'suspended') actx.resume().catch(() => {}); return actx; }
// 10-27 "it never talks": on an iPhone / iPad, Web Audio is muted by the ring/silent switch unless the page says it is a media player.
// navigator.audioSession (Safari 16.4+) does that; with the mic on it has to be play-and-record. Older iOS: a looping silent <audio>
// started inside the first tap moves the page to the playback category the same way.
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
function audioSession(mic) { try { if (navigator.audioSession) navigator.audioSession.type = mic ? 'play-and-record' : 'playback'; } catch (e) {} }
audioSession(false);
let unmuteEl = null;
function unmuteIOS() {
  if (!IOS || navigator.audioSession || unmuteEl) return;
  const n = 4000, b = new ArrayBuffer(44 + n * 2), v = new DataView(b), w = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true); v.setUint32(28, 16000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
  unmuteEl = new Audio(URL.createObjectURL(new Blob([b], { type: 'audio/wav' }))); unmuteEl.loop = true; unmuteEl.setAttribute('playsinline', '');
  unmuteEl.play().catch(() => { unmuteEl = null; });
}
document.addEventListener('click', () => { ensureCtx(); unmuteIOS(); }, { capture: true });
document.addEventListener('touchend', () => { ensureCtx(); unmuteIOS(); }, { capture: true });
document.addEventListener('keydown', () => ensureCtx(), { capture: true });
let outGain = null, outAnalyser = null, outBuf = null;
function outChain(ctx) {  // every sentence plays through one gain (ducking) and one analyser (how loud we are right now)
  if (!outGain || outGain.context !== ctx) {
    outGain = ctx.createGain(); outAnalyser = ctx.createAnalyser(); outAnalyser.fftSize = 1024; outBuf = new Float32Array(outAnalyser.fftSize);
    outGain.connect(outAnalyser); outAnalyser.connect(ctx.destination);
  }
  return outGain;
}
function outDb() {
  if (!outAnalyser || !S.playing) return -100;
  outAnalyser.getFloatTimeDomainData(outBuf); let s = 0; for (let i = 0; i < outBuf.length; i++) s += outBuf[i] * outBuf[i];
  return 20 * Math.log10(Math.sqrt(s / outBuf.length) + 1e-7);
}
function duck(on) {  // speakers mode: someone talks over us → drop to a quarter volume until we know whether it was a real interruption
  if (!outGain) return;
  const t = outGain.context.currentTime; outGain.gain.cancelScheduledValues(t); outGain.gain.setTargetAtTime(on ? 0.25 : 1, t, on ? 0.02 : 0.12);
  S.ducked = on; clearTimeout(S.duckTimer);
  if (on) S.duckTimer = setTimeout(() => { if (S.ducked && !S.pausedForUser) duck(false); }, 2500);
}
const player = {
  src: null, done: null, buffer: null, startedAt: 0, pausedFlag: false, pauseOffset: 0, guard: null,
  async play(blob) {
    const ctx = ensureCtx();
    let buf = null;
    try { buf = await ctx.decodeAudioData(await blob.arrayBuffer()); } catch (e) { console.warn('decode failed', e); return; }
    return new Promise((resolve) => {
      const finish = () => { if (this.done !== finish) return; this.done = null; this.src = null; this.buffer = null; clearTimeout(this.guard); resolve(); };
      this.done = finish; this.buffer = buf; this.pausedFlag = false;
      this._start(ctx, 0, finish);
      if (S.firstAudioMs == null) { S.firstAudioMs = Math.round(performance.now() - S.turnT0); latency(); metric(); }
    });
  },
  _start(ctx, offset, finish) {
    const s = ctx.createBufferSource(); s.buffer = this.buffer; s.connect(outChain(ctx));
    s.onended = () => { if (this.src === s && !this.pausedFlag) finish(); };
    this.src = s; this.startedAt = ctx.currentTime - offset; s.start(0, offset);
    clearTimeout(this.guard); this.guard = setTimeout(() => { if (this.done === finish && !this.pausedFlag) { console.warn('audio guard fired'); finish(); } }, (this.buffer.duration - offset) * 1000 + 1500);
  },
  get audio() { return this.buffer ? { currentTime: this.pausedFlag ? this.pauseOffset : actx.currentTime - this.startedAt, duration: this.buffer.duration, paused: this.pausedFlag, ended: false } : null; },
  pause() {
    if (S.playing) S.quietAt = performance.now();  // the recogniser may still deliver our last words for a moment (stripEcho)
    if (this.src && this.buffer && !this.pausedFlag) { this.pausedFlag = true; this.pauseOffset = Math.max(0, actx.currentTime - this.startedAt); clearTimeout(this.guard); try { this.src.stop(); } catch (e) {} }
    if (window.speechSynthesis && speechSynthesis.speaking) speechSynthesis.pause();
  },
  resume() {
    if (this.pausedFlag && this.buffer && this.done) { this.pausedFlag = false; this._start(actx, Math.min(this.pauseOffset, Math.max(0, this.buffer.duration - 0.05)), this.done); }
    if (window.speechSynthesis && speechSynthesis.paused) speechSynthesis.resume();
  },
  stop() {
    if (S.playing) S.quietAt = performance.now();
    const d = this.done; this.pausedFlag = false; clearTimeout(this.guard);
    if (this.src) { const s = this.src; this.src = null; try { s.stop(); } catch (e) {} }
    if (d) d();
    if (window.speechSynthesis) speechSynthesis.cancel();
    if (browserDone) { const b = browserDone; browserDone = null; b(); }
  },
};
function speakBrowser(text) { return new Promise((resolve) => {
  if (!window.speechSynthesis) return resolve();
  const u = new SpeechSynthesisUtterance(text); u.lang = 'en-AU'; u.rate = 1.0;
  browserDone = resolve; u.onend = () => { if (browserDone === resolve) { browserDone = null; resolve(); } }; u.onerror = u.onend;
  u.onstart = () => { if (S.firstAudioMs == null) { S.firstAudioMs = Math.round(performance.now() - S.turnT0); latency(); metric(); } };
  speechSynthesis.speak(u);
}); }

/* ---------------- event stream ---------------- */
async function sendTurn(text, source, interrupted) {
  text = (text || '').trim(); if (!text) return;
  if (!(interrupted && interrupted.active) && S.stoppedAt) interrupted = S.stoppedAt;  // stopped with the Stop button / Esc / Pause: tell the server where
  S.stoppedAt = null;
  const gen = ++S.gen;
  if (S.ac) S.ac.abort();
  const ac = new AbortController(); S.ac = ac;
  endBeat(); duck(false);
  player.stop(); S.timeline = []; S.currentSay = null; S.playing = false; S.expectAnswer = false; S.lastBusy = null; clearTimeout(S.pauseGuard);
  S.turnT0 = performance.now(); S.firstEventMs = null; S.firstAudioMs = null; S.lastTurnText = text; S.interruptedFlag = !!(interrupted && interrupted.active);
  ui.userSaid(text); ui.phase('thinking', 'Analysing'); latency();
  S.streamOpen = true; S.welcomed = true;
  let resp;
  try { resp = await fetch('/api/turn', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: S.session, renter: S.renter, text, source, listing_id: S.currentListing, interrupted: interrupted || { active: false } }), signal: ac.signal }); }
  catch (e) { if (gen === S.gen) { S.streamOpen = false; if (e.name !== 'AbortError') ui.error('Server unreachable: ' + e.message); } return; }
  await readEvents(resp, gen, ac);
}
async function readEvents(resp, gen, ac) {
  const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const line of chunk.split('\n')) if (line.startsWith('data: ')) { try { onEvent(JSON.parse(line.slice(6)), gen, ac); } catch (e) { console.warn('bad event', e); } }
      }
    }
  } catch (e) { if (e.name !== 'AbortError') console.warn(e); }
  if (gen === S.gen) S.streamOpen = false;
}
function onEvent(ev, gen, ac) {
  if (gen !== S.gen) return;
  S.events++; ui.events(S.events);
  if (S.firstEventMs == null) { S.firstEventMs = Math.round(performance.now() - S.turnT0); latency(); }
  if (ev.type === 'highlight') S.evStatus = ev.status;  // the line about to be spoken: its status picks the emotion tag (arrival order = speaking order)
  if (ev.type === 'say') ev._audio = fetchTTS(ev.text, ac.signal, ev.step, /^L\d+\./.test(ev.step || '') ? S.evStatus : null).catch(() => null);
  if (ev.type === 'error') { ui.error(ev.message); return; }
  S.timeline.push(ev); pump(gen);
}
async function pump(gen) {
  if (S.pumping) return; S.pumping = true;
  try { while (S.timeline.length && gen === S.gen) { const ev = S.timeline.shift(); try { await apply(ev, gen); } catch (e) { report('event ' + ev.type, e); } } }  // one bad event must not stop the ones after it
  finally { S.pumping = false; if (S.timeline.length && gen !== S.gen) pump(S.gen); }
}
async function apply(ev, gen) {
  switch (ev.type) {
    case 'state': S.lastBusy = (ev.phase === 'thinking' || ev.phase === 'searching') ? { phase: ev.phase, label: ev.label } : null; ui.state(ev); break;
    case 'needs': ui.needs(ev); break;
    case 'source': ui.source(ev); break;
    case 'card': ui.card(ev.listing); S.currentListing = ev.listing.id; break;
    case 'card_update': ui.cardUpdate(ev); break;
    case 'change': ui.change(ev); break;
    case 'highlight': ui.highlight(ev); S.currentListing = ev.listing_id; break;
    case 'evidence': ui.evidence(ev); break;
    case 'ask': S.expectAnswer = true; break;
    case 'say': await speak(ev, gen); break;
    case 'beat': await beat(ev, gen); break;
    case 'done':
      S.lastBusy = null;
      if (S.expectAnswer) { S.expectAnswer = false; ui.phase('listening', 'Your turn'); if (S.micOn || !el.autolisten.checked) {} else el.text.focus(); }
      else ui.phase('idle', 'Ready');
      break;
  }
}
function beat(ev, gen) {  // 10-28: a short pause after each place; nobody talking over us, so this is where a renter on speakers gets a word in
  if (gen !== S.gen || S.pausedForUser) return;
  ui.phase('listening', 'Your turn');
  return new Promise((resolve) => { S.beatDone = resolve; S.beatTimer = setTimeout(() => { if (S.beatDone === resolve) S.beatDone = null; resolve(); }, ev.ms || 1500); });
}
function endBeat() { clearTimeout(S.beatTimer); const d = S.beatDone; S.beatDone = null; if (d) d(); }
async function speak(ev, gen) {
  if (gen !== S.gen) return;
  while (S.pausedForUser && gen === S.gen) await new Promise((r) => setTimeout(r, 80));  // the renter started talking in a pause: hold the next sentence
  if (gen !== S.gen) return;
  S.currentSay = ev; S.lastSaid = ev.text; ui.caption(ev.text);
  let blob = null; try { blob = await ev._audio; } catch (e) { blob = null; }
  if (gen !== S.gen) { S.currentSay = null; return; }
  ui.phase('speaking', 'Speaking'); S.playing = true; rememberSaid(ev.text);
  if (blob) await player.play(blob); else await speakBrowser(ev.text);
  S.playing = false; saidEnded();
  if (gen !== S.gen) return;
  if (ev.idx != null) S.spokenIdx = ev.idx;
  S.currentSay = null;
  if (!S.timeline.length && S.streamOpen && S.lastBusy && !S.pausedForUser) ui.phase(S.lastBusy.phase, S.lastBusy.label);  // nothing queued yet: the server is still parsing / writing, say so rather than "Speaking" + "One moment"
}
function metric() {
  try { navigator.sendBeacon('/api/metric', new Blob([JSON.stringify({ session: S.session, source: 'client', first_event_ms: S.firstEventMs, first_audio_ms: S.firstAudioMs, turn_text: S.lastTurnText.slice(0, 120), interrupted: S.interruptedFlag, ua: navigator.userAgent.slice(0, 180), audio: actx ? actx.state : 'none', mic: S.micOn, headphones: !!(el.headphones && el.headphones.checked) })], { type: 'application/json' })); } catch (e) {}
}

/* ---------------- barge-in: VAD + recogniser ---------------- */
const vad = {
  ctx: null, analyser: null, buf: null, floor: -58, speaking: false, above: 0, below: 0, timer: null, stream: null,
  ratios: [], dt: 0,  // double-talk detector (speakers mode): mic level minus our own playback level, last ~3 s; a jump of 12 dB over the usual echo = someone talking
  async start() {
    if (this.ctx) return;
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    this.ctx = ensureCtx();
    const src = this.ctx.createMediaStreamSource(this.stream); this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = 1024; src.connect(this.analyser);
    this.buf = new Float32Array(this.analyser.fftSize); this.timer = setInterval(() => this.tick(), 30);
  },
  stop() { clearInterval(this.timer); this.timer = null; if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); this.ctx = null; this.stream = null; this.speaking = false; },
  doubleTalk(db) {  // 10-28 (docs/12, 第二档): through speakers, tell our own echo from a renter talking over us, and duck
    const o = outDb();
    if (!DUCK || el.headphones.checked || !S.playing || o < -50) { this.dt = 0; return; }
    const r = db - o;
    this.ratios.push(r); if (this.ratios.length > 100) this.ratios.shift();
    if (this.ratios.length < 15) return;  // learn the echo path for ~0.5 s first
    const usual = [...this.ratios].sort((a, b) => a - b)[Math.floor(this.ratios.length * 0.3)];
    if (r > usual + 12 && db > this.floor + 8) { if (++this.dt === 4 && !S.ducked && !S.pausedForUser) duck(true); }
    else this.dt = 0;
  },
  tick() {
    this.analyser.getFloatTimeDomainData(this.buf); let s = 0; for (let i = 0; i < this.buf.length; i++) s += this.buf[i] * this.buf[i];
    const db = 20 * Math.log10(Math.sqrt(s / this.buf.length) + 1e-7);
    const margin = (S.playing && !el.headphones.checked) ? 14 : 8;
    if (!this.speaking && db < this.floor + 6) this.floor = this.floor * 0.97 + db * 0.03;
    const thr = Math.max(this.floor + margin, -52);
    this.doubleTalk(db);
    if (db > thr) { this.above++; this.below = 0; if (!this.speaking && this.above >= 4) { this.speaking = true; S.speechStartT = performance.now(); onSpeechStart(); } }
    else { this.below++; this.above = 0; if (this.speaking && this.below >= 12) { this.speaking = false; onSpeechEnd(performance.now() - S.speechStartT); } }
    ui.meter(db, thr);
  },
};
function armPauseGuard() {  // an interruption whose final transcript never arrives must not pause the tour forever
  clearTimeout(S.pauseGuard); S.pauseGuard = setTimeout(() => { if (S.pausedForUser) { console.warn('no transcript after the interruption; resuming'); falseAlarm(); } }, 12000);
}
function onSpeechStart() {  // standard 1: pause within ~120 ms of voiced audio
  if (!busy()) { ui.phase('listening', 'Listening'); return; }
  if (!el.headphones.checked && S.playing) return;  // 10-27: through speakers the mic hears our own voice and this paused every sentence ("it never talks"); while we talk, only a real transcript (handleInterim) or the double-talk duck reacts. In a pause (beat) there is no echo, so voice alone holds the next sentence
  clearTimeout(S.resumeTimer); player.pause(); S.pausedForUser = true; armPauseGuard(); ui.interrupt(); ui.phase('listening', 'Go ahead');
}
function onSpeechEnd(durMs) {  // standard 5: short noises resume unless a real transcript arrives
  if (!S.pausedForUser) return;
  const wait = durMs < 600 ? 700 : 1800;
  clearTimeout(S.resumeTimer);
  S.resumeTimer = setTimeout(() => { if (S.pausedForUser && !S.holdForFinal) falseAlarm(); }, wait);
}
function falseAlarm() { clearTimeout(S.pauseGuard); S.pausedForUser = false; S.holdForFinal = false; duck(false); player.resume(); if (busy()) ui.phase('speaking', 'Speaking'); }
const isFiller = (t) => { const w = tokens(t); return w.length > 0 && w.every((x) => FILLERS.has(x)); };
/* standard 3, 10-28 rework: our own voice as the recogniser hears it through speakers. Its finals lag the audio by 1–3 s and often run
   two of our sentences together (since docs/12 every sentence is its own say), so comparing with the current sentence only let our
   own words through as the renter's ("it keeps hearing itself"). Now: every sentence of the last 15 s, matched by word pairs; a final
   that starts with our voice and goes on with the renter's keeps only the renter's part. */
const SAID = [];  // {w: Set(words), bi: Set(word pairs), end: performance.now() when it finished, null while it plays}
const pairsOf = (w) => w.slice(1).map((x, i) => w[i] + ' ' + x);
function rememberSaid(text) { const w = tokens(text); SAID.push({ w: new Set(w), bi: new Set(pairsOf(w)), end: null }); if (SAID.length > 12) SAID.shift(); }
function saidEnded() { const now = performance.now(); SAID.forEach((s) => { if (s.end === null) s.end = now; }); S.quietAt = now; }
const recentSaid = (ms) => { const now = performance.now(); return SAID.filter((s) => s.end === null || now - s.end < ms); };
const STOPW = new Set(['the', 'a', 'an', 'it', 'its', "it's", 'is', 'are', 'be', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with', 'that', 'this', 'there', 'you', 'your', 'i', 'me', 'my', 'we', 'our', 'so', 'do', 'does', 'what', 'how', 'about', 'one', 'just', 'can', 'any']);
function stripEcho(t) {  // → the part of a transcript that is not our own voice ('' = all of it was ours)
  const words = (t || '').trim().split(/\s+/).filter(Boolean), w = words.map((x) => tokens(x).join(''));
  const rec = recentSaid(15000); if (!rec.length || !words.length) return words.join(' ');
  const pair = (a, b) => rec.some((s) => s.bi.has(a + ' ' + b));
  const echo = w.map((x, i) => !x || (i > 0 && pair(w[i - 1], x)) || (i + 1 < w.length && pair(x, w[i + 1])));
  const live = S.playing && !S.pausedForUser, fresh = live || performance.now() - S.quietAt < 2500;
  if (echo.every(Boolean) && (fresh || words.length >= 5)) return '';
  if (el.headphones.checked) return words.join(' ');  // no echo path through headphones: only a word-for-word replay is ours
  const all = words.map((_, i) => i);
  let keep = all.filter((i) => !echo[i]);
  if (!fresh) {  // quiet for a while: drop only a leading run of ours (a final that began during our last sentence); a short phrase of ours said back is the renter's
    let k = 0; while (k < w.length && echo[k]) k++;
    keep = (k >= 3 && k < w.length) ? all.slice(k) : all;
  }
  if (fresh) {
    const kw = keep.map((i) => w[i]).filter(Boolean), just = recentSaid(4000);
    const command = kw.some((x) => COMMAND_WORDS.has(x) && !just.some((s) => s.w.has(x)));
    if (!command) {
      const content = kw.filter((x) => !STOPW.has(x));
      const ours = (x) => just.some((s) => s.w.has(x) || (/^\d+$/.test(x) && [...s.w].some((y) => /^\d+$/.test(y) && y.endsWith(x))));
      if (!content.length || content.filter(ours).length / content.length >= 0.5) return '';  // our own words, misheard
      if (live && kw.length < 3) return '';  // a stray word or two while we talk through speakers: not enough to stop for (tap the orb or say "stop")
    }
  }
  return keep.map((i) => words[i]).join(' ');
}
const COMMAND_WORDS = new Set(['stop', 'pause', 'wait', 'next', 'skip', 'hold', 'hang']);
function handleInterim(t) {
  const mine = stripEcho(t); ui.transcript(mine, true);
  const w = tokens(mine);
  // 10-28: a one-word command stops us at once (no waiting for the browser to decide you finished); stripEcho already dropped one we said ourselves
  const command = w.length === 1 && COMMAND_WORDS.has(w[0]);
  if (busy() && (command || (w.length >= 2 && !isFiller(mine)))) { S.holdForFinal = true; if (!S.pausedForUser) { clearTimeout(S.resumeTimer); player.pause(); duck(false); S.pausedForUser = true; armPauseGuard(); ui.phase('listening', 'Go ahead'); } }
}
function handleFinal(t) {
  if (!t) return;
  const mine = stripEcho(t); ui.transcript(mine, false);
  if (!tokens(mine).length) { if (S.pausedForUser) falseAlarm(); return; }  // all of it was our own voice
  if (busy()) { if (isFiller(mine)) { if (S.pausedForUser) falseAlarm(); S.holdForFinal = false; return; } commitInterrupt(mine); return; }
  sendTurn(mine, 'voice');
}
function talkNow() {  // 10-28: tap the orb (or Space) while it talks = "let me speak": stop the voice now and listen; the mic comes on if it was off
  clearTimeout(S.resumeTimer); endBeat(); player.pause(); duck(false); S.pausedForUser = true; S.holdForFinal = true; armPauseGuard(); ui.interrupt(); ui.phase('listening', 'Go ahead');
  if (!S.micOn) setMic(true);
}
function commitInterrupt(t) {  // standards 2 and 4: tell the server where we were, let the policy decide how to continue
  clearTimeout(S.resumeTimer); clearTimeout(S.pauseGuard); S.holdForFinal = false; S.pausedForUser = false; ui.interrupt();
  sendTurn(t, 'voice', { active: true, spoken_idx: S.spokenIdx, listing_id: S.currentListing, cut_sentence: S.currentSay ? S.currentSay.text : null });
}
function startRecog() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { ui.note('Voice input needs Chrome · type instead'); return false; }
  const r = new SR(); r.continuous = true; r.interimResults = true; r.lang = 'en-AU'; r.maxAlternatives = 1;
  r.onresult = (e) => { S.asrErrors = 0; let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const res = e.results[i]; const t = res[0].transcript.trim(); if (res.isFinal) handleFinal(t); else interim += t + ' '; } if (interim.trim()) handleInterim(interim.trim()); };
  r.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { ui.note('Mic blocked: ' + e.error); setMic(false); ui.error('The microphone is blocked for this page. Allow it in the address bar, or type instead.'); return; }
    if (e.error === 'no-speech' || e.error === 'aborted') return;
    console.warn('asr', e.error); report('asr', e.error);
    S.asrErrors = (S.asrErrors || 0) + 1;
    if (S.asrErrors >= 2) { setMic(false); ui.note('Voice input failed: ' + e.error); ui.error('Voice input is not working in this browser (' + e.error + '). Type instead, or open the page in Chrome.'); }
  };
  r.onend = () => { if (S.recogWanted) { try { r.start(); } catch (e) {} } };
  S.recog = r; S.recogWanted = true; S.asrErrors = 0; try { r.start(); } catch (e) {} return true;
}
function stopRecog() { S.recogWanted = false; if (S.recog) { try { S.recog.stop(); } catch (e) {} S.recog = null; } }
async function setMic(on) {
  if (on) {
    audioSession(true);
    try { await vad.start(); } catch (e) { audioSession(false); ui.note('Mic unavailable: ' + e.message); ui.error('No microphone here (' + e.message + '). Type instead.'); return; }
    const ok = startRecog(); S.micOn = true; micButton(ok ? 'Listening' : 'Mic level only'); if (!busy()) ui.phase('listening', 'Listening');
    detectHeadphones();
    sendWelcome();  // a returning renter hears "Welcome back…" as soon as the mic is on (the click lets the page play sound)
  } else { stopRecog(); vad.stop(); audioSession(false); S.micOn = false; micButton(null); if (!busy()) ui.phase('idle', 'Ready'); }
}
function micButton(label) {  // label = mic on; null = off
  el.mic.classList.toggle('on', !!label); el.mic.setAttribute('aria-pressed', String(!!label)); el.micLabel.textContent = label || 'Talk'; el.meter.hidden = !label;
}

async function detectHeadphones() {  // 10-28: tick Headphones by itself when the output (or the mic) is clearly a headset; the renter's own click wins
  if (S.headphonesTouched || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
  try {
    const devs = await navigator.mediaDevices.enumerateDevices();
    const out = devs.filter((d) => d.kind === 'audiooutput'), def = out.find((d) => d.deviceId === 'default') || out[0];
    const track = vad.stream && vad.stream.getAudioTracks()[0];
    const label = `${(def && def.label) || ''} | ${(track && track.label) || ''}`;
    const hp = /airpods|headphone|headset|earbud|earphone|\bbuds\b|beats|bose|wh-1000|wf-1000|jabra|sennheiser|plantronics|\bpoly\b|bluetooth/i.test(label) && !/built-in|speaker|macbook/i.test((def && def.label) || '');
    if (hp !== el.headphones.checked) { el.headphones.checked = hp; ui.note(hp ? 'Headphones on: interrupt any time' : ''); }
  } catch (e) {}
}
if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) navigator.mediaDevices.addEventListener('devicechange', () => { if (S.micOn) detectHeadphones(); });
el.headphones.addEventListener('change', () => { S.headphonesTouched = true; });

/* ---------------- controls ---------------- */
el.mic.onclick = () => { if (busy() && !S.pausedForUser) { talkNow(); return; } setMic(!S.micOn); };
document.addEventListener('keydown', (e) => {  // Space = tap the orb (not while typing, not on a focused button)
  if (e.code !== 'Space' || e.repeat || !busy() || S.pausedForUser) return;
  const t = e.target; if (t && (t.closest('input, textarea, button, select, [contenteditable="true"]'))) return;
  e.preventDefault(); talkNow();
});
document.addEventListener('click', (e) => {  // quick replies under the box (ui-notion.js): same as saying it
  const b = e.target.closest('[data-say]'); if (!b) return;
  e.preventDefault();
  const t = b.dataset.say;
  if (t === '__pause') { stopAll('Paused'); return; }
  if (busy()) commitInterrupt(t); else sendTurn(t, 'text');
});
$('#composer').onsubmit = (e) => { e.preventDefault(); const t = el.text.value.trim(); if (!t) return; el.text.value = ''; if (busy()) commitInterrupt(t); else sendTurn(t, 'text'); };
function stopAll(label) {
  // 10-28: remember where we stopped; the next thing said or tapped carries it, so "continue" picks up here instead of searching again
  if (S.playing || S.currentSay || S.timeline.length || S.beatDone) S.stoppedAt = { active: true, spoken_idx: S.spokenIdx, listing_id: S.currentListing, cut_sentence: S.currentSay ? S.currentSay.text : null };
  S.gen++; if (S.ac) S.ac.abort(); clearTimeout(S.pauseGuard); endBeat(); duck(false); player.stop(); S.timeline = []; S.streamOpen = false; S.playing = false; S.currentSay = null; S.pausedForUser = false; S.lastBusy = null; ui.phase('paused', label || 'Paused');
}
el.stop.onclick = () => stopAll('Paused');
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') stopAll('Paused'); });
$('#reset').onclick = async () => { stopAll('New session'); try { await fetch('/api/reset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: S.session }) }); } catch (e) {} location.reload(); };
window.HT = { S, ui, sendTurn, stopAll, setMic, player, vad };  // for debugging in the console
})();
