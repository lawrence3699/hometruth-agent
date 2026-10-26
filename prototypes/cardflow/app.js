// HomeTruth card-flow prototype: front end only, all mock.
// Background = a slow wall of listing cards. The user describes what they need, the page asks for
// missing must-haves (docs/00 §4.3), scans the wall, lifts the best few to the front and walks
// through them. Scrolling drives the walkthrough the way haoqi.design's hero drives its page.
'use strict';
window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const EASE = 'cubic-bezier(.22,1,.36,1)';
const RM = matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const pad = n => String(n).padStart(2, '0');
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const NUMW = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const numWord = n => NUMW[n] || String(n);
const ORD = ['first', 'second', 'third', 'fourth', 'fifth'];
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const MONL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const toDate = iso => new Date(iso + 'T00:00:00Z');
const days = (a, b) => Math.round((toDate(a) - toDate(b)) / 864e5);
const fmtShort = iso => { const d = toDate(iso); return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
const fmtSpoken = iso => { const d = toDate(iso); return `${d.getUTCDate()} ${MONL[d.getUTCMonth()]}`; };

const REQUIRED = ['A1', 'B1', 'G1', 'A4', 'J1'];
const HUBS = { central: { label: 'Central', chip: 'CENTRAL' }, unsw: { label: 'UNSW', chip: 'UNSW' }, cbd: { label: 'the CBD', chip: 'CBD' } };
const SOFT = {
  C1: { label: 'Bedroom AC', chip: 'AC IN BEDROOM', phrase: 'air con in the bedrooms', q: 'Is there air con in the bedrooms, or only in the living room?' },
  E4: { label: 'Quiet', chip: 'QUIET', phrase: 'a quiet street', q: 'How much road noise reaches the bedrooms at night?' },
  E2: { label: 'Sunlight', chip: 'SUNNY', phrase: 'good sun', q: 'Which way do the living room windows face, and does anything block them?' },
  C2: { label: 'Furnished', chip: 'FURNISHED', phrase: 'furniture', q: 'Which furniture stays? Is there an inventory?' },
  P1: { label: 'Parking', chip: 'PARKING', phrase: 'parking', q: 'Is there a car space, or street parking only?' },
};
const ASKQ = { A1: "what's your weekly budget", B1: 'how many bedrooms you need', G1: 'where you need to get to most days', A4: 'when you need to move in', J1: 'whether any pets are coming with you' };
const FAILW = { A1: 'over budget', B1: 'too few bedrooms', G1: 'too far', A4: 'free too late' };
const ICON = {
  A1: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M8 2v12M11 4.5H6.5a2 2 0 0 0 0 4h3a2 2 0 0 1 0 4H5"/></svg>',
  B1: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M2 12V4M2 9h12v3M14 9V7.5A1.5 1.5 0 0 0 12.5 6H7v3"/><circle cx="4.6" cy="7.4" r="1.2"/></svg>',
  G1: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M8 14.5s4.5-4.3 4.5-8a4.5 4.5 0 0 0-9 0c0 3.7 4.5 8 4.5 8z"/><circle cx="8" cy="6.5" r="1.6"/></svg>',
  A4: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"/></svg>',
  J1: '<svg viewBox="0 0 16 16" fill="currentColor"><ellipse cx="8" cy="11" rx="3" ry="2.5"/><circle cx="3.6" cy="7.4" r="1.3"/><circle cx="12.4" cy="7.4" r="1.3"/><circle cx="6" cy="4.4" r="1.3"/><circle cx="10" cy="4.4" r="1.3"/></svg>',
  plus: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M8 3v10M3 8h10"/></svg>',
};
const KEYLABEL = { A1: 'BUDGET', B1: 'BEDROOMS', G1: 'AREA', A4: 'MOVE-IN', J1: 'PETS' };

const S = {
  phase: 'idle', needs: blankNeeds(), rounds: 0, asked: [], assumed: new Set(),
  res: null, fits: [], picks: [], misses: [], cards: [], f: 0, focus: -1,
  token: 0, speaking: false, sound: false, auto: false, demo: false, tourDone: false, log: [], lastWheel: 0,
};

function blankNeeds() { return { A1: null, B1: null, G1: null, A4: null, J1: null, soft: [] }; }

/* ======================================================================
   Parsing: a plain rule parser standing in for the Nemotron needs parser.
   English first, plus a few Chinese keywords.
   ====================================================================== */
const WORDNUM = { one: 1, two: 2, three: 3, four: 4, single: 1, '一': 1, '两': 2, '二': 2, '三': 3, '四': 4 };
const MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };

function isoFrom(month, day) {
  const year = month >= 9 ? 2026 : 2027;
  return `${year}-${pad(month + 1)}-${pad(day)}`;
}

