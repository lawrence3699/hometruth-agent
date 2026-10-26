// Procedural floor plans: one <symbol> per listing, reused by every card copy through <use>.
// The plan is the card's "cover art"; rooms follow the bedroom and bathroom counts.
// Layout is computed on a 100-unit grid and written out ×10, because Chrome mis-scales
// SVG text with tiny font sizes inside 3D-transformed layers.

// living, kitchen, bedroom, bath, background
const PALETTES = [
  ['#E4EBDD', '#D3DEC8', '#C3D3B5', '#EEF1EA', '#F4F6F0'], // sage
  ['#F1E8D6', '#E6D8BB', '#DCC9A3', '#F5F0E6', '#FAF6EE'], // sand
  ['#DEE7EF', '#CCDAE6', '#B8CBDC', '#EEF2F6', '#F4F7FA'], // sky
  ['#F3E2DC', '#EBD0C7', '#E1BEB2', '#F7EEEA', '#FBF5F2'], // blush
  ['#E7E3EF', '#D9D2E6', '#C9C0DC', '#F1EEF5', '#F7F5FA'], // lilac
  ['#ECEAE3', '#DEDBD1', '#CFCBBE', '#F3F2EE', '#F8F7F3'], // stone
];
const K = 10;
const u = v => Math.round(v * K);
const LABEL = 'font-family="Menlo,monospace" text-anchor="middle" fill="rgba(17,17,17,.55)"';

function hashStr(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

function line(x1, y1, x2, y2, stroke, w) {
  return `<line x1="${u(x1)}" y1="${u(y1)}" x2="${u(x2)}" y2="${u(y2)}" stroke="${stroke}" stroke-width="${u(w)}"/>`;
}

function rect(o, fill, stroke = 'none', w = 0, extra = '') {
  return `<rect x="${u(o.x)}" y="${u(o.y)}" width="${u(o.w)}" height="${u(o.h)}" fill="${fill}"${stroke !== 'none' ? ` stroke="${stroke}" stroke-width="${u(w)}"` : ''}${extra}/>`;
}

function planSymbol(l) {
  const r = seeded(hashStr(l.id));
  const pal = PALETTES[l.tint % PALETTES.length];
  const X0 = 12, Y0 = 14, X1 = 88, Y1 = 86;
  const n = Math.max(1, Math.min(3, l.bed));
  const a = X0 + (X1 - X0) * (n === 1 ? 0.56 : 0.5) + (r() - 0.5) * 8;
  const b = Y0 + (Y1 - Y0) * 0.58 + (r() - 0.5) * 10;
  let rooms = [
    { x: X0, y: Y0, w: a - X0, h: b - Y0, t: 'LIVING', k: 0 },
    { x: X0, y: b, w: a - X0, h: Y1 - b, t: 'KITCHEN', k: 1 },
  ];
  const items = [];
  for (let i = 0; i < n; i++) items.push({ t: n === 1 ? 'BED' : `BED ${i + 1}`, w: 1, k: 2 });
  items.push({ t: 'BATH', w: 0.55, k: 3 });
  if (l.bath > 1) items.splice(1, 0, { t: 'ENS', w: 0.42, k: 3 });
  const total = items.reduce((s, it) => s + it.w, 0);
  let y = Y0;
  for (const it of items) {
    const h = (Y1 - Y0) * it.w / total;
    rooms.push({ x: a, y, w: X1 - a, h, t: it.t, k: it.k, priv: true });
    y += h;
  }
  const mx = r() < 0.5, my = r() < 0.4;
  rooms = rooms.map(o => ({ ...o, x: mx ? X0 + X1 - (o.x + o.w) : o.x, y: my ? Y0 + Y1 - (o.y + o.h) : o.y }));
  const wallX = mx ? X0 + X1 - a : a;
  const dir = mx ? -1 : 1;

  let s = `<rect width="${u(100)}" height="${u(100)}" fill="${pal[4]}"/>`;
  const living = rooms[0];
  if (l.balcony) {
    const by = living.y === Y0 ? Y0 - 9 : Y1 + 1;
    s += rect({ x: living.x + 3, y: by, w: living.w - 6, h: 8 }, 'none', '#111', 0.5, ` stroke-dasharray="${u(1.6)} ${u(1.2)}"`);
    s += `<text x="${u(living.x + living.w / 2)}" y="${u(by + 5.4)}" font-size="${u(3)}" ${LABEL} fill-opacity=".8">BALCONY</text>`;
  }
  for (const o of rooms) s += rect(o, pal[o.k]);
  for (const o of rooms) s += rect(o, 'none', '#111', 0.8);
  s += rect({ x: X0, y: Y0, w: X1 - X0, h: Y1 - Y0 }, 'none', '#111', 2);
  // one window per room, cut into the outer wall
  for (const o of rooms) {
    const len = Math.min(o.w, o.h) * 0.42;
    let seg = null;
    if (Math.abs(o.y - Y0) < 0.1) seg = [o.x + o.w / 2 - len / 2, Y0, o.x + o.w / 2 + len / 2, Y0];
    else if (Math.abs(o.y + o.h - Y1) < 0.1) seg = [o.x + o.w / 2 - len / 2, Y1, o.x + o.w / 2 + len / 2, Y1];
    else if (Math.abs(o.x - X0) < 0.1) seg = [X0, o.y + o.h / 2 - len / 2, X0, o.y + o.h / 2 + len / 2];
    else if (Math.abs(o.x + o.w - X1) < 0.1) seg = [X1, o.y + o.h / 2 - len / 2, X1, o.y + o.h / 2 + len / 2];
    if (!seg) continue;
    s += line(...seg, pal[4], 2.4) + line(...seg, '#111', 0.4);
  }
  // doors from the living side into each private room
  for (const o of rooms.filter(q => q.priv)) {
    const cy = o.y + o.h / 2;
    s += line(wallX, cy - 3.2, wallX, cy + 3.2, pal[o.k], 1.6);
    s += `<path d="M${u(wallX)} ${u(cy - 3.2)} A${u(6.4)} ${u(6.4)} 0 0 ${dir > 0 ? 1 : 0} ${u(wallX + dir * 6.4)} ${u(cy + 3.2)}" fill="none" stroke="#111" stroke-width="${u(0.35)}"/>`;
    s += line(wallX, cy + 3.2, wallX + dir * 6.4, cy + 3.2, '#111', 0.6);
  }
  for (const o of rooms) {
    s += `<text x="${u(o.x + o.w / 2)}" y="${u(o.y + o.h / 2 + 1.3)}" font-size="${u(o.h < 12 ? 2.8 : 3.4)}" letter-spacing="${u(0.2)}" ${LABEL}>${o.t}</text>`;
  }
  if (l.compass) {
    s += `<g transform="translate(${u(93)} ${u(7)}) rotate(${l.north || 0})"><circle r="${u(3.6)}" fill="none" stroke="#111" stroke-width="${u(0.35)}"/><path d="M0 ${u(-3)} L${u(1.5)} ${u(1.8)} L0 ${u(1)} L${u(-1.5)} ${u(1.8)}Z" fill="#111"/></g>`;
  }
  return `<symbol id="pl-${l.id}" viewBox="0 0 ${u(100)} ${u(100)}">${s}</symbol>`;
}

function buildSprite(listings) {
  document.querySelector('#sprite defs').innerHTML = listings.map(planSymbol).join('');
}

function planUse(id) {
  return `<svg viewBox="0 0 ${u(100)} ${u(100)}" aria-hidden="true"><use href="#pl-${id}" width="${u(100)}" height="${u(100)}"/></svg>`;
}
