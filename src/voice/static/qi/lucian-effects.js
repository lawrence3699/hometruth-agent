// lucian-effects.js · HomeTruth on the qi shell (2026-10-27). Motion ported from Lucian UX/UI Prompt (MIT, (c) 2026 Seokwoooo,
// https://lucianlabs.dev/uxui-prompt/); the originals are in vendor/lucian/NNN-*.txt, the licence in vendor/lucian/LICENSE.md.
// Loaded last by index.html and pipecat.html. It changes nothing the page says or does: it watches what ui-qi.js, conversation-panel.js
// and style-match.js render (MutationObserver, IntersectionObserver, pointer events, window.HT.ui's level callbacks) and adds motion on
// top, one function per Lucian element. With prefers-reduced-motion: reduce nothing here is installed and the CSS under html.ht-fx is inert.
const RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false, addEventListener() {} };
const html = document.documentElement;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const on = () => html.classList.contains('ht-fx');
const raf = (fn) => requestAnimationFrame(fn);
const NS = 'http://www.w3.org/2000/svg';
const CHECK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.4l3 3 6-6.4"/></svg>';
function observe(target, cb, opts) {  // with a circuit breaker: a callback that re-triggers itself (a class written on every report) would otherwise spin the microtask queue and freeze the page (fx019, 10-27)
  if (!target) return null; let n = 0, t = 0;
  const mo = new MutationObserver((ms) => { const now = performance.now(); if (now - t > 50) { n = 0; t = now; } if (++n > 400) { mo.disconnect(); console.warn('[lucian-effects] observer storm on', target, '- effect disconnected'); return; } cb(ms, mo); });
  mo.observe(target, opts); return mo;
}
function el(tag, cls, html_) { const n = document.createElement(tag); if (cls) n.className = cls; if (html_ != null) n.innerHTML = html_; return n; }
function hide(n) { n.setAttribute('aria-hidden', 'true'); return n; }
const stops = [];  // what to undo if the motion preference flips to "reduce" while the page is open

/* ---- phase mirror: #app[data-phase] (ui-qi.js) → html[data-ht-fx-phase], so the panel (outside #app) can read it too ---- */
function fxPhase() {
  const app = $('#app'); if (!app) return;
  const sync = () => { const p = app.dataset.phase || 'idle'; if (html.dataset.htFxPhase !== p) html.dataset.htFxPhase = p; };
  observe(app, sync, { attributes: true, attributeFilter: ['data-phase'] }); sync();
}

/* ---- 237 Line-by-line mask reveal headline ---- */
function fx237() {
  const h = $('#hero-title'); if (!h) return;
  let mine = false, prev = [];
  const linesOf = (node) => { const out = []; let cur = ''; node.childNodes.forEach((n) => { if (n.nodeName === 'BR') { out.push(cur); cur = ''; } else cur += n.textContent; }); out.push(cur); return out.map((s) => s.trim()).filter(Boolean); };
  const build = (lines, cls) => { const cp = el('span', 'ht-fx-237-cp' + (cls ? ' ' + cls : '')); lines.forEach((t, i) => { const ln = el('span', 'ht-fx-237-ln'); const inn = el('span', 'ht-fx-237-in'); inn.textContent = t; inn.style.setProperty('--i', i); ln.append(inn); cp.append(ln); }); return cp; };
  const render = () => {
    if (mine || h.querySelector('.ht-fx-237')) return;
    const lines = linesOf(h); if (!lines.length) { prev = []; return; }
    mine = true;
    const wrap = el('span', 'ht-fx-237'); const same = prev.join('\n') === lines.join('\n');
    if (prev.length && !same && on()) { const ghost = hide(build(prev, 'is-ghost is-in')); wrap.append(ghost); raf(() => { ghost.classList.remove('is-in'); ghost.classList.add('is-out'); setTimeout(() => ghost.remove(), 700); }); }
    const cp = build(lines, same || !on() ? 'is-in' : ''); wrap.append(cp); h.replaceChildren(wrap);
    if (!same && on()) { void cp.offsetWidth; cp.classList.add('is-in'); }
    prev = lines; queueMicrotask(() => { mine = false; });
  };
  observe(h, render, { childList: true, characterData: true, subtree: true }); render();
}