function parseNeeds(text, prev, asked = []) {
  const t = ' ' + text.toLowerCase().replace(/[’]/g, "'") + ' ';
  const n = { ...prev, soft: [...prev.soft] };
  const changed = [];
  const set = (k, v) => { if (JSON.stringify(n[k]) !== JSON.stringify(v)) { n[k] = v; changed.push(k); } };

  let m = t.match(/(?:under|below|max(?:imum)?|budget(?:\s+(?:of|is))?|up to|less than|no more than|around|about|\$)\s*\$?\s*(\d{3,4})\b/)
    || t.match(/\b(\d{3,4})\s*(?:a|per|\/)\s*(?:week|wk|w)\b/)
    || t.match(/(?:预算|不超过|最多)\s*\$?(\d{3,4})/) || t.match(/(\d{3,4})\s*(?:以内|以下|刀|澳|块|元)/);
  if (!m && asked.includes('A1')) m = t.match(/\b(\d{3,4})\b/);
  if (m) set('A1', +m[1]);

  m = t.match(/\b(\d|one|two|three|four|single)[\s-]*(?:bed(?:room)?s?|br|bd|b\/r)\b/) || t.match(/(\d|一|两|二|三|四)\s*(?:房|居|室|卧)/);
  if (m) set('B1', WORDNUM[m[1]] || +m[1]);
  else if (/\bstudio\b|单间|开间/.test(t)) set('B1', 1);
  else if (asked.includes('B1')) { const k = t.match(/\b(\d|one|two|three|four)\b/); if (k) set('B1', WORDNUM[k[1]] || +k[1]); }

  let hub = null;
  if (/\bcentral\b|中央车站/.test(t)) hub = 'central';
  else if (/\bunsw\b|\buni\b|university|campus|新南/.test(t)) hub = 'unsw';
  else if (/\bcbd\b|\bcity\b|town hall|wynyard|martin place|市中心|市区/.test(t)) hub = 'cbd';
  else if (/zetland|mascot/.test(t)) hub = 'central';
  else if (/kensington|kingsford|randwick/.test(t)) hub = 'unsw';
  else if (/haymarket/.test(t)) hub = 'cbd';
  const lim = t.match(/(?:within|under|less than|max|no more than)\s*(\d{1,2})\s*(?:min|mins|minutes)\b/) || t.match(/(\d{1,2})\s*分钟/);
  if (hub || lim) set('G1', { hub: hub || (n.G1 && n.G1.hub) || 'central', limit: lim ? +lim[1] : (n.G1 && n.G1.limit) || 25 });

  let date = null, label = null;
  m = t.match(/\b(early|mid|middle of|late|end of|start of|beginning of)?[\s-]*(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b/);
  const md = t.match(/\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/);
  if (md) { const mo = MONTHS[md[2]]; date = isoFrom(mo, +md[1]); label = `${+md[1]} ${MON[mo]}`; }
  else if (m && !(m[2] === 'may' && !m[1])) {
    const mo = MONTHS[m[2].slice(0, 3)];
    const q = m[1] || '';
    const day = /early/.test(q) ? 5 : /start|beginning/.test(q) ? 1 : /mid/.test(q) ? 15 : /late/.test(q) ? 24 : /end/.test(q) ? 28 : 1;
    date = isoFrom(mo, day);
    label = `${q ? q.replace(/middle of/, 'mid').replace(/ of$/, '').toUpperCase() + ' ' : ''}${MON[mo]}`;
  } else {
    const cm = t.match(/(十二|十一|十|[一二三四五六七八九]|\d{1,2})\s*月\s*(初|上旬|中旬|中|下旬|底|末)?/);
    if (cm) {
      const cn = { '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12 };
      const mo = (cn[cm[1]] || +cm[1]) - 1;
      const q = cm[2] || '';
      const day = /初|上旬/.test(q) ? 3 : /中/.test(q) ? 15 : /下旬|底|末/.test(q) ? 26 : 1;
      date = isoFrom(mo, day); label = `${q ? ({ '初': 'EARLY', '上旬': 'EARLY', '中旬': 'MID', '中': 'MID', '下旬': 'LATE', '底': 'END', '末': 'END' }[q] + ' ') : ''}${MON[mo]}`;
    } else if (/\b(asap|now|immediately|right away)\b|马上|尽快/.test(t)) { date = '2026-11-01'; label = 'ASAP'; }
    else if (/next month|下个月/.test(t)) { date = '2026-11-05'; label = 'NOV'; }
  }
  if (date) set('A4', { date, label });

  if (/\bno pets?\b|without (?:a |any )?pets?|pet[- ]free|don'?t have (?:a |any )?pets?|没有宠物|无宠物|不养/.test(t)) set('J1', 'none');
  else if (/\bcats?\b|kitten|猫/.test(t)) set('J1', 'a cat');
  else if (/\bdogs?\b|puppy|狗/.test(t)) set('J1', 'a dog');
  else if (/\bpets?\b|宠物/.test(t)) set('J1', 'a pet');
  else if (asked.includes('J1') && /^\s*(no|nope|none|nah)\b|没有/.test(t)) set('J1', 'none');

  const soft = [
    ['C1', /air ?con|a\/c|\bac\b|aircon|air-conditioning|cooling|空调/],
    ['E4', /quiet|noise|安静/],
    ['E2', /\bsun|sunny|bright|north[- ]facing|natural light|采光|朝北|阳光/],
    ['C2', /(?<!un)furnished|furniture|家具/],
    ['P1', /parking|car ?space|garage|车位|停车/],
  ];
  for (const [d, re] of soft) if (re.test(t) && !n.soft.includes(d)) { n.soft.push(d); changed.push(d); }
  return { needs: n, changed };
}

/* ======================================================================
   Checking: four states per cell (docs/01). Hard misses drop a listing,
   everything else only moves it up or down.
   ====================================================================== */
const W = { supported: 1, inferred: 0.5, unknown: 0, conflict: -1 };

function petLabel(p) { return p === 'a cat' ? 'Cat' : p === 'a dog' ? 'Dog' : 'Pet'; }

function evaluate(l, n) {
  const cells = [];
  let fail = null;
  const listingQ = `Rent $${l.rent} per week, bond 4 weeks`;
  if (n.A1) {
    const ok = l.rent <= n.A1;
    cells.push({ d: 'A1', label: 'Budget', s: ok ? 'supported' : 'conflict', v: ok ? `$${l.rent} ≤ $${n.A1}` : `$${l.rent} > $${n.A1}`, src: 'LISTING', tb: 'listings', row: l.id, q: listingQ, hard: true });
    if (!ok) fail = fail || { d: 'A1', stamp: `OVER $${n.A1}` };
  }
  if (n.B1) {
    const ok = l.bed >= n.B1;
    cells.push({ d: 'B1', label: 'Bedrooms', s: ok ? 'supported' : 'conflict', v: `${l.bed} bed, ${l.bath} bath`, src: l.planNote ? 'FLOOR PLAN' : 'LISTING', tb: l.planNote ? 'photo_facts' : 'listings', row: l.id, q: l.planNote || `${l.bed} bed, ${l.bath} bath, ${l.car} car`, hard: true });
    if (!ok) fail = fail || { d: 'B1', stamp: `ONLY ${l.bed} BD` };
  }
  if (n.G1) {
    const c = l.commute[n.G1.hub];
    const ok = c.min <= n.G1.limit;
    cells.push({ d: 'G1', label: 'Commute', s: ok ? 'supported' : 'conflict', v: `${c.min} min to ${HUBS[n.G1.hub].label.replace('the ', '')} · ${c.mode}`, src: 'TRANSIT', tb: 'public_transit', row: `${l.suburb}→${n.G1.hub}`, q: `AM peak, door to ${HUBS[n.G1.hub].label}: ${c.min} min by ${c.mode}`, hard: true });
    if (!ok) fail = fail || { d: 'G1', stamp: `${c.min} MIN AWAY` };
  }
  if (n.A4) {
    const late = days(l.avail, n.A4.date);
    const s = late <= 0 ? 'supported' : 'conflict';
    const v = late <= 0 ? `free ${fmtShort(l.avail).toLowerCase()}` : `free ${fmtShort(l.avail).toLowerCase()} · ${late} days after`;
    cells.push({ d: 'A4', label: 'Move-in', s, v, src: 'LISTING', tb: 'listings', row: l.id, q: `Available ${fmtShort(l.avail)} 2026`, hard: true, why: late > 0 ? `You asked for ${n.A4.label.toLowerCase()}.` : '' });
    if (late > 10) fail = fail || { d: 'A4', stamp: `FREE ${fmtShort(l.avail)}` };
  }
  if (n.J1 && n.J1 !== 'none') {
    const f = l.f.J1;
    cells.push({ d: 'J1', label: petLabel(n.J1), s: f.s, v: f.v, src: f.src, tb: f.tb, row: l.id, q: f.q, why: f.why, proof: f.proof, hard: true });
  }
  for (const d of n.soft) {
    const f = l.f[d];
    cells.push({ d, label: SOFT[d].label, s: f.s, v: f.v, src: f.src, tb: f.tb, row: l.id, q: f.q, why: f.why, proof: f.proof, hard: false });
  }
  let score = 0;
  for (const c of cells) {
    const w = c.hard ? 3 : 2;
    score += c.s === 'unknown' ? (c.hard ? -1 : 0) : c.s === 'conflict' && c.hard ? -4 : W[c.s] * w;
  }
  if (n.A1) score += (n.A1 - l.rent) / n.A1 * 3;
  return { l, cells, score, pass: !fail, fail };
}

function runChecks() {
  S.res = {};
  for (const l of LISTINGS) S.res[l.id] = evaluate(l, S.needs);
  const all = Object.values(S.res);
  S.fits = all.filter(r => r.pass).sort((a, b) => b.score - a.score || a.l.rent - b.l.rent);
  S.picks = S.fits.slice(0, 3);
  S.misses = all.filter(r => !r.pass).sort((a, b) => b.score - a.score).slice(0, 2);
}

function reqId(c) { return 'zq_' + (hashStr(c.row + c.d + c.tb) % 0xffffff).toString(16).padStart(6, '0'); }

/* ======================================================================
   Background wall
   ====================================================================== */
const probe = name => { const d = document.createElement('div'); d.style.cssText = `position:absolute;visibility:hidden;width:var(${name})`; document.body.appendChild(d); const w = d.offsetWidth; d.remove(); return w; };

const Wall = {
  rows: [], speed: 1, target: 1, scanning: null, cw: 0,
  build() {
    const wall = $('#wall');
    $$('.row', wall).forEach(r => r.remove());
    this.cw = probe('--cw');
    const gap = 18, pitch = this.cw + gap, rowH = this.cw + 48, vgap = 22;
    const Wd = wall.offsetWidth, H = wall.offsetHeight;
    const R = Math.max(4, Math.ceil((H + vgap) / (rowH + vgap)));
    const r = seeded(7);
    const order = [...LISTINGS].sort(() => r() - 0.5);
    const per = Array.from({ length: R }, () => []);
    order.forEach((l, i) => per[i % R].push(l));
    this.rows = per.map((seq, ri) => {
      const row = document.createElement('div');
      row.className = 'row';
      const strip = document.createElement('div');
      strip.className = 'strip';
      const seqW = seq.length * pitch;
      const k = Math.ceil((Wd + seqW) / seqW) + 1;
      let html = '';
      for (let c = 0; c < k; c++) for (const l of seq) html += wallCardHTML(l);
      strip.innerHTML = html;
      row.appendChild(strip);
      wall.appendChild(row);
      return { el: row, strip, seqW, pitch, pos: r() * seqW, p: 0, dir: ri % 2 ? 1 : -1, base: 11 + r() * 12, cards: [...strip.children], ri };
    });
    if (S.res && S.phase !== 'search') this.restore();
  },
  intro() {
    this.rows.forEach((row, i) => {
      row.el.style.setProperty('--rx', `${row.dir * -38}vw`);
      row.el.style.setProperty('--ro', 0);
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      this.rows.forEach((row, i) => {
        row.el.classList.add('intro');
        row.el.style.transitionDelay = `${i * 70}ms`;
        row.el.style.setProperty('--rx', '0px');
        row.el.style.setProperty('--ro', 1);
      });
      setTimeout(() => this.rows.forEach(row => { row.el.classList.remove('intro'); row.el.style.transitionDelay = ''; }), 2400);
    }));
  },
  tick(dt, now) {
    const k = 1 - Math.pow(0.04, dt);
    this.speed += (this.target - this.speed) * k;
    for (const row of this.rows) {
      row.pos += row.dir * row.base * this.speed * dt;
      row.p = ((row.pos % row.seqW) + row.seqW) % row.seqW;
      row.strip.style.transform = `translate3d(${(-row.p).toFixed(2)}px,0,0)`;
    }
    const sc = this.scanning;
    if (!sc) return;
    const t = clamp((now - sc.t0) / sc.dur, 0, 1);
    const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    const x = sc.x0 + (sc.x1 - sc.x0) * e;
    $('#scanLine').style.transform = `translateX(${x.toFixed(1)}px)`;
    for (const row of this.rows) {
      row.cards.forEach((card, j) => {
        if (card._ev) return;
        if (j * row.pitch - row.p + this.cw / 2 < x) this.mark(card, sc);
      });
    }
    if (t >= 1) {
      for (const row of this.rows) row.cards.forEach(c => c._ev || this.mark(c, sc));
      $('#scanLine').style.opacity = 0;
      this.scanning = null;
      sc.done();
    }
  },
  mark(card, sc) {
    card._ev = true;
    const r = S.res[card.dataset.id];
    card.classList.add(r.pass ? 'in' : 'out');
    card.querySelector('.st').textContent = r.pass ? 'FIT' : r.fail.stamp;
    if (!sc.seen.has(card.dataset.id)) { sc.seen.add(card.dataset.id); sc.onEval(r); }
  },
  scan(dur, onEval) {
    return new Promise(done => {
      const Wd = $('#wall').offsetWidth;
      $('#scanLine').style.opacity = 1;
      this.scanning = { t0: performance.now(), dur, x0: Wd * 0.15, x1: Wd * 0.87, seen: new Set(), onEval, done };
    });
  },
  restore() {
    for (const row of this.rows) row.cards.forEach(card => {
      const r = S.res[card.dataset.id];
      card._ev = true;
      card.classList.add(r.pass ? 'in' : 'out');
      card.querySelector('.st').textContent = r.pass ? 'FIT' : r.fail.stamp;
      if (S.picks.some(p => p.l.id === card.dataset.id)) card.classList.add('best');
    });
  },
  reset() {
    for (const row of this.rows) row.cards.forEach(card => {
      card._ev = false;
      card.classList.remove('in', 'out', 'best', 'lifted');
      card.querySelector('.st').textContent = '';
    });
  },
  markBest(ids) { for (const row of this.rows) row.cards.forEach(c => ids.includes(c.dataset.id) && c.classList.add('best')); },
  lift(id) {
    const vw = innerWidth, vh = innerHeight;
    let best = null, bd = Infinity;
    for (const row of this.rows) for (const card of row.cards) {
      if (card.dataset.id !== id) continue;
      const r = card.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const on = cx > 40 && cx < vw - 40 && cy > 40 && cy < vh - 40;
      const d = Math.hypot(cx - vw * 0.42, cy - vh * 0.5) + (on ? 0 : 1e5);
      if (d < bd) { bd = d; best = card; }
    }
    return best;
  },
  scatter(p) {
    const mid = (this.rows.length - 1) / 2;
    for (const row of this.rows) row.el.style.setProperty('--sy', `${((row.ri - mid) * p * 34).toFixed(1)}px`);
  },
};

function wallCardHTML(l) {
  return `<div class="lc" data-id="${l.id}"><div class="cv">${planUse(l.id)}<i class="st"></i></div>` +
    `<div class="pr">$${l.rent}<small>/WK</small></div><div class="sb">${l.bed} BD · ${l.bath} BA · ${l.suburb}</div></div>`;
}

/* ======================================================================
   Grid, HUD, smooth scroll
   ====================================================================== */
function buildGrid() {
  const g = $('#grid');
  let h = '';
  for (const x of [25, 50, 75]) h += `<i class="gl" style="left:${x}%;top:0;bottom:0;width:1px"></i>`;
  for (const y of [33.333, 66.666]) h += `<i class="gl" style="top:${y}%;left:0;right:0;height:1px"></i>`;
  for (const x of [25, 50, 75]) for (const y of [33.333, 66.666]) h += `<i class="gx" style="left:${x}%;top:${y}%"></i>`;
  g.innerHTML = h;
}

function tickClock() {
  const t = new Intl.DateTimeFormat('en-AU', { timeZone: 'Australia/Sydney', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date());
  $('#clock').textContent = `SYD ${t}`;
}

const SM = { cur: 0, target: 0, active: false };
const maxScroll = () => document.documentElement.scrollHeight - innerHeight;
function smoothTo(y) {
  if (!SM.active) SM.cur = scrollY;
  SM.target = clamp(y, 0, maxScroll());
  SM.active = true;
}

function canScrollInside(el, dy) {
  const box = el && el.closest('#detail');
  if (!box || box.scrollHeight <= box.clientHeight + 2) return false;
  return dy > 0 ? box.scrollTop + box.clientHeight < box.scrollHeight - 1 : box.scrollTop > 0;
}

let swipeX = 0, swipeT = 0;
addEventListener('wheel', e => {
  if (e.ctrlKey) return;
  if (canScrollInside(e.target, e.deltaY)) return;
  e.preventDefault();
  if (S.phase !== 'tour') return;
  const now = performance.now();
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY) * 1.4 && scrollY < tourEnd()) {
    swipeX += e.deltaX;
    if (Math.abs(swipeX) > 70 && now - swipeT > 450) { userTook(); goTo(S.focus + Math.sign(swipeX)); swipeX = 0; swipeT = now; }
    return;
  }
  const dy = e.deltaMode === 1 ? e.deltaY * 32 : e.deltaY;
  if (!SM.active) SM.cur = SM.target = scrollY;
  SM.target = clamp(SM.target + dy, 0, maxScroll());
  SM.active = true;
  S.lastWheel = now;
  userTook();
}, { passive: false });
addEventListener('touchmove', () => { if (S.phase === 'tour') userTook(); }, { passive: true });
addEventListener('scroll', () => { if (!SM.active) SM.cur = SM.target = scrollY; }, { passive: true });
addEventListener('keydown', e => {
  if (S.phase !== 'tour' || e.target.closest('input')) return;
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); userTook(); goTo(S.focus + (e.key === 'ArrowRight' ? 1 : -1)); }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === ' ' || e.key === 'PageDown' || e.key === 'PageUp') userTook();
});
addEventListener('mousemove', e => {
  $('#xy').innerHTML = `${String(Math.round(e.clientX)).padStart(4, '0')} X&nbsp;&nbsp;${String(Math.round(e.clientY)).padStart(4, '0')} Y`;
});

