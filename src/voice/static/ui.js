/* HomeTruth voice tour — shared renderer for both pages (8630 browser version, 8631 Pipecat page). Third pass, 2026-10-25.
   Information first. Behind the page runs a slow, faint wall of every candidate listing (GET /api/listings). The conversation
   sits in the middle. When the search is done, each shortlisted card is lifted off that wall to the front (same listing id)
   and introduced in turn: every line says its status in words, the line being discussed is highlighted, and its evidence
   (table, row, request_id) sits in the side panel. No transport and no speech in here: app.js (SSE + Web Audio + Web Speech)
   and pipecat.html (RTVI over WebRTC) call these methods in spoken order. Each page provides #app, its own #dock and
   optionally #topbar-extra; create() mounts the shared page around them. */
window.HTUI = (() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const EASE = 'cubic-bezier(.22,1,.36,1)';
  const RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  const cssEsc = (s) => (window.CSS && CSS.escape ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, '\\$&'));
  const fmtDate = (iso) => { if (!iso) return ''; const d = new Date(iso + 'T00:00:00'); return isNaN(d) ? String(iso) : d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' }); };
  const fmtMs = (ms) => (ms == null ? '' : ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms');
  const sentence = (s) => { s = String(s || ''); return s ? s[0].toUpperCase() + s.slice(1) : s; };
  const STATUS = { supported: 'Supported', inferred: 'Inferred', conflict: 'Conflict', unknown: 'Unknown' };
  const STATUS_WORDS = new Set(['yes', 'likely', 'clash', '?']);  // card_payload's short values that only repeat the status
  const SOURCE_NAMES = { agent_reply: 'Agent reply' };
  const EXAMPLE = 'Two bedrooms near Central, under 900 a week, I have a cat, moving mid November';
  const icon = (name, cls = 'ico') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const chip = (st) => `<span class="chip ${esc(st)}"><svg class="sico" aria-hidden="true"><use href="#s-${esc(st)}"/></svg>${esc(STATUS[st] || st)}</span>`;
  const splitTitle = (L) => { const t = String(L.title || L.id || ''); const i = t.lastIndexOf(', '); return i > 0 ? [t.slice(0, i), L.suburb || t.slice(i + 2)] : [t, L.suburb || '']; };
  const bedText = (n) => (n === 0 ? 'Studio' : `${n} bed`);
  // the five must-haves (policy.REQUIRED): icon, the value in words, the chip while we ask for it, the chip when assumed (phraser.ASSUME)
  const NEEDS = [
    ['A1', 'coin', (p) => (p.budget != null ? `Under $${p.budget}/wk` : null), 'Weekly budget?', 'Any budget (assumed)'],
    ['B1', 'bed', (p) => (p.bedrooms != null ? (p.bedrooms === 0 ? 'Studio' : `${p.bedrooms} bedroom${p.bedrooms === 1 ? '' : 's'}`) : null), 'How many bedrooms?', 'Any size (assumed)'],
    ['G1', 'pin', (p) => (p.anchor ? `Near ${p.anchor}` : null), 'Close to where?', 'Commute to Central Station (assumed)'],
    ['A4', 'cal', (p) => (p.move_in ? `Move in ${p.move_in}` : null), 'Move-in date?', 'Any move-in date (assumed)'],
    ['J1', 'paw', (p) => (p.pets ? (/^no\b/i.test(p.pets) ? sentence(p.pets) : `With ${p.pets}`) : null), 'Any pets?', 'No pets (assumed)'],
  ];

  const SPRITE = `<svg class="sprite" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<symbol id="i-logo" viewBox="0 0 24 24"><path d="M3.5 11.2 12 4l8.5 7.2"/><path d="M5.8 9.6V20h12.4V9.6"/><path d="m9.2 14.6 2 2 3.8-4.2"/></symbol>
<symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></symbol>
<symbol id="i-send" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
<symbol id="i-stop" viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M8.5 5.8v12.4l10-6.2z" fill="currentColor" stroke="none"/></symbol>
<symbol id="i-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v9M14.6 9.6c-.3-.9-1.3-1.5-2.6-1.5-1.5 0-2.6.8-2.6 1.8 0 2.4 5.2 1.1 5.2 3.6 0 1-1.1 1.9-2.6 1.9-1.4 0-2.4-.7-2.7-1.6"/></symbol>
<symbol id="i-bed" viewBox="0 0 24 24"><path d="M3 18v-8M3 14h18v4M21 14v-3a2 2 0 0 0-2-2h-7v5"/><circle cx="7" cy="9.5" r="1.8"/></symbol>
<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z"/><circle cx="12" cy="10" r="2.2"/></symbol>
<symbol id="i-cal" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></symbol>
<symbol id="i-paw" viewBox="0 0 24 24"><circle cx="7" cy="9" r="1.7"/><circle cx="11" cy="6.2" r="1.7"/><circle cx="15.8" cy="6.8" r="1.7"/><circle cx="19" cy="10.8" r="1.7"/><path d="M8.2 17.2c0-2.6 2.1-4.7 4.6-4.7s4.6 2.1 4.6 4.7c0 1.5-1.1 2.4-2.4 2.4-1 0-1.5-.5-2.2-.5s-1.2.5-2.2.5c-1.3 0-2.4-.9-2.4-2.4z"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5.5v13M5.5 12h13"/></symbol>
<symbol id="i-ask" viewBox="0 0 24 24"><path d="M4 5.5h16v10.5H10l-6 4z"/><path d="M10.1 9.2a1.9 1.9 0 1 1 2.7 1.7c-.5.25-.8.6-.8 1.1v.2"/><path d="M12 14.1v.01"/></symbol>
<symbol id="s-supported" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m4.9 8.2 2.1 2.1 4.2-4.5" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="s-inferred" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1.8a6.2 6.2 0 0 0 0 12.4z" fill="currentColor"/></symbol>
<symbol id="s-conflict" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="s-unknown" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.3 1.9"/><path d="M6.5 6.4a1.6 1.6 0 1 1 2.3 1.5c-.5.25-.8.6-.8 1.1v.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".85" fill="currentColor"/></symbol>
</svg>`;

  const EV_EMPTY = 'The line being discussed shows its evidence here.';
  const SKELETON = `
<div class="wall" aria-hidden="true"><div class="lanes" id="lanes"></div></div>
<header class="topbar">
  <div class="brand">${icon('logo', 'logo')}<b>HomeTruth</b><span>Rental listing checker</span></div>
  <div class="legend" role="note" aria-label="What the labels mean">
    <span class="lg-title">Every line is</span>
    <span title="A listing, document or public table backs it">${chip('supported')}</span>
    <span title="Likely, but nothing confirms it yet">${chip('inferred')}</span>
    <span title="The evidence goes against what you need">${chip('conflict')}</span>
    <span title="Nothing we have covers it yet">${chip('unknown')}</span>
    <span class="confirm" title="A must-have that is still unknown: ask the agent before you apply">To confirm</span>
  </div>
  <div class="topbar-extra" id="topbar-extra-slot"></div>
</header>
<main class="stage" id="stage">
  <section class="hero">
    <h1>Tell me what you need.<br>I'll check every listing.</h1>
    <p class="lede">Rent, rooms, commute, move-in date, pets: I check each one against the listing, floor plan, the agent’s replies and public data, and show you what backs it up.</p>
    <div class="slot" id="slot-home"></div>
    <p class="try">Try <button type="button" class="try-btn" id="try">“${EXAMPLE}”</button></p>
  </section>
  <section class="talk" aria-live="polite">
    <div class="talk-status"><span class="spin" aria-hidden="true"></span><span id="talk-title">Analysing your request</span></div>
    <div class="slot" id="needs-talk"></div>
    <div class="slot" id="sources-talk"></div>
  </section>
  <section class="board" id="board">
    <div class="board-main">
      <div class="board-head"><div class="slot" id="needs-board"></div></div>
      <div class="shortlist" id="shortlist"></div>
    </div>
    <aside class="side">
      <section class="panel" id="ev-panel">
        <div class="panel-head"><h2>Evidence</h2><span id="ev-status"></span></div>
        <div class="ev-where" id="ev-where">${EV_EMPTY}</div>
        <ul class="ev-list" id="evidence"></ul>
      </section>
      <div class="slot" id="sources-side"></div>
      <section class="panel" id="changes-panel" hidden>
        <div class="panel-head"><h2>Changes</h2><span class="count" id="changes-count"></span></div>
        <ul id="changes"></ul>
      </section>
    </aside>
  </section>
</main>
<div class="bottom" id="slot-bottom"></div>
<div hidden>
  <div class="needs" id="needs"></div>
  <section class="panel sources" id="sources-box"><div class="panel-head"><h2>Sources</h2><span class="count" id="sources-count"></span></div><ul id="sources"></ul></section>
</div>`;

  /* ---------------- the wall: every candidate listing, looping slowly in lanes ---------------- */
  function makeWall(lanesEl) {
    const CW = 216, CH = 124, GAP = 16, SPEED = 26;  // card size, gap, px per second at rate 1 (5 mock listings → ~48 s a loop)
    let listings = [], anims = [], rate = 1, target = 1, raf = 0, resizeT = 0;
    const picked = new Map();  // listing id → lane it was lifted from (that lane shows an empty slot)
    const cardHTML = (L) => {
      const [addr, sub] = splitTitle(L);
      return `<div class="wcard" data-id="${esc(L.id)}"><span class="w-sub">${esc(sub)}</span><span class="w-addr">${esc(addr)}</span>`
        + `<span class="w-rent"><b>$${esc(L.rent)}</b> per week</span><span class="w-meta">${esc(bedText(L.bedrooms))} · ${esc(L.bathrooms)} bath · from ${esc(fmtDate(L.available_from))}</span></div>`;
    };
    function build() {
      anims.forEach((a) => a.cancel()); anims = []; lanesEl.textContent = '';
      const n = listings.length; if (!n) return;
      const vw = window.innerWidth, vh = window.innerHeight;
      const lanes = Math.max(3, Math.ceil((vh + CH * 0.4) / (CH + GAP)));
      for (let k = 0; k < lanes; k++) {
        // plenty of listings: each lane gets its own; only a few (the mock has 5): every lane loops all of them, rotated
        let set;
        if (n >= lanes * 4) set = listings.filter((_, i) => i % lanes === k);
        else { const off = (k * 2) % n; set = listings.slice(off).concat(listings.slice(0, off)); }
        const setW = set.length * (CW + GAP);
        const lane = document.createElement('div'); lane.className = 'lane'; lane.dataset.lane = k;
        const track = document.createElement('div'); track.className = 'track';
        track.innerHTML = Array.from({ length: Math.ceil(vw / setW) + 1 }, () => set.map(cardHTML).join('')).join('');
        lane.appendChild(track); lanesEl.appendChild(lane);
        picked.forEach((lk, id) => { if (lk === k) lane.querySelectorAll(`.wcard[data-id="${cssEsc(id)}"]`).forEach((c) => c.classList.add('picked')); });
        if (RM.matches) { track.style.transform = `translateX(${-((k * 97) % setW)}px)`; continue; }
        const dur = Math.round(Math.max(30, Math.min(60, (setW / SPEED) * (1 + (k % 3) * 0.08))) * 1000);
        const kf = [{ transform: 'translateX(0px)' }, { transform: `translateX(${-setW}px)` }];
        const a = track.animate(k % 2 ? kf.reverse() : kf, { duration: dur, iterations: Infinity, easing: 'linear' });
        a.currentTime = Math.round(dur * ((k * 0.383) % 1));
        a.playbackRate = rate;
        anims.push(a);
      }
    }
    window.addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(build, 250); });
    return {
      load(list) { listings = (list || []).filter((L) => L && L.id); build(); },
      // the on-screen copy of this listing nearest to `near`; its lane copies turn into empty slots. null if it isn't on the wall.
      pick(id, near) {
        const vw = window.innerWidth, vh = window.innerHeight; let best = null, bestScore = Infinity;
        lanesEl.querySelectorAll(`.wcard[data-id="${cssEsc(id)}"]:not(.picked)`).forEach((c) => {
          const r = c.getBoundingClientRect();
          if (r.right < 30 || r.left > vw - 30 || r.bottom < 80 || r.top > vh - 30) return;
          const cut = r.left < 0 || r.right > vw || r.top < 60 || r.bottom > vh ? 500 : 0;
          const score = (near ? Math.hypot(r.left + r.width / 2 - near.x, r.top + r.height / 2 - near.y) : 0) + cut;
          if (score < bestScore) { bestScore = score; best = { c, r }; }
        });
        if (!best) return null;
        const lane = best.c.closest('.lane'); picked.set(id, Number(lane.dataset.lane));
        lane.querySelectorAll(`.wcard[data-id="${cssEsc(id)}"]`).forEach((c) => c.classList.add('picked'));
        return best.r;
      },
      unpick(id) { picked.delete(id); lanesEl.querySelectorAll(`.wcard.picked[data-id="${cssEsc(id)}"]`).forEach((c) => c.classList.remove('picked')); },
      // ease the loop speed to r (1 = normal) instead of jumping
      setRate(r) {
        if (RM.matches || r === target) return;
        target = r; const from = rate, t0 = performance.now(), D = 800;
        cancelAnimationFrame(raf);
        const step = (t) => {
          const p = Math.min(1, (t - t0) / D);
          rate = from + (r - from) * (1 - Math.pow(1 - p, 3));
          anims.forEach((a) => { a.playbackRate = rate; });
          if (p < 1) raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
      },
    };
  }

  function create() {
    document.body.insertAdjacentHTML('afterbegin', SPRITE);
    const app = $('#app'); app.innerHTML = SKELETON;
    const dock = $('#dock'); const extra = $('#topbar-extra');
    if (extra) $('#topbar-extra-slot').appendChild(extra);
    $('#slot-home').appendChild(dock);
    const el = {
      app, dock, board: $('#board'), shortlist: $('#shortlist'), talkTitle: $('#talk-title'), needs: $('#needs'),
      sourcesBox: $('#sources-box'), sources: $('#sources'), sourcesCount: $('#sources-count'),
      evStatus: $('#ev-status'), evWhere: $('#ev-where'), evidence: $('#evidence'),
      changesPanel: $('#changes-panel'), changes: $('#changes'), changesCount: $('#changes-count'),
      voice: $('#voice'), phase: $('#phase'), caption: $('#caption'), transcript: $('#transcript'), text: $('#text'),
      note: $('#note'), metrics: $('#metrics'), meterBar: $('#meter i'), meterThr: $('#meter b'),
    };
    const wall = makeWall($('#lanes'));
    fetch('/api/listings', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => wall.load((d && d.listings) || [])).catch(() => {});

    let stage = null, phaseNow = 'idle', phaseLabel = 'Ready', asking = false, litKey = null, searchOpen = false;
    const cards = new Map();   // listing id → { el, L, rank, ask: Set(dim), was: Map(dim → old status), moved }
    const evCache = new Map(); // "id|dim" → last evidence event, so a row can be clicked later
    const metaParts = new Map();

    /* ---------------- stages: home (hero + composer) → talk (analysing / asking) → results (shortlist) ---------------- */
    function moveFlip(node, target) {
      const a = node.getBoundingClientRect(); target.appendChild(node);
      if (RM.matches) return;
      const b = node.getBoundingClientRect(); const dx = a.left - b.left, dy = a.top - b.top;
      if (Math.abs(dx) + Math.abs(dy) > 2) node.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], { duration: 620, easing: EASE });
    }
    function talkTitle() {  // what the assistant is doing; speaking / listening show in the dock, so the title keeps its last value then
      if (phaseNow === 'searching') return 'Checking sources';
      if (phaseNow === 'thinking') return sentence(phaseLabel);
      if (asking) return 'Before I search';
      return el.talkTitle.textContent || 'Analysing your request';
    }
    function setStage(s) {
      if (stage === s) return;
      stage = s; app.dataset.stage = s;
      const dockTo = s === 'home' ? $('#slot-home') : $('#slot-bottom');
      if (dock.parentElement !== dockTo) moveFlip(dock, dockTo);
      (s === 'results' ? $('#needs-board') : $('#needs-talk')).appendChild(el.needs);
      (s === 'results' ? $('#sources-side') : $('#sources-talk')).appendChild(el.sourcesBox);
      if (s === 'results') { el.board.classList.remove('enter'); void el.board.offsetWidth; el.board.classList.add('enter'); }
      if (s === 'talk') el.talkTitle.textContent = talkTitle();
      wallMode();
    }
    function wallMode() {
      const busy = phaseNow === 'thinking' || phaseNow === 'searching';
      const m = stage === 'results' ? 'back' : stage === 'home' ? 'home' : busy ? 'busy' : 'wait';
      app.dataset.wall = m;
      wall.setRate({ home: 1, wait: 0.6, busy: 0.25, back: 0.15 }[m]);
    }

    /* ---------------- cards out front ---------------- */
    function rowsHTML(rec) {
      const L = rec.L;
      return (L.cells || []).map((c, i) => {
        const val = c.short != null && !STATUS_WORDS.has(String(c.short)) ? c.short : '';
        const was = rec.was.get(c.dim);
        // under the line's name: "To confirm" (a must-have nobody has confirmed), "was …" after an update, the best question to ask
        const sub = (c.status === 'unknown' && c.hard ? '<span class="confirm">To confirm</span>' : '')
          + (was ? `<span class="was">was ${esc(STATUS[was] || was)}</span>` : '')
          + (rec.ask.has(c.dim) ? `<span class="asknote">${icon('ask')}Best question for the agent</span>` : '');
        return `<li class="row ${esc(c.status)}${c.hard ? ' hard' : ''}${evCache.has(L.id + '|' + c.dim) ? ' has-ev' : ''}" data-dim="${esc(c.dim)}" style="--i:${i}">`
          + `<span class="dim">${esc(c.label)}${sub}</span><span class="val">${esc(val)}</span><span class="tags">${chip(c.status)}</span></li>`;
      }).join('');
    }
    function summaryHTML(L) {
      const n = { supported: 0, inferred: 0, conflict: 0, unknown: 0 }; let confirm = 0;
      (L.cells || []).forEach((c) => { if (n[c.status] != null) n[c.status]++; if (c.status === 'unknown' && c.hard) confirm++; });
      const parts = [];
      if (n.supported) parts.push(`<b class="t-supported">${n.supported}</b> supported`);
      if (n.inferred) parts.push(`<b class="t-inferred">${n.inferred}</b> inferred`);
      if (n.conflict) parts.push(`<b class="t-conflict">${n.conflict}</b> conflict${n.conflict > 1 ? 's' : ''}`);
      if (confirm) parts.push(`<b class="t-unknown">${confirm}</b> to confirm`);
      if (n.unknown - confirm) parts.push(`<b class="t-unknown">${n.unknown - confirm}</b> unknown`);
      return parts.join('<span class="sep">·</span>');
    }
    function cardInner(rec) {
      const L = rec.L; const [addr, sub] = splitTitle(L);
      const mv = rec.moved && rec.moved.until > Date.now() ? rec.moved : null;
      return `<header class="fg-head"><div class="fg-top"><span class="now">Now discussing</span><span class="rank">#${esc(rec.rank)}</span></div>`
        + `<div class="suburb">${esc(sub)}</div><h3 class="addr">${esc(addr)}</h3>`
        + `<div class="rent"><b>$${esc(L.rent)}</b><span>per week</span></div>`
        + `<div class="meta">${esc(bedText(L.bedrooms))} · ${esc(L.bathrooms)} bath · Available ${esc(fmtDate(L.available_from))}</div>`
        + `<div class="moved${mv ? ' ' + mv.dir : ''}">${mv ? esc(mv.text) : ''}</div></header>`
        + `<ul class="rows">${rowsHTML(rec)}</ul><footer class="fg-foot">${summaryHTML(L)}</footer>`;
    }
    function renderCard(rec, flashDims) {
      rec.el.innerHTML = cardInner(rec);
      if (litKey && litKey.split('|')[0] === rec.L.id) { const row = rec.el.querySelector(`.row[data-dim="${cssEsc(litKey.split('|')[1])}"]`); if (row) row.classList.add('lit'); }
      (flashDims || []).forEach((dim) => { const row = rec.el.querySelector(`.row[data-dim="${cssEsc(dim)}"]`); if (row) row.classList.add('changed'); });
    }
    const byRank = () => [...cards.values()].sort((a, b) => a.rank - b.rank);
    const placeByRank = () => byRank().forEach((r) => el.shortlist.appendChild(r.el));
    // FLIP: remember where each card sits, change the DOM, then slide every card from its old spot to its new one
    function flipCards(mutate, skip) {
      const before = new Map();
      cards.forEach((r) => { if (r.el !== skip && r.el.isConnected) before.set(r.el, r.el.getBoundingClientRect()); });
      mutate();
      if (RM.matches) return;
      before.forEach((b, node) => {
        const a = node.getBoundingClientRect(); const dx = b.left - a.left, dy = b.top - a.top;
        if (Math.abs(dx) + Math.abs(dy) > 1) node.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], { duration: 600, easing: EASE });
      });
    }
    function reveal(d) { d.classList.add('reveal'); setTimeout(() => d.classList.remove('reveal'), 1200); }
    // lift the listing's card off the wall: start at the wall copy's size and place, grow into the slot, then unfold the lines
    function flyIn(rec) {
      const d = rec.el; const to = d.getBoundingClientRect();
      const from = RM.matches || !to.width ? null : wall.pick(rec.L.id, { x: to.left + to.width / 2, y: to.top + 70 });
      if (!from) { d.classList.add('rise'); reveal(d); return; }
      const s = Math.min(1, from.width / to.width);
      const clipBottom = Math.max(0, to.height - from.height / s);
      d.classList.add('flying');
      const a = d.animate([
        { transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${s})`, clipPath: `inset(0px 0px ${clipBottom}px 0px round ${(12 / s).toFixed(1)}px)`, opacity: 0.55, offset: 0 },
        { opacity: 1, offset: 0.4 },
        { transform: 'translate(0px, 0px) scale(1)', clipPath: 'inset(0px 0px 0px 0px round 14px)', opacity: 1, offset: 1 },
      ], { duration: 760, easing: EASE });
      let open = false;  // the lines start unfolding while the card is still settling, not after it stops
      const unfold = () => { if (open) return; open = true; d.classList.remove('flying'); reveal(d); };
      setTimeout(unfold, 380);
      a.onfinish = unfold; a.oncancel = unfold;
    }
    function setActive(rec) {
      cards.forEach((r) => r.el.classList.toggle('active', r === rec));
      app.classList.add('touring');
      if (el.shortlist.scrollHeight > el.shortlist.clientHeight + 4) rec.el.scrollIntoView({ block: 'nearest', behavior: RM.matches ? 'auto' : 'smooth' });
    }
    function endTour() {
      cards.forEach((r) => r.el.classList.remove('active'));
      el.shortlist.querySelectorAll('.row.lit').forEach((r) => r.classList.remove('lit'));
      litKey = null; app.classList.remove('touring');
    }
    function sendAllBack() {  // a new search: the old shortlist goes back into the wall
      cards.forEach((rec, id) => { wall.unpick(id); const node = rec.el; node.classList.add('leaving'); setTimeout(() => node.remove(), 450); });
      cards.clear(); litKey = null; app.classList.remove('touring');
    }
    function resetEvidence() { el.evidence.innerHTML = ''; el.evStatus.innerHTML = ''; el.evWhere.textContent = EV_EMPTY; }
    function newSearch() {
      searchOpen = true;
      el.sources.innerHTML = ''; el.sourcesCount.textContent = ''; evCache.clear(); resetEvidence();
      if (cards.size) sendAllBack();
      setStage('talk');
    }
    function showEvidence(ev) {
      const rec = cards.get(ev.listing_id); const addr = rec ? splitTitle(rec.L)[0] : ev.listing_id;
      el.evWhere.innerHTML = `<b>${esc(addr)}</b><span class="sep">›</span><span>${esc(ev.label)}</span>`;
      el.evStatus.innerHTML = chip(ev.status);
      const items = ev.items || [];
      el.evidence.innerHTML = items.length ? items.map((it, i) => `<li style="--i:${i}">`
        + `<div class="ev-src"><span>Table <b>${esc(it.table)}</b></span><span>Row <b>${esc(it.row)}</b></span>${it.material_id && it.material_id !== it.row ? `<span>Material <b>${esc(it.material_id)}</b></span>` : ''}</div>`
        + `<blockquote>${esc(it.text)}</blockquote>`
        + `<div class="ev-id">request_id <code>${esc(it.request_id)}</code>${it.mock ? '<span class="mock">mock</span>' : ''}</div></li>`).join('')
        : '<li class="ev-none">No rows for this line yet.</li>';
    }
    el.shortlist.addEventListener('click', (e) => {  // click a line that has been discussed to see its evidence again
      const row = e.target.closest('.row.has-ev'); if (!row) return;
      const ev = evCache.get(row.closest('.fgcard').dataset.id + '|' + row.dataset.dim); if (!ev) return;
      showEvidence(ev);
      el.shortlist.querySelectorAll('.row.viewing').forEach((r) => r.classList.remove('viewing'));
      row.classList.add('viewing');
    });
    function showMoved(rec, from, to) {
      rec.moved = { text: to < from ? `Moved up to #${to}` : `Moved down to #${to}`, dir: to < from ? 'up' : 'down', until: Date.now() + 6000 };
      const m = rec.el.querySelector('.moved'); if (m) { m.textContent = rec.moved.text; m.className = 'moved ' + rec.moved.dir; }
      clearTimeout(rec.movedT); rec.movedT = setTimeout(() => { const n = rec.el.querySelector('.moved'); if (n) { n.textContent = ''; n.className = 'moved'; } }, 6000);
    }
    function meta(key, value) {  // each part stays on one line; a long footer wraps between parts, never inside one
      metaParts.set(key, value || '');
      if (el.metrics) el.metrics.innerHTML = [...metaParts.values()].filter(Boolean).map((v) => `<span>${esc(v)}</span>`).join(' · ');
    }
    function sourcesCount() {  // the server sends sources one by one with no total, so while the search runs only the done count is known
      const n = el.sources.children.length, done = el.sources.querySelectorAll('li.done').length;
      el.sourcesCount.textContent = !n ? '' : searchOpen ? `${done} checked so far` : `${done} of ${n} checked`;
    }

    const ui = {
      el, meta, example: EXAMPLE,
      stage: () => stage,
      // a server `state` event: what it means happens now (a new search clears the old shortlist, "Ready" ends the tour);
      // showing it can wait (8631 holds the label until the current sentence has been spoken: pass show = false, then phase() later)
      state(ev, show = true) {
        if (ev.phase === 'searching') newSearch();
        else if (searchOpen) { searchOpen = false; sourcesCount(); }
        if (ev.phase === 'idle' && !/paus/i.test(ev.label || '')) endTour();
        if (show) ui.phase(ev.phase, ev.label);
      },
      phase(p, label) {  // what is shown: the indicator and label in the dock, the title of the analysing view, the wall's pace
        phaseNow = p; phaseLabel = label || p; const txt = sentence(phaseLabel);
        app.dataset.phase = p; if (el.voice) el.voice.dataset.phase = p;
        if (el.phase.textContent !== txt) el.phase.textContent = txt;
        if (p === 'thinking' || p === 'searching') asking = false;
        if (stage === 'talk') el.talkTitle.textContent = talkTitle();
        if (p === 'idle' || p === 'paused') app.classList.remove('touring');
        if (p === 'paused' && searchOpen) { searchOpen = false; sourcesCount(); }
        wallMode();
      },
      level(x) { if (el.voice) el.voice.style.setProperty('--level', Math.max(0, Math.min(1, x || 0)).toFixed(3)); },
      botLevel(x) { if (el.voice) el.voice.style.setProperty('--bot', Math.max(0, Math.min(1, x || 0)).toFixed(3)); },
      interrupt() {
        el.caption.classList.add('dim');
        if (el.voice) { el.voice.classList.remove('cut'); void el.voice.offsetWidth; el.voice.classList.add('cut'); }
      },
      caption(t) {
        el.caption.classList.remove('dim'); el.caption.textContent = t || '';
        if (t && !RM.matches) el.caption.animate([{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: EASE });
      },
      transcript(t, interim) {
        el.transcript.innerHTML = t ? `<span class="you-l">You</span>${esc(t)}` : '';
        el.transcript.classList.toggle('interim', !!interim);
      },
      userSaid(t) { ui.transcript(t, false); if (stage === 'home') setStage('talk'); },
      error(m) { el.caption.innerHTML = `<span class="error">${esc(m)}</span>`; ui.phase('idle', 'Error'); },
      latency(firstEventMs, firstWordMs) {
        meta('latency', firstEventMs == null && firstWordMs == null ? '' : `First event ${firstEventMs == null ? '–' : firstEventMs + ' ms'} · first word ${firstWordMs == null ? '–' : firstWordMs + ' ms'}`);
      },
      events(n) { if (el.metrics) el.metrics.title = `${n} events this session`; },
      note(t) { if (el.note) el.note.textContent = t || ''; },
      needs(ev) {
        const p = ev.profile || {}; const ask = new Set(ev.asking || []); const assumed = new Set(ev.assumed || []);
        asking = ask.size > 0;
        const chips = [];
        NEEDS.forEach(([dim, ic, get, askText, assumedText]) => {
          const v = get(p);
          if (v != null) chips.push(['set', ic, v]);
          else if (ask.has(dim)) chips.push(['asking', ic, askText]);
          else if (assumed.has(dim)) chips.push(['assumed', ic, assumedText]);
        });
        (p.extras || []).forEach((x) => chips.push(['extra', 'plus', x]));
        el.needs.innerHTML = '<span class="lbl">Your needs</span><span class="chips">' + chips.map(([cls, ic, t], i) => `<span class="need ${cls}" style="--i:${i}">${icon(ic)}<span>${esc(t)}</span></span>`).join('') + '</span>';
        if (ev.parser) meta('parser', ev.parser === 'llm' ? `Needs read by Nemotron${ev.parse && ev.parse.provider ? ' via ' + sentence(ev.parse.provider) : ''}` : 'Needs read by rules');
        if (stage === 'home') setStage('talk');
        if (stage === 'talk') el.talkTitle.textContent = talkTitle();
      },
      source(ev) {
        let li = el.sources.querySelector(`li[data-name="${cssEsc(ev.name)}"]`);
        if (!li) {
          li = document.createElement('li'); li.dataset.name = ev.name; el.sources.appendChild(li);
          li.innerHTML = '<span class="s-ico"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.4 8.3 2.4 2.4 4.8-5.1"/></svg></span><span class="s-name"></span><span class="s-n"></span>';
        }
        li.className = ev.status === 'done' ? 'done' : 'running';
        li.title = `${ev.table || ''} · ${ev.request_id || ''}${ev.mock ? ' · mock' : ''}`;
        li.querySelector('.s-name').textContent = (ev.label || ev.name).replace(/-/g, '‑');  // non-breaking hyphen: "by-laws" wraps as a whole word
        li.querySelector('.s-n').textContent = ev.status === 'done' ? `${Number(ev.rows || 0).toLocaleString('en-AU')} rows · ${fmtMs(ev.ms)}` : 'checking…';
        if (ev.mock) el.sourcesBox.classList.add('is-mock');
        sourcesCount();
      },
      card(L) {
        if (!L || !L.id) return;
        const rank = Number(L.rank) || 99;
        let rec = cards.get(L.id);
        if (!rec || !rec.el.classList.contains('active')) {  // a different place is being introduced: the last line and its evidence were about another one
          el.shortlist.querySelectorAll('.row.lit, .row.viewing').forEach((r) => r.classList.remove('lit', 'viewing'));
          litKey = null; resetEvidence();
        }
        if (rec) {  // already out front (tour resumed, skipped back, repeated): refresh in place, slide if its rank changed
          const moved = rec.rank !== rank;
          rec.L = L; rec.rank = rank; renderCard(rec);
          if (moved) flipCards(placeByRank);
        } else {
          setStage('results');
          const d = document.createElement('article'); d.className = 'fgcard'; d.dataset.id = L.id;
          rec = { el: d, L, rank, ask: new Set(), was: new Map(), moved: null }; cards.set(L.id, rec);
          renderCard(rec);
          flipCards(placeByRank, d);
          flyIn(rec);
        }
        setActive(rec);
      },
      cardUpdate(ev) {  // agent reply or new material: same card, new statuses; changed lines flash and keep a "was …" note
        const L = ev.listing; const rec = L && cards.get(L.id); if (!rec) return;
        const old = new Map((rec.L.cells || []).map((c) => [c.dim, c.status]));
        const flash = (L.cells || []).filter((c) => (old.has(c.dim) && old.get(c.dim) !== c.status) || (rec.flash && rec.flash.has(c.dim))).map((c) => c.dim);
        flash.forEach((dim) => { if (!rec.was.has(dim) && old.has(dim)) rec.was.set(dim, old.get(dim)); });
        rec.flash = null;
        const rank = Number(L.rank) || rec.rank; const from = rec.rank;
        rec.L = L; rec.rank = rank; renderCard(rec, flash);
        if (rank !== from) { flipCards(placeByRank); showMoved(rec, from, rank); }
      },
      highlight(ev) {
        const rec = cards.get(ev.listing_id); if (!rec) return;
        setActive(rec);
        el.shortlist.querySelectorAll('.row.lit, .row.viewing').forEach((r) => r.classList.remove('lit', 'viewing'));
        litKey = ev.listing_id + '|' + ev.dim;
        if (ev.question && !rec.ask.has(ev.dim)) { rec.ask.add(ev.dim); renderCard(rec); }
        const row = rec.el.querySelector(`.row[data-dim="${cssEsc(ev.dim)}"]`); if (!row) return;
        row.classList.add('lit');
        const box = el.shortlist.getBoundingClientRect(), r = row.getBoundingClientRect();
        if (r.bottom > box.bottom || r.top < box.top) row.scrollIntoView({ block: 'nearest', behavior: RM.matches ? 'auto' : 'smooth' });
      },
      evidence(ev) {
        evCache.set(ev.listing_id + '|' + ev.dim, ev);
        const rec = cards.get(ev.listing_id);
        const row = rec && rec.el.querySelector(`.row[data-dim="${cssEsc(ev.dim)}"]`); if (row) row.classList.add('has-ev');
        showEvidence(ev);
      },
      change(ev) {  // arrives just before the card_update it explains: log it, and let that update show "was <from>" on the line
        const rec = cards.get(ev.listing_id); const addrOf = (id) => { const r = cards.get(id); return r ? splitTitle(r.L)[0] : id; };
        if (rec && ev.dim) { if (ev.from && !rec.was.has(ev.dim)) rec.was.set(ev.dim, ev.from); (rec.flash = rec.flash || new Set()).add(ev.dim); }
        const before = ev.rank_before || [], after = ev.rank_after || [];
        const reranked = after.length > 0 && before.join() !== after.join();
        const li = document.createElement('li');
        li.innerHTML = `<div class="ch-top"><b>${esc(rec ? splitTitle(rec.L)[0] : ev.listing_id)}</b><span>${esc(SOURCE_NAMES[ev.source] || sentence(String(ev.source || '').replace(/_/g, ' ')))}${ev.ts ? ' · ' + esc(String(ev.ts).slice(11, 16)) : ''}</span></div>`
          + `<div class="ch-line"><span class="ch-dim">${esc(ev.label)}</span>${chip(ev.from)}<span class="arrow" aria-label="to">→</span>${chip(ev.to)}</div>`
          + (reranked ? `<div class="ch-rank">New order: ${after.map((id, i) => `#${i + 1} ${esc(addrOf(id))}`).join(', ')}</div>` : '');
        el.changes.prepend(li); el.changesPanel.hidden = false; el.changesCount.textContent = String(el.changes.children.length);
        if (reranked) {
          const moves = [];
          after.forEach((id, i) => { const r = cards.get(id); if (r && r.rank !== i + 1) { moves.push([r, r.rank, i + 1]); r.rank = i + 1; } });
          flipCards(placeByRank);
          moves.forEach(([r, from, to]) => { const b = r.el.querySelector('.rank'); if (b) b.textContent = '#' + to; showMoved(r, from, to); });
        }
      },
      meter(db, thr) {
        if (!el.meterBar) return;
        const pct = (v) => Math.max(0, Math.min(100, ((v + 75) / 60) * 100));
        el.meterBar.style.width = pct(db) + '%'; el.meterThr.style.left = pct(thr) + '%';
        ui.level((db - thr + 10) / 30);
      },
      clear() {
        sendAllBack(); evCache.clear(); resetEvidence(); asking = false; searchOpen = false;
        el.needs.innerHTML = ''; el.sources.innerHTML = ''; el.sourcesCount.textContent = ''; el.sourcesBox.classList.remove('is-mock');
        el.changes.innerHTML = ''; el.changesPanel.hidden = true; el.changesCount.textContent = '';
        ui.caption(''); ui.transcript('', false);
        setStage('home');
      },
    };
    const tryBtn = $('#try');
    if (tryBtn) tryBtn.onclick = () => { el.text.value = EXAMPLE; el.text.focus(); };
    setStage('home');
    return ui;
  }
  return { create, esc, fmtDate };
})();