/* ---- 216 Staggered hero entrance ---- */
function fx216() {
  const stagger = (els, step, base) => { els.forEach((e, i) => { if (!e || e.hasAttribute('data-ht-fx-216')) return; e.setAttribute('data-ht-fx-216', ''); e.style.setProperty('--d', base + i * step); }); raf(() => raf(() => els.forEach((e) => e && e.setAttribute('data-ht-fx-216', 'in')))); setTimeout(() => els.forEach((e) => e && e.setAttribute('data-ht-fx-216', 'in')), 1600); };
  stagger([$('.nav-pill'), $('#hero-lede'), $('#dock .voice-intro'), $('#dock .search-box'), $('#dock .suggestions'), $('#dock .dock-hint')], 110, 0);
  // what appears later: the welcome-back box (a returning renter) and the "Looks like this" style chips
  const later = (root, sel, step) => observe(root, (ms) => { const found = []; ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType !== 1) return; if (n.matches(sel)) found.push(n); found.push(...$$(sel, n)); })); if (found.length && on()) stagger(found, step, 60); }, { childList: true, subtree: true });
  later($('#hero-content'), '#welcome-back', 0);
  later($('#explore'), '.ht-style-chip', 60);
}

/* ---- 363 Dot grid waves from the cursor (canvas behind the orbit; a frame loop only while a ripple is alive) ---- */
function fx363() {
  const hero = $('.hero'); if (!hero || !on()) return;
  const cv = hide(el('canvas', 'ht-fx-363')); hero.prepend(cv);
  const cx = cv.getContext('2d'); const dpr = Math.min(2, window.devicePixelRatio || 1); const GAP = 24;
  let W = 0, H = 0, dots = [], waves = [], lastAdd = 0, rafId = 0, vis = true;
  const size = () => { W = hero.clientWidth; H = hero.clientHeight; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + 'px'; cv.style.height = H + 'px'; cx.setTransform(dpr, 0, 0, dpr, 0, 0); dots = []; for (let y = GAP; y < H - 4; y += GAP) for (let x = GAP; x < W - 4; x += GAP) dots.push([x, y]); draw(performance.now()); };
  function draw(now) {
    cx.clearRect(0, 0, W, H); waves = waves.filter((w) => now - w.t < 2600);
    for (const d of dots) {
      let h = 0;
      for (const w of waves) { const age = (now - w.t) / 1000, k = Math.hypot(d[0] - w.x, d[1] - w.y) - age * 170; if (k > 0 || k < -90) continue; h += Math.sin(k / 14) * Math.exp(k / 60) * w.a * Math.exp(-age * 1.3); }
      const m = Math.max(-1, Math.min(1.6, h)), r = 1.4 + Math.max(0, m) * 3, calm = Math.abs(m) < 0.04;
      cx.globalAlpha = calm ? 0.5 : 0.9; cx.fillStyle = calm ? '#d9ddd8' : `hsl(150 55% ${Math.round(44 - m * 8)}%)`;
      cx.beginPath(); cx.arc(d[0], d[1] - m * 3, r, 0, 6.2832); cx.fill();
    }
    cx.globalAlpha = 1;
  }
  const active = () => on() && vis && !document.hidden && !hero.classList.contains('has-results') && (($('#orbit') || {}).dataset || {}).paused !== 'true';
  function frame(now) { rafId = 0; if (!cv.isConnected) return; draw(now); if (waves.length && active()) rafId = raf(frame); }
  const run = () => { if (!rafId && active()) rafId = raf(frame); };
  hero.addEventListener('pointermove', (e) => { if (e.pointerType === 'touch' || !active()) return; const now = performance.now(); if (now - lastAdd < 110) return; lastAdd = now; const r = cv.getBoundingClientRect(); waves.push({ x: e.clientX - r.left, y: e.clientY - r.top, t: now, a: 0.55 }); if (waves.length > 14) waves.shift(); run(); }, { passive: true });
  if ('IntersectionObserver' in window) new IntersectionObserver((es) => { vis = es[0].isIntersecting; run(); }).observe(hero);
  if ('ResizeObserver' in window) new ResizeObserver(size).observe(hero); else size();
  stops.push(() => { waves = []; cv.remove(); });
}

/* ---- 002 Magnetic arrow button (the send button) ---- */
function fx002() {
  const btn = $('#send'), form = $('#composer'), box = $('#dock .search-box'); if (!btn || !form) return;
  const svg = btn.querySelector('svg');
  if (svg && !btn.querySelector('.ht-fx-002-dup')) { const dup = svg.cloneNode(true); dup.classList.add('ht-fx-002-dup'); dup.setAttribute('aria-hidden', 'true'); btn.append(dup); }
  let t = 0;
  document.addEventListener('submit', (e) => { const v = ($('#text') || {}).value; if (e.target !== form || !on() || !v || !v.trim()) return; clearTimeout(t); btn.removeAttribute('data-ht-fx-002'); void btn.offsetWidth; btn.setAttribute('data-ht-fx-002', 'go'); t = setTimeout(() => btn.removeAttribute('data-ht-fx-002'), 900); }, true);
  if (box) {
    box.addEventListener('pointermove', (e) => { if (!on() || e.pointerType === 'touch') return; const r = btn.getBoundingClientRect(); const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2); const p = Math.max(0, 1 - Math.hypot(dx, dy) / 90); btn.style.translate = p ? `${(dx * 0.18 * p).toFixed(1)}px ${(dy * 0.22 * p).toFixed(1)}px` : ''; }, { passive: true });
    box.addEventListener('pointerleave', () => { btn.style.translate = ''; });
  }
}