/* ======================================================================
   Story geometry: scroll position ↔ focused card
   ====================================================================== */
const STEP = 0.9;
const posFor = i => (i <= 0 ? 0 : innerHeight * (0.2 + i * STEP));
const tourEnd = () => posFor(Math.max(0, S.picks.length - 1)) + innerHeight * 0.2;
function storyHeight() { return innerHeight * (1 + 0.2 + Math.max(0, S.picks.length - 1) * STEP + 0.35); }
function goTo(i) {
  if (!S.picks.length) return;
  smoothTo(posFor(clamp(i, 0, S.picks.length - 1)));
}

/* ======================================================================
   Main loop
   ====================================================================== */
let lastT = performance.now();
function loop(now) {
  const dt = Math.min(0.05, (now - lastT) / 1000);
  lastT = now;
  if (SM.active) {
    const k = 1 - Math.pow(1 - 0.1, dt * 60);
    SM.cur += (SM.target - SM.cur) * k;
    if (Math.abs(SM.target - SM.cur) < 0.4) { SM.cur = SM.target; SM.active = false; }
    window.scrollTo(0, SM.cur);
  }
  Wall.tick(dt, now);
  if (S.phase === 'tour') tourFrame(now);
  requestAnimationFrame(loop);
}

function tourFrame(now) {
  const y = scrollY, vh = innerHeight, n = S.picks.length;
  S.f = clamp((y - vh * 0.2) / (vh * STEP), 0, n - 1);
  const fi = Math.round(S.f);
  if (fi !== S.focus) setFocus(fi);
  const p = clamp(y / (vh * 0.9), 0, 1);
  document.documentElement.style.setProperty('--wo', (1 - p * 0.55).toFixed(3));
  document.documentElement.style.setProperty('--ws', (1 + p * 0.1).toFixed(4));
  Wall.scatter(p);
  document.body.classList.toggle('hint', y < 20 && S.tourDone && n > 1);
  const leave = clamp((y - ($('#story').offsetHeight - vh)) / (vh * 0.45), 0, 1);
  $('.stage').style.opacity = (1 - leave).toFixed(3);
  document.body.classList.toggle('in-compare', y > $('#compare').offsetTop - vh * 0.6);
  // snap to the nearest card once the wheel goes quiet
  if (!SM.active && now - S.lastWheel > 240 && now - S.lastWheel < 2000 && y < tourEnd() - 4 && Math.abs(S.f - fi) > 0.02) smoothTo(posFor(fi));
  for (const c of S.cards) {
    if (c.flying || c.leaving) continue;
    c.slot += (c.target - c.slot) * (1 - Math.pow(0.0015, Math.min(0.05, 1 / 60)));
    const d = c.slot - S.f, ad = Math.abs(d);
    c.el.style.transform = cfTransform(d);
    c.el.style.opacity = ad <= 1.15 ? 1 : clamp(1 - (ad - 1.15) * 0.6, 0, 1).toFixed(3);
    c.el.style.zIndex = String(100 - Math.round(ad * 10));
    c.el.classList.toggle('focus', c.target === fi);
  }
}

const tf = (x, y, z, ry, rz, s) => `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,${z.toFixed(1)}px) rotateY(${ry.toFixed(2)}deg) rotateZ(${rz.toFixed(2)}deg) scale(${s.toFixed(4)})`;
function cfTransform(d) {
  const pw = S.pw, ad = Math.abs(d), sg = Math.sign(d);
  const x = sg * (Math.min(ad, 1) * pw * 0.68 + Math.max(0, ad - 1) * pw * 0.24);
  return tf(x, 0, -Math.min(ad, 2.5) * 170, -sg * Math.min(ad, 1) * 46, 0, 1);
}

/* ======================================================================
   Narration
   ====================================================================== */
let voice = null;
function pickVoice() {
  const vs = speechSynthesis.getVoices();
  voice = vs.find(v => /en-AU/i.test(v.lang) && /karen|natural|premium/i.test(v.name)) || vs.find(v => /en-AU/i.test(v.lang)) || vs.find(v => /^en/i.test(v.lang)) || null;
}
function speak(text) {
  return new Promise(res => {
    if (!S.sound || !('speechSynthesis' in window)) return res();
    const u = new SpeechSynthesisUtterance(text.replace(/≤/g, 'under'));
    if (voice) u.voice = voice;
    u.rate = 1.05;
    u.onend = u.onerror = () => res();
    speechSynthesis.speak(u);
  });
}

function setText(text) {
  const words = text.split(/\s+/).filter(Boolean);
  $('#aiText').innerHTML = words.map((w, i) => `<span class="w" style="animation-delay:${Math.min(i * 34, 1000)}ms">${esc(w)}</span>`).join(' ');
  return words.length;
}

async function say(text, tok) {
  if (tok !== S.token) return;
  const n = setText(text);
  S.speaking = true;
  document.body.classList.add('speaking');
  document.body.classList.remove('thinking');
  const dur = 450 + n * 235;
  if (S.sound && 'speechSynthesis' in window) await Promise.race([speak(text), sleep(dur + 9000)]);
  else await sleep(dur);
  if (tok === S.token) { S.speaking = false; document.body.classList.remove('speaking'); }
}

function cancel() {
  S.token++;
  S.auto = false;
  S.speaking = false;
  document.body.classList.remove('speaking', 'thinking');
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  hot(null);
}

function userTook() { if (S.auto) { cancel(); S.tourDone = true; } }

function hot(keys) {
  $$('#detail .hot').forEach(e => e.classList.remove('hot'));
  if (!keys) return;
  for (const k of [].concat(keys)) {
    const el = k.startsWith('cell:') ? $(`#detail [data-cell="${k.slice(5)}"]`) : $(`#detail [data-hot="${k}"]`);
    if (el) el.classList.add('hot');
  }
}

/* ======================================================================
   Needs chips
   ====================================================================== */
function chipValue(d) {
  const n = S.needs;
  if (d === 'A1') return n.A1 ? `$${n.A1}/WK` : null;
  if (d === 'B1') return n.B1 ? `${n.B1} BED` : null;
  if (d === 'G1') return n.G1 ? `${HUBS[n.G1.hub].chip} ≤${n.G1.limit}′` : null;
  if (d === 'A4') return n.A4 ? n.A4.label : null;
  if (d === 'J1') return n.J1 ? (n.J1 === 'none' ? 'NO PETS' : n.J1.replace(/^a /, '').toUpperCase()) : null;
  return null;
}

function renderChips(changed = []) {
  const box = $('#needs');
  let h = REQUIRED.map(d => {
    const v = chipValue(d);
    const cls = ['chip', v ? '' : 'empty', S.asked.includes(d) && !v ? 'asking' : '', S.assumed.has(d) ? 'assumed' : '', changed.includes(d) ? 'fresh' : ''].join(' ');
    return `<span class="${cls}" data-d="${d}">${ICON[d]}<span>${v || (S.asked.includes(d) ? KEYLABEL[d] + ' ?' : KEYLABEL[d] + ' ·')}</span></span>`;
  }).join('');
  h += S.needs.soft.map(d => `<span class="chip soft ${changed.includes(d) ? 'fresh' : ''}" data-d="${d}">${ICON.plus}<span>${SOFT[d].chip}</span></span>`).join('');
  box.innerHTML = h;
}

/* ======================================================================
   Conversation flow
   ====================================================================== */
function showYou(text) { $('#you').innerHTML = `<b>YOU</b>${esc(text)}`; }

async function handleInput(text) {
  text = text.trim();
  if (!text) return;
  if (/^(start over|reset|restart|重新开始)$/i.test(text)) { location.hash = ''; location.reload(); return; }
  if (S.phase === 'search') return;
  cancel();
  const tok = S.token;
  showYou(text);
  document.body.classList.add('has-asked');
  if (S.phase === 'tour') return followUp(text, tok);

  const { needs, changed } = parseNeeds(text, S.needs, S.asked);
  S.needs = needs;
  changed.forEach(d => S.assumed.delete(d));
  S.asked = S.asked.filter(d => !needs[d]);
  renderChips(changed);
  const missing = REQUIRED.filter(d => needs[d] == null);
  if (!changed.length && S.rounds === 0) {
    S.phase = 'asking';
    await say("Tell me what matters: your weekly budget, bedrooms, where you need to get to, when you move in, and any pets.", tok);
    return;
  }
  if (missing.length && S.rounds < 2) {
    S.rounds++;
    S.asked = missing.slice(0, 2);
    S.phase = 'asking';
    renderChips(changed);
    const qs = S.asked.map(d => ASKQ[d]);
    const lead = S.rounds === 1 ? 'Got it.' : 'Thanks.';
    const ask = qs.length > 1
      ? `${lead} Two quick things before I search: ${qs[0]}, and ${qs[1]}?`
      : `${lead} One quick thing before I search: ${qs[0]}?`;
    await say(ask[0].toUpperCase() + ask.slice(1), tok);
    return;
  }
  const notes = [];
  for (const d of missing) {
    S.assumed.add(d);
    if (d === 'A1') notes.push("I'll search without a budget cap.");
    if (d === 'B1') { S.needs.B1 = 1; notes.push("I'll assume one bedroom is enough."); }
    if (d === 'G1') { S.needs.G1 = { hub: 'central', limit: 30 }; notes.push("I'll keep it within 30 minutes of Central."); }
    if (d === 'A4') notes.push("I'll ignore move-in dates for now.");
    if (d === 'J1') { S.needs.J1 = 'none'; notes.push("I'll assume no pets."); }
  }
  if (!notes.length && !S.needs.soft.includes('C2')) notes.push("I'll assume unfurnished is fine.");
  S.asked = [];
  renderChips();
  await runSearch(tok, notes);
}