/* ---- 019 Interest chips multi-select (the needs chips: a check slides out when a need is answered, the one being asked flashes) ---- */
function fx019() {
  const seen = new Set();
  const deco = (root) => { if (!root) return; $$('.criterion-chip.need', root).forEach((c) => {
    if (c.querySelector('.ht-fx-019-ck')) return;
    if (c.classList.contains('set')) { const key = c.textContent.trim(); const i = hide(el('i', 'ht-fx-019-ck', CHECK)); const ico = c.querySelector('.ico'); c.insertBefore(i, ico ? ico.nextSibling : c.firstChild); if (seen.has(key) || !on()) i.classList.add('is-on'); else { seen.add(key); void i.offsetWidth; i.classList.add('is-on'); } }
    else if (c.classList.contains('asking') && on() && !c.classList.contains('ht-fx-019-flash')) c.classList.add('ht-fx-019-flash');  // only once: classList.add of a class already there still reports a mutation, and this panel observer watches class changes
  }); };
  [$('#search-criteria'), $('#needs-results')].forEach((r) => { if (!r) return; observe(r, () => { if (!r.children.length) seen.clear(); deco(r); }, { childList: true }); deco(r); });
  const panel = $('.agent-criteria'); if (panel) observe(panel, () => deco(panel), { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
}

/* ---- 084 Voice-reactive dot loader (next to the status in the dock line and in the panel) ---- */
function fx084() {
  const make = () => { const d = hide(el('span', 'ht-fx-084')); for (let i = 0; i < 5; i++) { const b = el('i'); b.style.setProperty('--i', i); d.append(b); } return d; };
  const hosts = [];
  const phase = $('#phase'); if (phase) { const d = make(); phase.after(d); hosts.push(d); }
  const st = $('.agent-status'); if (st) { const d = make(); st.append(d); hosts.push(d); }
  if (!hosts.length) return;
  const feed = (x) => { if (!on()) return; const v = Math.max(0, Math.min(1, Number(x) || 0)), t = performance.now() / 1000; hosts.forEach((h) => { h.dataset.live = '1'; Array.from(h.children).forEach((b, i) => b.style.setProperty('--h', Math.max(0, Math.min(1, v * (0.55 + 0.45 * Math.abs(Math.sin(t * 9 + i * 1.3))))).toFixed(3))); }); };
  const hook = () => { const ui = window.HT && window.HT.ui; if (!ui || ui.__fx084) return !!ui; ui.__fx084 = true;
    [['level', 'listening'], ['botLevel', 'speaking']].forEach(([k, when]) => { const orig = ui[k]; if (typeof orig !== 'function') return; ui[k] = function () { const r = orig.apply(this, arguments); if (html.dataset.htFxPhase === when) feed(arguments[0]); return r; }; });
    return true; };
  if (!hook()) { let n = 0; const t = setInterval(() => { if (hook() || ++n > 20) clearInterval(t); }, 250); }
  observe(html, () => hosts.forEach((h) => { delete h.dataset.live; Array.from(h.children).forEach((b) => b.style.removeProperty('--h')); }), { attributes: true, attributeFilter: ['data-ht-fx-phase'] });
}

/* ---- 083 Queue bar turning into progress (under the Sources label) ---- */
function fx083() {
  const wrap = $('#sources-wrap'), lbl = wrap && wrap.querySelector('.ht-sources-lbl'), cnt = $('#sources-count'); if (!wrap || !lbl || !cnt) return;
  const trk = hide(el('div', 'ht-fx-083-trk', '<span class="ht-fx-083-seg a"></span><span class="ht-fx-083-seg b"></span><span class="ht-fx-083-fill"></span>')); lbl.after(trk);
  const fill = trk.lastElementChild;
  const update = () => { const t = cnt.textContent.trim(); const m = /^(\d+) of (\d+) checked/.exec(t); trk.hidden = !t; if (m) { const p = Number(m[2]) ? Number(m[1]) / Number(m[2]) : 0; trk.classList.add('is-det'); trk.classList.toggle('is-done', p >= 1); fill.style.setProperty('--p', p.toFixed(3)); } else { trk.classList.remove('is-det', 'is-done'); fill.style.setProperty('--p', 0); } };
  observe(cnt, update, { childList: true, characterData: true, subtree: true }); update();
}

/* ---- 014 To-do checklist (the progress ring, one per source group heading) ---- */
function fx014() {
  const list = $('#sources'), cnt = $('#sources-count'); if (!list) return;
  const RING = '<svg viewBox="0 0 14 14" aria-hidden="true"><circle class="bg" cx="7" cy="7" r="5"/><circle class="fg" cx="7" cy="7" r="5"/></svg><span class="ht-fx-014-done">' + CHECK + '</span>';
  let busy = false;
  const update = () => { if (busy) return; busy = true;
    const closed = cnt && / of /.test(cnt.textContent);  // the search is over (ui-qi's "k of n checked"); while it runs the total is unknown
    $$('li.ht-stage', list).forEach((h) => {
      if (h.classList.contains('empty')) return;
      let ring = h.querySelector('.ht-fx-014'); if (!ring) { ring = hide(el('span', 'ht-fx-014', RING)); h.prepend(ring); }
      const rows = $$('li[data-stage="' + h.dataset.stage + '"]:not(.ht-stage)', list), done = rows.filter((r) => r.classList.contains('done')).length;
      ring.hidden = !rows.length; ring.style.setProperty('--p', rows.length ? (done / rows.length).toFixed(3) : 0);
      ring.classList.toggle('is-all', closed && rows.length > 0 && done === rows.length);
    });
    queueMicrotask(() => { busy = false; }); };
  observe(list, update, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  if (cnt) observe(cnt, update, { childList: true, characterData: true, subtree: true });
  update();
}

/* ---- 047 Period segmented control (its count-up: row counts per source, the grid's place count, the card's tally) ---- */
function tween(node, from, to, fmt, dur = 600, done) {
  if (!on() || from === to) { node.textContent = fmt(to); if (done) done(); return; }
  const t0 = performance.now();
  (function step(now) { if (!node.isConnected) { if (done) done(); return; } const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 4); node.textContent = fmt(Math.round(from + (to - from) * e)); if (k < 1) raf(step); else if (done) done(); })(t0);
}
function fx047() {
  const num = (v) => Number(v).toLocaleString('en-AU');
  const list = $('#sources');
  if (list) observe(list, (ms) => ms.forEach((m) => { const li = m.target; if (!(li instanceof Element) || !li.classList.contains('done')) return; const n = li.querySelector('.s-n'); if (!n || n.dataset.fx) return; const mm = /^([\d,]+) rows · (.*)$/.exec(n.textContent); if (!mm) return; n.dataset.fx = '1'; const b = el('b', 'ht-fx-047'); n.replaceChildren(b, document.createTextNode(' rows · ' + mm[2])); tween(b, 0, Number(mm[1].replace(/,/g, '')), num, 500); }), { attributes: true, attributeFilter: ['class'], subtree: true });
  const cc = $('#collection-count');
  if (cc) { let last = null, mine = false; observe(cc, () => { if (mine) return; const m = /^(\d+) (place.*)$/.exec(cc.textContent.trim()); if (!m) return; const to = Number(m[1]), tail = ' ' + m[2]; if (last == null) { last = to; return; } const from = last; last = to; if (from === to) return; mine = true; const b = el('b', 'ht-fx-047'); cc.replaceChildren(b, document.createTextNode(tail)); tween(b, from, to, num, 500, () => setTimeout(() => { mine = false; }, 0)); }, { childList: true, characterData: true, subtree: true }); }
  const slot = $('#result-main-slot');
  if (slot) { const last = new Map(); observe(slot, () => { const main = slot.querySelector('.result-main'); if (!main) return; $$('.ht-summary b', main).forEach((b, i) => { if (b.dataset.fx) return; b.dataset.fx = '1'; const to = Number(b.textContent); if (!Number.isFinite(to)) return; const key = main.dataset.id + '|' + i; const from = last.has(key) ? last.get(key) : 0; last.set(key, to); if (from !== to) tween(b, from, to, String, 500); }); }, { childList: true, subtree: true }); }
}

/* ---- 018 Rolling quantity stepper (the odometer on the rank badge and the Saved count) ---- */
function odometer(host, prefix, n, animate, lh) {
  let odo = host.querySelector('.ht-fx-018');
  const digits = String(n).split('').map(Number); const cols = Math.max(digits.length, odo ? odo.children.length : 0, 1);
  if (!odo) { odo = hide(el('span', 'ht-fx-018')); odo.style.setProperty('--lh', lh + 'px'); host.replaceChildren(document.createTextNode(prefix), odo); }
  while (odo.children.length < cols) { const c = el('span', 'ht-fx-018-col no-anim'); for (let d = 0; d < 10; d++) { const s = el('span'); s.textContent = String(d); c.append(s); } odo.prepend(c); }
  const pad = Array(cols - digits.length).fill(0).concat(digits);
  Array.from(odo.children).forEach((c, i) => { c.classList.toggle('no-anim', !animate); c.classList.toggle('is-hide', i < cols - digits.length); c.style.transform = `translateY(${-pad[i] * lh}px)`; });
  if (!animate) { void odo.offsetWidth; Array.from(odo.children).forEach((c) => c.classList.remove('no-anim')); }
}
function fx018() {
  const sc = $('#saved-count');
  if (sc) { let last = null, mine = false; const apply = () => { if (mine || sc.querySelector('.ht-fx-018')) return; const v = sc.textContent.trim(); if (!/^\d+$/.test(v)) return; const n = Number(v); mine = true; if (last != null && last !== n && on()) { odometer(sc, '', last, false, 18); void sc.offsetWidth; odometer(sc, '', n, true, 18); } else odometer(sc, '', n, false, 18); last = n; queueMicrotask(() => { mine = false; }); };
    observe(sc, apply, { childList: true, characterData: true, subtree: true }); apply(); stops.push(() => { if (last != null) sc.textContent = String(last); }); }
  const slot = $('#result-main-slot');
  if (slot) { const last = new Map(); let mine = false; const apply = () => { if (mine) return; const main = slot.querySelector('.result-main'); const b = main && main.querySelector('.result-photo-wrap .rank'); if (!b || b.querySelector('.ht-fx-018')) return; const m = /^#(\d+)$/.exec(b.textContent.trim()); if (!m) return; const n = Number(m[1]), id = main.dataset.id, was = last.get(id); mine = true; if (was != null && was !== n && on()) { odometer(b, '#', was, false, 18); void b.offsetWidth; odometer(b, '#', n, true, 18); } else odometer(b, '#', n, false, 18); last.set(id, n); queueMicrotask(() => { mine = false; }); };
    observe(slot, apply, { childList: true, characterData: true, subtree: true }); }
}

/* ---- 368 Sentence-following reading focus (the bar glides to the line being discussed) ---- */
function fx368() {
  const slot = $('#result-main-slot'); if (!slot) return; const last = new Map(); let queued = 0;
  const place = () => { queued = 0; const main = slot.querySelector('.result-main'); const ul = main && main.querySelector('.rows'); if (!ul) return;
    let bar = ul.querySelector('.ht-fx-368-bar');
    if (!bar) { bar = hide(el('li', 'ht-fx-368-bar')); ul.prepend(bar); const p = last.get(main.dataset.id); if (p) { bar.style.transition = 'none'; bar.style.transform = `translateY(${p.y}px)`; bar.style.height = p.h + 'px'; void bar.offsetWidth; bar.style.transition = ''; } }
    const lit = ul.querySelector('.row.lit'); if (!lit) { if (bar.classList.contains('is-on')) bar.classList.remove('is-on'); return; }
    const y = lit.offsetTop + 4, h = Math.max(8, lit.offsetHeight - 8);
    bar.style.transform = `translateY(${y}px)`; bar.style.height = h + 'px'; if (!bar.classList.contains('is-on')) bar.classList.add('is-on'); last.set(main.dataset.id, { y, h }); };
  observe(slot, () => { if (!queued) queued = raf(place); }, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
}

/* ---- 081 Payment ring and check (the evidence block rises under its line; a ring draws around the status word) ---- */
function fx081() {
  const deco = (li) => { if (li.dataset.fx || !on()) return; li.dataset.fx = '1';
    const inner = el('div', 'ht-fx-081-in'); while (li.firstChild) inner.append(li.firstChild); li.append(inner); void li.offsetWidth; li.classList.add('is-open');
    const chip = inner.querySelector('.ev-where .chip'); if (!chip) return;
    const w = chip.offsetWidth + 6, h = chip.offsetHeight + 6; if (!w || !h) return;
    const svg = document.createElementNS(NS, 'svg'); svg.setAttribute('class', 'ht-fx-081-ring'); svg.setAttribute('viewBox', `0 0 ${w} ${h}`); svg.setAttribute('aria-hidden', 'true');
    const r = document.createElementNS(NS, 'rect'); r.setAttribute('x', '1'); r.setAttribute('y', '1'); r.setAttribute('width', String(w - 2)); r.setAttribute('height', String(h - 2)); r.setAttribute('rx', String((h - 2) / 2)); r.setAttribute('pathLength', '100');
    svg.append(r); chip.append(svg); setTimeout(() => svg.remove(), 2200); };
  const watch = (root) => observe(root, (ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1 && n.classList.contains('ht-ev-row')) deco(n); })), { childList: true, subtree: true });
  watch($('#result-main-slot')); watch($('#detail-dialog'));
}

/* ---- 070 Stacking toasts (mirrors #toast, which stays as the live region) ---- */
function fx070() {
  const t = $('#toast'); if (!t || !on()) return;
  const zone = hide(el('div', 'ht-fx-070')); document.body.append(zone);
  const list = []; let open = false; const DUR = 3800;
  const layout = () => { let acc = 0; list.forEach((it, i) => { const e = it.el; e.classList.toggle('back', !open && i > 0); if (open) { e.style.setProperty('--y', -acc + 'px'); e.style.setProperty('--s', '1'); e.style.setProperty('--o', '1'); acc += e.offsetHeight + 8; } else { e.style.setProperty('--y', -(i * 10) + 'px'); e.style.setProperty('--s', (1 - i * 0.06).toFixed(2)); e.style.setProperty('--o', i > 2 ? '0' : '1'); } e.style.zIndex = String(50 - i); }); zone.classList.toggle('is-open', open); };
  const remove = (it) => { const i = list.indexOf(it); if (i < 0) return; list.splice(i, 1); clearTimeout(it.t); it.el.classList.add('leave'); setTimeout(() => it.el.remove(), 450); layout(); };
  const arm = (it) => { clearTimeout(it.t); it.at = performance.now(); it.t = setTimeout(() => remove(it), it.left); };
  const push = (text) => { const e = el('div', 'ht-fx-070-t enter', '<span></span><i class="ht-fx-070-bar"></i>'); e.firstChild.textContent = text; e.style.setProperty('--dur', DUR + 'ms'); zone.append(e); const it = { el: e, left: DUR, t: 0, at: performance.now(), text }; list.unshift(it); void e.offsetWidth; e.classList.remove('enter'); while (list.length > 4) remove(list[list.length - 1]); layout(); if (!open) arm(it); };
  zone.addEventListener('pointerenter', (e) => { if (e.pointerType !== 'mouse' || open) return; open = true; list.forEach((it) => { clearTimeout(it.t); it.left = Math.max(800, it.left - (performance.now() - it.at)); }); layout(); });
  zone.addEventListener('pointerleave', () => { if (!open) return; open = false; layout(); list.forEach(arm); });
  observe(t, () => { if (!on() || !t.classList.contains('visible')) return; const text = t.textContent.trim(); if (!text) return; if (list[0] && list[0].text === text && performance.now() - list[0].at < 400) return; push(text); }, { attributes: true, attributeFilter: ['class'], childList: true, characterData: true, subtree: true });
  stops.push(() => zone.remove());
}

/* ---- 050 Spotlight-tilt news card (glare + border light + a small lift on the photo out front; no tilt) ---- */
function fx050() {
  const slot = $('#result-main-slot'); if (!slot) return;
  slot.addEventListener('pointermove', (e) => { if (!on() || e.pointerType === 'touch') return; const wrap = e.target.closest('.result-photo-wrap'); if (!wrap) return;
    const btn = wrap.querySelector('.result-photo-button'); if (btn && !btn.querySelector('.ht-fx-050-glare')) btn.append(hide(el('span', 'ht-fx-050-glare')));
    const r = wrap.getBoundingClientRect(); wrap.classList.add('is-live'); wrap.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%'); wrap.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%'); }, { passive: true });
  slot.addEventListener('pointerout', (e) => { const wrap = e.target.closest('.result-photo-wrap'); if (wrap && !wrap.contains(e.relatedTarget)) wrap.classList.remove('is-live'); });
}

/* ---- 228 Cursor-lit glowing card borders (grid cards and the small cards) ---- */
function fx228() {
  const lamp = (root, sel) => { if (!root) return; let p = null, queued = 0;
    const apply = () => { queued = 0; $$(sel, root).forEach((c) => { const r = c.getBoundingClientRect(); if (!p) { c.classList.remove('is-lit'); return; } const lx = p.x - r.left, ly = p.y - r.top; const dx = Math.max(r.left - p.x, 0, p.x - r.right), dy = Math.max(r.top - p.y, 0, p.y - r.bottom); c.style.setProperty('--cx', lx.toFixed(1) + 'px'); c.style.setProperty('--cy', ly.toFixed(1) + 'px'); c.classList.toggle('is-lit', Math.hypot(dx, dy) < 200); }); };
    root.addEventListener('pointermove', (e) => { if (!on() || e.pointerType === 'touch') return; p = { x: e.clientX, y: e.clientY }; if (!queued) queued = raf(apply); }, { passive: true });
    root.addEventListener('pointerleave', () => { p = null; if (!queued) queued = raf(apply); }); };
  lamp($('#property-grid'), '.property-image-wrap'); lamp($('#result-side'), '.result-mini');
}

/* ---- 039 Sliding pill tabs (the nav pill and the suburb groups) ---- */
function fx039() {
  [[$('.nav-pill'), '.active'], [$('#collection-controls'), 'button.active']].forEach(([g, sel]) => { if (!g) return;
    const pill = hide(el('span', 'ht-fx-039-pill no-anim')); let queued = 0;
    const place = (anim) => { queued = 0; if (!pill.isConnected) g.prepend(pill); const a = g.querySelector(sel); if (!a || !a.offsetWidth) { pill.style.opacity = '0'; return; } pill.style.opacity = ''; if (!anim && !pill.classList.contains('no-anim')) pill.classList.add('no-anim'); pill.style.setProperty('--x', a.offsetLeft + 'px'); pill.style.setProperty('--w', a.offsetWidth + 'px'); if (!anim) { void pill.offsetWidth; (pill.classList.contains('no-anim') && pill.classList.remove('no-anim')); } };
    observe(g, () => { if (!queued) queued = raf(() => place(true)); }, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
    if ('ResizeObserver' in window) new ResizeObserver(() => place(false)).observe(g);
    place(false); if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => place(false)); });
  // which nav item is current: the section in view, or Saved while that list is open
  const find = $('.nav-pill .nav-find'), explore = $('.nav-pill .nav-explore'), saved = $('#saved-open'), dlg = $('#saved-dialog'), sec = $('#explore');
  let cur = '';
  const set = () => { const so = !!(dlg && dlg.open); const where = so ? 'saved' : sec && window.scrollY + window.innerHeight * 0.45 >= sec.offsetTop ? 'explore' : 'home'; if (where === cur) return; cur = where; if (find) find.classList.toggle('active', where === 'home'); if (explore) explore.classList.toggle('active', where === 'explore'); if (saved) saved.classList.toggle('active', where === 'saved'); };
  window.addEventListener('scroll', set, { passive: true }); if (dlg) observe(dlg, set, { attributes: true, attributeFilter: ['open'] }); set();
}