async function runSearch(tok, notes = []) {
  S.phase = 'search';
  S.tourDone = false;
  Wall.reset();
  $('#ask').classList.add('busy');
  document.body.classList.add('is-searching', 'thinking');
  runChecks();
  say(`Thanks, searching now. ${notes.join(' ')} Six sources, fifty listings.`.replace(/\s+/g, ' '), tok);
  Wall.target = 0.12;
  $('#tChecked').textContent = '0';
  $('#tFit').textContent = '0';
  $('#tBest').innerHTML = '&ndash;';
  $('#reasons').innerHTML = '';
  runSources();
  await sleep(RM ? 0 : 750);
  let checked = 0, fit = 0;
  await Wall.scan(RM ? 10 : 2700, r => {
    checked++; if (r.pass) fit++;
    $('#tChecked').textContent = checked;
    $('#tFit').textContent = fit;
  });
  $('#tChecked').textContent = LISTINGS.length;
  $('#tFit').textContent = S.fits.length;
  const counts = {};
  for (const r of Object.values(S.res)) if (!r.pass) counts[r.fail.d] = (counts[r.fail.d] || 0) + 1;
  $('#reasons').innerHTML = Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([d, c], i) => `<span style="animation-delay:${i * 90}ms"><b>${c}</b>${FAILW[d].toUpperCase()}</span>`).join('');
  await sleep(500);
  if (tok !== S.token) return;
  if (!S.fits.length) return noFit(tok, counts);
  Wall.markBest(S.picks.map(p => p.l.id));
  $('#tBest').textContent = S.picks.length;
  await sleep(RM ? 0 : 1100);
  if (tok !== S.token) return;
  enterTour();
  await flyOut();
  if (tok !== S.token) return;
  tour(tok);
}

const srcTimers = [];
function runSources() {
  srcTimers.splice(0).forEach(clearTimeout);
  const ul = $('#sources');
  ul.innerHTML = '';
  let done = 0;
  $('#srcCount').textContent = `0 / ${SOURCES.length}`;
  SOURCES.forEach((s, i) => {
    srcTimers.push(setTimeout(() => {
      const li = document.createElement('li');
      const ms = 180 + Math.round(Math.random() * 1300);
      li.innerHTML = `<i class="ic"></i><span>${s.label}</span><em>${s.rows}</em>`;
      ul.appendChild(li);
      srcTimers.push(setTimeout(() => {
        li.classList.add('done');
        li.querySelector('em').textContent = `${s.rows} · ${ms}MS`;
        $('#srcCount').textContent = `${++done} / ${SOURCES.length}`;
      }, ms + 300));
    }, i * 120));
  });
}

async function noFit(tok, counts) {
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const stretch = { A1: 'budget', B1: 'bedrooms', G1: 'travel time', A4: 'move-in date' }[top[0]];
  document.body.classList.remove('is-searching');
  $('#ask').classList.remove('busy');
  S.phase = 'idle';
  S.rounds = 2;
  Wall.target = 0.6;
  await say(`Nothing in the fifty fits all of that. Most miss on ${FAILW[top[0]]}. Want to stretch the ${stretch}?`, tok);
  setTimeout(() => { if (S.phase === 'idle') Wall.reset(); }, 6000);
}

/* ======================================================================
   Front cards
   ====================================================================== */
function pickCardHTML(p, i) {
  const L = p.l;
  return `<div class="cv">${planUse(L.id)}<span class="rk">${pad(i + 1)}</span></div>` +
    `<div class="pr">$${L.rent}<small>/WEEK</small></div>` +
    `<div class="ad">${esc(L.unit)}/${esc(L.street)} · ${L.suburb}</div>` +
    `<div class="dots">${p.cells.map(c => `<i class="dot ${c.s}" title="${esc(c.label)}"></i>`).join('')}</div>`;
}

async function flyOut() {
  const flow = $('#flow');
  flow.innerHTML = '';
  S.pw = probe('--pw');
  S.cards = S.picks.map((p, i) => {
    const el = document.createElement('div');
    el.className = 'pk';
    el.innerHTML = pickCardHTML(p, i);
    el.addEventListener('click', () => { userTook(); goTo(S.cards.find(c => c.el === el).target); });
    flow.appendChild(el);
    el.style.marginTop = `${-el.offsetHeight / 2}px`;
    return { el, p, slot: i, target: i, flying: true };
  });
  const fr = flow.getBoundingClientRect();
  const fcx = fr.left + fr.width / 2, fcy = fr.top + fr.height / 2;
  const stagger = 170, dur = RM ? 1 : 1200;
  S.cards.forEach((c, i) => {
    const src = Wall.lift(c.p.l.id);
    const to = cfTransform(i);
    c.el.style.transform = to;
    c.el.style.zIndex = String(100 - i * 10);
    if (!src) { c.flying = false; return; }
    const r = src.getBoundingClientRect();
    const s0 = src.offsetWidth / S.pw;
    const from = tf(r.left + r.width / 2 - fcx, r.top + r.height / 2 - fcy, 0, 0, -7, s0);
    setTimeout(() => src.classList.add('lifted'), i * stagger);
    const a = c.el.animate([{ transform: from, opacity: 0.6 }, { transform: from, opacity: 1, offset: 0.06 }, { transform: to, opacity: 1 }],
      { duration: dur, delay: i * stagger, easing: EASE, fill: 'backwards' });
    a.finished.then(() => { c.flying = false; });
  });
  await sleep(dur + S.cards.length * stagger);
}

function enterTour() {
  S.phase = 'tour';
  document.body.classList.remove('is-searching', 'thinking');
  document.body.classList.add('is-tour', 'has-results');
  $('#ask').classList.remove('busy');
  Wall.target = 0.25;
  moveFlip($('#needs'), $('#topNeeds'));
  moveFlip($('#ai'), $('#dock'));
  moveFlip($('#askWrap'), $('#dock'));
  $('#story').style.height = `${storyHeight()}px`;
  $('#rail').innerHTML = S.picks.map((p, i) => `<button data-i="${i}"><span>${pad(i + 1)}</span><i></i></button>`).join('');
  $$('#rail button').forEach(b => b.addEventListener('click', () => { userTook(); goTo(+b.dataset.i); }));
  $$('.hud.tr [data-go]').forEach(b => { b.disabled = false; });
  buildCompare();
  S.focus = -1;
}

function exitTour() {
  S.phase = 'idle';
  document.body.classList.remove('is-tour', 'has-results', 'hint');
  moveFlip($('#needs'), $('#needsSlot'));
  moveFlip($('#ai'), $('#aiSlot'));
  moveFlip($('#askWrap'), $('#askSlot'));
  $('#story').style.height = '';
  $('.stage').style.opacity = '';
  document.body.classList.remove('in-compare');
  $('#flow').innerHTML = '';
  $('#detail').innerHTML = '';
  S.cards = [];
  document.documentElement.style.setProperty('--wo', 1);
  document.documentElement.style.setProperty('--ws', 1);
  Wall.scatter(0);
  $$('.hud.tr [data-go="picks"], .hud.tr [data-go="compare"]').forEach(b => { b.disabled = true; });
}