/* ---- 212 Hide-on-scroll header ---- */
function fx212() {
  const bar = $('.topbar'); if (!bar) return; bar.append(hide(el('span', 'ht-fx-212-pg'))); const pg = bar.lastElementChild;
  let last = window.scrollY, acc = 0, pinned = false;
  const pin = (v) => { if (pinned === v) return; pinned = v; if (v) { document.body.style.paddingTop = bar.offsetHeight + 'px'; bar.classList.add('ht-fx-212-pin', 'is-hide'); void bar.offsetWidth; } else { bar.classList.remove('ht-fx-212-pin', 'is-hide'); document.body.style.paddingTop = ''; } };
  const onScroll = () => { if (!on()) { pin(false); return; } const y = window.scrollY, d = y - last; last = y; acc = (d > 0) === (acc > 0) ? acc + d : d;
    if (y < 60) pin(false);
    else if (acc > 8) { if (pinned) bar.classList.add('is-hide'); }
    else if (acc < -6) { if (!pinned) pin(true); raf(() => bar.classList.remove('is-hide')); }
    pg.style.width = (y / Math.max(1, html.scrollHeight - window.innerHeight) * 100).toFixed(1) + '%'; };
  window.addEventListener('scroll', onScroll, { passive: true });
  stops.push(() => pin(false));
}