function moveFlip(el, parent) {
  const a = el.getBoundingClientRect();
  parent.appendChild(el);
  const b = el.getBoundingClientRect();
  if (RM) return;
  el.animate([{ transform: `translate(${a.left - b.left}px,${a.top - b.top}px)`, opacity: 0.4 }, { transform: 'none', opacity: 1 }], { duration: 950, easing: EASE });
}

/* ======================================================================
   Detail panel
   ====================================================================== */
function statusCounts(cells) {
  const c = { supported: 0, inferred: 0, conflict: 0, unknown: 0 };
  cells.forEach(x => c[x.s]++);
  return [['supported', 'CONFIRMED'], ['inferred', 'INFERRED'], ['conflict', 'CONFLICT'], ['unknown', 'UNKNOWN']]
    .filter(([k]) => c[k]).map(([k, w]) => `${c[k]} ${w}`).join(' · ');
}

function standOut(p) {
  const fits = S.fits, k = fits.length, L = p.l;
  for (const d of S.needs.soft) {
    const mine = p.cells.find(c => c.d === d);
    if (mine && mine.s === 'supported' && fits.filter(f => f.cells.find(c => c.d === d && c.s === 'supported')).length === 1) {
      return { text: `The only one of the ${k} where ${mine.proof || SOFT[d].phrase + ' is confirmed'}.`, cell: d };
    }
  }
  if (k > 1 && L.rent === Math.min(...fits.map(f => f.l.rent))) {
    return { text: S.needs.A1 ? `Cheapest of the ${k}: $${S.needs.A1 - L.rent} a week under your budget.` : `Cheapest of the ${k}.`, cell: 'A1' };
  }
  if (S.needs.G1 && k > 1) {
    const h = S.needs.G1.hub;
    if (L.commute[h].min === Math.min(...fits.map(f => f.l.commute[h].min))) {
      return { text: `Shortest trip of the ${k}: ${L.commute[h].min} minutes to ${HUBS[h].label} by ${L.commute[h].mode}.`, cell: 'G1' };
    }
  }
  const conf = p.cells.filter(c => c.s === 'supported').length;
  if (k > 1 && conf === Math.max(...fits.map(f => f.cells.filter(c => c.s === 'supported').length))) {
    return { text: `Most checks backed by documents: ${conf} of ${p.cells.length}.`, cell: null };
  }
  if (L.special) return { text: L.special, cell: null };
  const med = MEDIAN[L.suburb][Math.min(L.bed, 3) - 1];
  return { text: med >= L.rent ? `Rent sits $${med - L.rent} under the ${L.suburb} median for a ${L.bed}-bed.` : `Level ${L.floor}, free from ${fmtSpoken(L.avail)}.`, cell: null };
}

function weakest(p) {
  // hard needs first: an unconfirmed must-have matters more than a known gap in a nice-to-have
  const rank = { conflict: 3, unknown: 2, inferred: 1, supported: 0 };
  let best = null;
  for (const c of p.cells) {
    const sc = (c.hard ? 100 : 0) + rank[c.s] * 10;
    if (rank[c.s] > 0 && (!best || sc > best.sc)) best = { c, sc };
  }
  return best && best.c;
}

function questionFor(p) {
  const c = weakest(p);
  const pet = S.needs.J1;
  if (!c) return { text: 'Has there been serious violent crime at the property in the last five years? They must tell you if so.', cell: null };
  if (c.d === 'J1') {
    if (c.s === 'conflict' && c.src === 'AGENT') return { text: `On what ground is ${pet} refused? In NSW a landlord can only say no on set grounds.`, cell: 'J1' };
    if (c.s === 'conflict') return { text: `The listing says no pets. Would the landlord consider ${pet}? In NSW a refusal needs set grounds.`, cell: 'J1' };
    return { text: `Can you confirm ${pet} is OK here? A yes makes this a confirmed fit.`, cell: 'J1' };
  }
  if (c.d === 'A4') return { text: `Could the lease start closer to ${fmtSpoken(S.needs.A4.date)}?`, cell: 'A4' };
  if (SOFT[c.d]) return { text: SOFT[c.d].q, cell: c.d };
  return { text: 'Is there anything the listing leaves out that I should know before applying?', cell: null };
}

function detailHTML(p, i) {
  const L = p.l, n = S.picks.length;
  const med = MEDIAN[L.suburb][Math.min(L.bed, 3) - 1], dm = L.rent - med;
  const hub = (S.needs.G1 && S.needs.G1.hub) || 'central';
  const c = L.commute[hub];
  const so = standOut(p), q = questionFor(p);
  const log = S.log.filter(e => e.id === L.id);
  return `
    <div class="d-top" style="--d:0"><span class="tag lime">${pad(i + 1)} / ${pad(n)}</span><span class="tag">${i === 0 ? 'BEST FIT' : 'FITS'}</span><span class="d-id">${L.id}</span></div>
    <h2 class="d-addr" style="--d:1">${esc(L.unit)}/${esc(L.street)}</h2>
    <div class="d-sub" style="--d:2">${L.suburb} ${L.postcode} · level ${L.floor}</div>
    <div class="d-keys" data-hot="keys" style="--d:3">
      <div><b>$${L.rent}</b><span>per week<br><em class="${dm <= 0 ? 'under' : 'over'}">$${Math.abs(dm)} ${dm <= 0 ? 'under' : 'over'} median</em></span></div>
      <div><b>${L.bed}·${L.bath}·${L.car}</b><span>bed · bath<br>· car</span></div>
      <div><b>${c.min} min</b><span>to ${HUBS[hub].chip}<br>${c.mode}</span></div>
      <div><b>${fmtShort(L.avail)}</b><span>free<br>from</span></div>
    </div>
    <div class="d-h" style="--d:4"><span>WHY IT FITS</span><span class="d-count">${statusCounts(p.cells)}</span></div>
    <div class="d-cells">${p.cells.map((x, k) => cellHTML(x, 5 + k)).join('')}</div>
    <div class="d-h" style="--d:12"><span>STANDS OUT</span></div>
    <p class="d-stand" data-hot="stand" style="--d:13"><span>${esc(so.text)}</span></p>
    <div class="d-h" style="--d:14"><span>ASK THE AGENT</span></div>
    <div class="d-ask" data-hot="ask" style="--d:15"><p>${esc(q.text)}</p><button type="button" data-copy="${esc(q.text)}">COPY</button></div>
    ${log.length ? `<div class="d-log" style="--d:16">${log.map(e => `<div><span>${esc(e.label)}</span><i class="dot ${e.from}"></i><span class="arr">→</span><i class="dot ${e.to}"></i><span>${e.to}</span>${e.rr ? `<span class="rr">${e.rr}</span>` : ''}</div>`).join('')}</div>` : ''}`;
}

function cellHTML(c, d) {
  return `<div class="cell ${c.s}" data-cell="${c.d}" style="--d:${d}">` +
    `<i class="dot ${c.s}"></i><span class="lab">${esc(c.label)}</span><span class="val">${esc(c.v)}</span><span class="src">${c.src}</span>` +
    `<div class="ev"><q>${esc(c.q)}</q>${c.why ? `<span class="why">${esc(c.why)}</span>` : ''}<code>${c.tb} › ${esc(c.row)} › ${reqId(c)}</code></div></div>`;
}

let focusSeq = 0;
function setFocus(i, instant = false) {
  S.focus = i;
  const seq = ++focusSeq;
  $$('#rail button').forEach((b, k) => b.classList.toggle('on', k === i));
  const box = $('#detail');
  const nu = document.createElement('div');
  nu.className = 'd-inner enter';
  nu.innerHTML = detailHTML(S.picks[i], i);
  const old = box.querySelector('.d-inner');
  if (!old || instant || RM) { box.replaceChildren(nu); return; }
  old.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(-10px)' }], { duration: 170, easing: 'ease-in', fill: 'forwards' })
    .finished.then(() => { if (seq === focusSeq) { box.replaceChildren(nu); box.scrollTop = 0; } });
}

$('#detail').addEventListener('click', e => {
  const cp = e.target.closest('[data-copy]');
  if (cp) {
    navigator.clipboard && navigator.clipboard.writeText(cp.dataset.copy).catch(() => {});
    cp.textContent = 'COPIED';
    setTimeout(() => { cp.textContent = 'COPY'; }, 1400);
    return;
  }
  const cell = e.target.closest('.cell');
  if (cell) cell.classList.toggle('open');
});

/* ======================================================================
   Guided walkthrough
   ====================================================================== */
function pickLines(p, i) {
  const L = p.l, n = S.picks.length;
  const ord = i === 0 ? 'First' : i === n - 1 ? 'Last' : 'Next';
  const hub = S.needs.G1 && S.needs.G1.hub;
  const trip = hub ? `, ${L.commute[hub].min} minutes to ${HUBS[hub].label} by ${L.commute[hub].mode}` : '';
  const lines = [{ text: `${ord}: ${L.street}, ${L.suburb}. $${L.rent} a week, ${numWord(L.bed)} bed, ${numWord(L.bath)} bath${trip}.`, hot: 'keys' }];
  const so = standOut(p);
  lines.push({ text: so.text, hot: so.cell ? ['stand', 'cell:' + so.cell] : 'stand' });
  const q = questionFor(p);
  const w = weakest(p);
  if (w && w.s !== 'supported') {
    const lower = q.text[0].toLowerCase() + q.text.slice(1);
    lines.push({ text: `Worth asking the agent: ${lower}`, hot: q.cell ? ['ask', 'cell:' + q.cell] : 'ask' });
  } else {
    lines.push({ text: 'Every check here is backed by a document.', hot: 'ask' });
  }
  return lines;
}

async function waitFocus(i, ms = 2500) {
  const t0 = performance.now();
  while (S.focus !== i && performance.now() - t0 < ms) await sleep(60);
  await sleep(260);
}

async function tour(tok) {
  S.auto = true;
  const n = S.picks.length;
  await say(`Out of fifty, ${numWord(S.fits.length)} fit. ${n === 1 ? "Here's the one" : `Here are the ${numWord(n)}`} I'd look at first.`, tok);
  for (let i = 0; i < n; i++) {
    if (tok !== S.token || !S.auto) return;
    if (i > 0) { goTo(i); await waitFocus(i); }
    for (const ln of pickLines(S.picks[i], i)) {
      if (tok !== S.token || !S.auto) return;
      hot(ln.hot);
      await say(ln.text, tok);
    }
    hot(null);
  }
  if (tok !== S.token || !S.auto) return;
  await say(`That's my ${numWord(n)}. Scroll down for the side by side, or tell me what to change.`, tok);
  S.auto = false;
  S.tourDone = true;
}

/* ======================================================================
   Follow-ups during the walkthrough
   ====================================================================== */
function pickRef(t) {
  const byName = S.picks.findIndex(p => t.includes(p.l.street.toLowerCase().replace(/^\d+\s+/, '').split(' ')[0]));
  if (byName >= 0) return byName;
  const o = ['first', 'second', 'third', 'last'].findIndex(w => new RegExp(`\\b${w}\\b`).test(t));
  if (o >= 0) return o === 3 ? S.picks.length - 1 : Math.min(o, S.picks.length - 1);
  return Math.max(0, S.focus);
}

async function followUp(text, tok) {
  const t = text.toLowerCase();
  if (/\bagent\b|\breplied\b|\breply\b|\bsays\b|\bsaid\b|中介/.test(t)) return agentReply(text, tok);
  const { needs, changed } = parseNeeds(text, S.needs, []);
  if (changed.length) {
    S.needs = needs;
    renderChips(changed);
    return rerun(tok);
  }
  if (/close|far|station|commute|how long|minutes|通勤|多远/.test(t)) {
    const i = pickRef(t), L = S.picks[i].l, hub = (S.needs.G1 && S.needs.G1.hub) || 'central';
    if (i !== S.focus) { goTo(i); await waitFocus(i); }
    hot('cell:G1');
    await say(`${L.street} is ${L.commute[hub].min} minutes to ${HUBS[hub].label} by ${L.commute[hub].mode}, from the AM-peak transit table.`, tok);
    return;
  }
  if (/\bnext\b|\bskip\b|下一/.test(t)) { goTo(S.focus + 1); return; }
  if (/\bback\b|previous|上一/.test(t)) { goTo(S.focus - 1); return; }
  if (/\bstop\b|\bpause\b|停/.test(t)) { await say('Stopped. Scroll when you are ready.', tok); return; }
  if (/compare|side by side|对比/.test(t)) { smoothTo($('#compare').offsetTop); return; }
  await say("I can change what we're looking for, answer a question about one of these, or take an agent's reply.", tok);
}

async function agentReply(text, tok) {
  const t = text.toLowerCase();
  const i = pickRef(t);
  const p = S.picks[i], L = p.l;
  const d = /air ?con|\bac\b|split|ducted|cooling|空调/.test(t) ? 'C1' : /\bcat\b|\bdog\b|\bpets?\b|animal|宠物|猫|狗/.test(t) ? 'J1' : null;
  if (!d) { await say(`Noted for ${L.street}. I couldn't tell which check that answers, so nothing changed.`, tok); return; }
  if (i !== S.focus) { goTo(i); await waitFocus(i); }
  const neg = /\bonly\b|\bnot\b|\bno\b|isn'?t|aren'?t|doesn'?t|can'?t|won'?t|wouldn'?t|sorry|living room|refus|不/.test(t);
  const prevCell = p.cells.find(c => c.d === d);
  const from = prevCell ? prevCell.s : L.f[d].s;
  const to = neg ? 'conflict' : 'supported';
  const quote = text.replace(/^.*?(says?|replied|said)[:,]?\s*/i, '');
  L.f[d] = F(to, d === 'C1' ? (neg ? 'living room only' : 'agent confirms bedrooms') : (neg ? 'agent says no' : 'agent says yes'),
    'AGENT', 'agent_replies', `Agent reply: "${quote}"`, neg ? 'The agent says it does not meet this.' : 'The agent confirms it.', neg ? '' : 'the agent confirms it');
  const label = d === 'C1' ? 'Bedroom AC' : petLabel(S.needs.J1 || 'a pet');
  // 1. same order, new verdict: the cell flips in place
  S.picks = S.picks.map(x => evaluate(x.l, S.needs));
  S.fits = S.fits.map(x => S.picks.find(y => y.l.id === x.l.id) || x);
  const entry = { id: L.id, label, from, to, rr: '' };
  S.log.push(entry);
  refreshCards();
  setFocus(i, true);
  const cell = $(`#detail [data-cell="${d}"]`);
  if (cell) cell.classList.add('flip');
  await say(`Noted. For ${L.street}, ${d === 'C1' ? 'bedroom air con' : 'the ' + label.toLowerCase()} goes from ${from} to ${to}.`, tok);
  if (tok !== S.token) return;
  // 2. re-rank: cards slide to their new slots and the view follows this listing
  S.picks.sort((a, b) => b.score - a.score || a.l.rent - b.l.rent);
  const newIdx = S.picks.findIndex(x => x.l.id === L.id);
  if (newIdx !== i) entry.rr = `#${i + 1} → #${newIdx + 1}`;
  refreshCards();
  buildCompare();
  const card = S.cards.find(c => c.p.l.id === L.id);
  card.el.classList.remove('bump'); void card.el.offsetWidth; card.el.classList.add('bump');
  if (newIdx !== i) { goTo(newIdx); await waitFocus(newIdx); } else setFocus(i, true);
  await say(newIdx !== i ? `That moves it from ${ORD[i]} to ${ORD[newIdx]}.` : `It stays ${ORD[i]}.`, tok);
  S.agentDone = true;
}

function refreshCards() {
  for (const c of S.cards) {
    const k = S.picks.findIndex(x => x.l.id === c.p.l.id);
    c.p = S.picks[k];
    c.target = k;
    c.el.querySelector('.rk').textContent = pad(k + 1);
    c.el.querySelector('.dots').innerHTML = c.p.cells.map(x => `<i class="dot ${x.s}" title="${esc(x.label)}"></i>`).join('');
  }
}