/* ---- 251 Staggered scroll-in feature cards (the section title's underline) ---- */
function fx251() {
  const h = $('#explore-title'); if (!h || !('IntersectionObserver' in window)) return;
  new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) h.classList.add('is-in'); else if (e.boundingClientRect.top > window.innerHeight - 1) h.classList.remove('is-in'); }), { threshold: 0.5 }).observe(h);
}

/* ---- 022 Heart burst like (the save button) ---- */
function fx022() {
  const DOTS = [[0, '#0d913e', '#d6a21e'], [51, '#7bd389', '#2f8fe0'], [103, '#d6a21e', '#0d913e'], [154, '#0d913e', '#7bd389'], [206, '#2f8fe0', '#d6a21e'], [257, '#7bd389', '#0d913e'], [309, '#d6a21e', '#2f8fe0']];
  const burst = (b) => { if (!b.querySelector('.ht-fx-022-ring')) { b.append(hide(el('span', 'ht-fx-022-ring'))); DOTS.forEach(([a, c, c2]) => { const d = hide(el('span', 'ht-fx-022-dot', '<i></i><i></i>')); d.style.setProperty('--a', a + 'deg'); d.style.setProperty('--c', c); d.style.setProperty('--c2', c2); b.append(d); }); }
    b.classList.remove('ht-fx-022-pop'); void b.offsetWidth; b.classList.add('ht-fx-022-pop'); setTimeout(() => b.classList.remove('ht-fx-022-pop'), 900); };
  document.addEventListener('click', (e) => { const b = e.target.closest('.save-home'); if (!b || !on()) return; raf(() => { if (b.isConnected && b.getAttribute('aria-pressed') === 'true') burst(b); }); });
}