async function rerun(tok) {
  for (const c of S.cards) {
    c.leaving = true;
    c.el.animate([{ opacity: 1 }, { opacity: 0, transform: c.el.style.transform + ' translateY(60px) scale(.7)' }], { duration: 520, easing: EASE, fill: 'forwards' });
  }
  smoothTo(0);
  await sleep(600);
  if (tok !== S.token) return;
  exitTour();
  Wall.reset();
  Wall.target = 1;
  S.log = [];
  await sleep(400);
  if (tok !== S.token) return;
  await runSearch(tok, ['Updating the search.']);
}

/* ======================================================================
   Compare section
   ====================================================================== */
function buildCompare() {
  const dims = S.picks[0].cells.map(c => ({ d: c.d, label: c.label }));
  const rows = [...S.picks.map((p, i) => ({ p, tag: pad(i + 1), miss: false })), ...S.misses.map(p => ({ p, tag: 'MISS', miss: true }))];
  const n = S.picks.length;
  const head = `${numWord(n)} that fit,`.split(' ');
  const head2 = 'checked line by line.'.split(' ');
  $('#compare').innerHTML = `
    <div class="c-tag"><span class="tag lime">SIDE BY SIDE</span><span>${LISTINGS.length} LISTINGS · ${SOURCES.length} SOURCES · ${S.fits.length} FIT · ${n} SHOWN</span></div>
    <h2 class="c-h reveal"><span class="ln">${head.map((w, i) => `<span class="w" style="transition-delay:${i * 70}ms">${esc(w)}</span>`).join(' ')}</span><span class="ln">${head2.map((w, i) => `<span class="w" style="transition-delay:${150 + i * 70}ms">${esc(w)}</span>`).join(' ')}</span></h2>
    <div class="c-wrap"><table class="cmp reveal">
      <thead><tr><th>Listing</th><th>Rent</th>${dims.map(d => `<th>${esc(d.label)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r, k) => `<tr class="${r.miss ? 'miss' : ''}" style="--i:${k}">
        <td><div class="who"><span class="tag ${r.miss ? '' : 'lime'}">${r.tag}</span><div><b>${esc(r.p.l.street)}</b><small>${r.p.l.suburb}${r.miss ? ' · ' + FAILW[r.p.fail.d] : ''}</small></div></div></td>
        <td class="rent">$${r.p.l.rent}</td>
        ${dims.map(d => { const c = r.p.cells.find(x => x.d === d.d); return `<td>${c ? `<span class="cvl${c.v.length <= 22 ? ' nw' : ''}"><i class="dot ${c.s}"></i>${esc(c.v)}</span>` : ''}</td>`; }).join('')}
      </tr>`).join('')}</tbody></table></div>
    <div class="legend">
      <span><i class="dot supported"></i><b>Supported</b>a document says so</span>
      <span><i class="dot inferred"></i><b>Inferred</b>follows from documents, not stated</span>
      <span><i class="dot conflict"></i><b>Conflict</b>documents say no, or disagree</span>
      <span><i class="dot unknown"></i><b>Unknown</b>nothing on file yet</span>
    </div>
    <div class="c-qs reveal">${S.picks.map((p, i) => `<div class="c-q" style="--i:${i}"><span class="tag lime">${pad(i + 1)} · ASK</span><p>${esc(questionFor(p).text)}</p><small>${esc(p.l.street)}, ${p.l.suburb}</small></div>`).join('')}</div>
    <div class="c-foot"><span>Mock data · fictional streets, real suburbs · no demographics</span><button class="pill" id="restart">START OVER</button></div>`;
  $('#restart').addEventListener('click', () => { location.hash = ''; location.reload(); });
  $$('#compare .reveal').forEach(el => io.observe(el));
}

const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: 0.18 });

/* ======================================================================
   Input, mic, sound, demo
   ====================================================================== */
$('#ask').addEventListener('submit', e => {
  e.preventDefault();
  const q = $('#q');
  const v = q.value;
  q.value = '';
  handleInput(v);
});

const SUGGEST = [
  "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom",
  'A quiet one-bed near UNSW under $700, early December, no pets',
];
$('#suggest').innerHTML = SUGGEST.map(s => `<button type="button">${esc(s)}</button>`).join('');
$$('#suggest button').forEach((b, i) => b.addEventListener('click', () => handleInput(SUGGEST[i])));

const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Rec) {
  const mic = $('#micBtn');
  mic.hidden = false;
  let rec = null;
  mic.addEventListener('click', () => {
    if (rec) { rec.stop(); return; }
    rec = new Rec();
    rec.lang = 'en-AU';
    rec.interimResults = true;
    if (S.phase === 'search') return;
    mic.classList.add('on');
    cancel();
    rec.onresult = ev => {
      const r = ev.results[ev.results.length - 1];
      showYou(r[0].transcript);
      if (r.isFinal) handleInput(r[0].transcript);
    };
    rec.onend = rec.onerror = () => { mic.classList.remove('on'); rec = null; };
    rec.start();
  });
}

$('#soundBtn').addEventListener('click', () => {
  S.sound = !S.sound;
  $('#soundBtn').classList.toggle('on', S.sound);
  $('#soundBtn span').textContent = S.sound ? 'ON' : '/';
  if (S.sound && 'speechSynthesis' in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }
  if (!S.sound && 'speechSynthesis' in window) speechSynthesis.cancel();
});

$$('.hud.tr [data-go]').forEach(b => b.addEventListener('click', () => {
  userTook();
  const g = b.dataset.go;
  if (g === 'brief') smoothTo(0);
  if (g === 'picks') goTo(Math.max(0, S.focus));
  if (g === 'compare') smoothTo($('#compare').offsetTop);
}));

async function typeInto(text) {
  const q = $('#q');
  q.focus();
  q.value = '';
  for (const ch of text) { q.value += ch; await sleep(RM ? 0 : 22 + Math.random() * 26); }
  await sleep(300);
}
const submitTyped = () => { const q = $('#q'); const v = q.value; q.value = ''; handleInput(v); };
async function waitFor(fn, ms) { const t0 = performance.now(); while (!fn() && performance.now() - t0 < ms) await sleep(120); }

async function demo() {
  if (S.demo) return;
  if (S.phase !== 'idle' || S.rounds || S.needs.A1 || S.needs.B1) { location.hash = 'demo'; location.reload(); return; }
  S.demo = true;
  $('#demoBtn').classList.add('on');
  await typeInto(SUGGEST[0] + '.');
  submitTyped();
  await waitFor(() => S.phase === 'asking' && !S.speaking, 15000);
  await sleep(800);
  await typeInto('Under 900, mid-November.');
  submitTyped();
  await waitFor(() => S.phase === 'tour' && S.tourDone && !S.speaking, 120000);
  const k = S.picks.findIndex(p => p.l.id === 'L-0001');
  if (S.phase === 'tour' && k >= 0) {
    await sleep(900);
    goTo(k);
    await sleep(1400);
    await typeInto("Agent for Alder Lane says: sorry, the owner won't take a cat.");
    submitTyped();
  }
  S.demo = false;
  $('#demoBtn').classList.remove('on');
}
$('#demoBtn').addEventListener('click', demo);

/* ======================================================================
   Boot
   ====================================================================== */
let resizeT = 0;
addEventListener('resize', () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => {
    S.pw = probe('--pw');
    if (S.phase !== 'search') Wall.build();
    if (S.phase === 'tour') {
      $('#story').style.height = `${storyHeight()}px`;
      S.cards.forEach(c => { c.el.style.marginTop = `${-c.el.offsetHeight / 2}px`; });
    }
  }, 220);
});

function boot() {
  buildSprite(LISTINGS);
  buildGrid();
  Wall.build();
  S.pw = probe('--pw');
  renderChips();
  tickClock();
  setInterval(tickClock, 15000);
  $$('#headline .w').forEach((w, i) => { w.style.transitionDelay = `${180 + i * 75}ms`; });
  requestAnimationFrame(loop);
  setTimeout(() => {
    document.body.classList.remove('is-loading');
    Wall.intro();
    setTimeout(() => document.body.classList.add('ready'), 250);
    setTimeout(() => setText('Tell me what you need, in your own words. I check every listing against it.'), 900);
    if (location.hash === '#demo') { history.replaceState(null, '', location.pathname); setTimeout(demo, 1600); }
  }, RM ? 0 : 950);
}
boot();