/* ---- 092 Empty search that loosens filters (the magnifier over empty shelves, above the empty-grid line) ---- */
function fx092() {
  const g = $('#empty-grid'); if (!g) return;
  const ART = '<svg viewBox="0 0 150 92" aria-hidden="true"><path class="shelf" d="M8 30h134M8 56h134M8 82h134"/><g class="lens"><circle cx="34" cy="38" r="20"/><path class="gl" d="M24 30a12 12 0 0 1 8-5"/><path d="M48 52l14 14"/></g></svg>';
  const sync = () => { if (g.hidden) return; if (!g.querySelector('.ht-fx-092')) g.prepend(hide(el('span', 'ht-fx-092', ART))); };
  observe(g, sync, { attributes: true, attributeFilter: ['hidden'] }); sync();
}

/* ---- 090 Error widget that plugs back in (the pulled plug next to an error line; the voice-line pill shakes) ---- */
function fx090() {
  const cap = $('#caption'); if (!cap) return;
  const PLUG = '<svg viewBox="0 0 220 70" aria-hidden="true"><g class="L"><path class="cord" d="M-14 54C24 54 40 35 72 35"/><path class="pr" d="M100 28h14M100 42h14"/><rect class="bd" x="68" y="19" width="34" height="32" rx="8"/></g><g class="R"><rect class="bd" x="124" y="17" width="38" height="36" rx="9"/><path class="hole" d="M124 28h6M124 42h6"/><circle class="led" cx="153" cy="25" r="3"/><path class="cord" d="M162 35C188 35 194 16 236 16"/></g></svg>';
  let t = 0;
  observe(cap, () => { const err = cap.querySelector('.error'); if (!err || err.querySelector('.ht-fx-090') || !on()) return; err.prepend(hide(el('span', 'ht-fx-090', PLUG))); cap.classList.add('ht-fx-090-shake'); clearTimeout(t); t = setTimeout(() => cap.classList.remove('ht-fx-090-shake'), 600); }, { childList: true, subtree: true });
}

/* ---- 086 Streaming AI answer (the caption arrives word by word; a cursor while it is still speaking) ---- */
function fx086() {
  const cap = $('#caption'); if (!cap) return; let mine = false;
  const wrap = () => { if (mine || !on()) return; if (cap.childNodes.length !== 1 || cap.firstChild.nodeType !== 3) return; const text = cap.textContent; if (!text.trim()) return;
    mine = true; const frag = document.createDocumentFragment(); let i = 0;
    text.split(/(\s+)/).forEach((tok) => { if (!tok) return; if (/^\s+$/.test(tok)) { frag.append(document.createTextNode(tok)); return; } const w = el('span', 'ht-fx-086-w'); w.textContent = tok; w.style.setProperty('--d', Math.min(i * 45, 1100) + 'ms'); i++; frag.append(w); });
    cap.replaceChildren(frag); queueMicrotask(() => { mine = false; }); };
  observe(cap, wrap, { childList: true, characterData: true, subtree: true });
}

/* ---- boot: wait for ui-qi.js to have built #app, then install everything (or nothing, under prefers-reduced-motion) ---- */
function install() {
  html.classList.add('ht-fx');
  [fxPhase, fx237, fx216, fx363, fx002, fx019, fx084, fx083, fx014, fx047, fx018, fx368, fx081, fx070, fx050, fx228, fx039, fx212, fx251, fx022, fx092, fx090, fx086]
    .forEach((f) => { try { f(); } catch (e) { console.warn('[lucian-effects] ' + f.name, e); } });
}
function boot() {
  if (!$('#hero-title')) { const mo = new MutationObserver(() => { if ($('#hero-title')) { mo.disconnect(); boot(); } }); mo.observe($('#app') || document.body, { childList: true, subtree: true }); return; }
  let installed = false;
  const sync = () => { if (RM.matches) { html.classList.remove('ht-fx'); stops.splice(0).forEach((s) => { try { s(); } catch (e) { /* already gone */ } }); } else if (!installed) { installed = true; install(); } else html.classList.add('ht-fx'); };
  sync(); if (RM.addEventListener) RM.addEventListener('change', sync);
}
boot();
