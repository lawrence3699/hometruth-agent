// HomeTruth 2026-10-26: the sun figure on the detail page. An isometric sky dome over a small apartment block, with the sun's track on
// 21 June (winter) and 21 December (summer) from src/sun/solar.py (home.sun: tracks[], direct{}, aspect, facing_deg, floor). The stretch of
// each track the main window can see (azimuth within 85° of the window's facing, above the horizon) is drawn warm and thick; the rest thin and
// grey. No obstruction data, so it is sky geometry only, and the legend says so. Facing unknown → the arcs are drawn, the wedge is not, and
// the legend says what to ask the agent. Pure SVG, no library; the moving sun is SMIL animateMotion (off under prefers-reduced-motion).
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const NS = 'http://www.w3.org/2000/svg';
const W = 600, H = 390, CX = 300, CY = 262, R = 168, K = 1;  // canvas, ground centre, dome radius
const C30 = Math.cos(Math.PI / 6), S30 = Math.sin(Math.PI / 6);
const HALF = 85;  // window half-angle, same as solar.py WINDOW_HALF_ANGLE
const rad = (d) => d * Math.PI / 180;
function el(tag, attrs = {}, text) { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v); if (text != null) n.textContent = text; return n; }
// world: x east, y north, z up → screen (isometric, viewer to the south-west)
const P = (x, y, z = 0) => [CX + (x - y) * C30 * K, CY + (x + y) * S30 * K - z * K];
const onDome = (az, elev) => { const a = rad(az), e = rad(elev); return P(R * Math.cos(e) * Math.sin(a), R * Math.cos(e) * Math.cos(a), R * Math.sin(e)); };
const onGround = (az, r = R) => P(r * Math.sin(rad(az)), r * Math.cos(rad(az)), 0);
const fmt = (pts) => pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
const azDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
const hours = (h) => (h == null ? '' : `${h} h`);
const span = (d) => (d && d.spans && d.spans.length ? `${d.spans[0][0]}–${d.spans[d.spans.length - 1][1]}` : 'none');

export function sunFigure(sun, opts = {}) {
  const facing = typeof sun.facing_deg === 'number' ? sun.facing_deg : null;
  const obstruction = Number(sun.obstruction_elev || 0);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, class: 'sun-figure', role: 'img', 'aria-label': opts.label || 'Sun path over the building on 21 June and 21 December' });
  const defs = el('defs');
  const grad = el('radialGradient', { id: 'sun-sky', cx: '50%', cy: '35%', r: '70%' });
  grad.append(el('stop', { offset: '0', 'stop-color': '#f6f9ff' }), el('stop', { offset: '1', 'stop-color': '#e9eef5' }));
  defs.append(grad); svg.append(defs);
  // the ground ring (horizon) and the compass
  svg.append(el('polygon', { points: fmt([...Array(73)].map((_, i) => onGround(i * 5))), fill: 'url(#sun-sky)', stroke: '#c9d2dc', 'stroke-width': 1 }));
  for (let az = 0; az < 360; az += 90) { const [x1, y1] = onGround(az, 18), [x2, y2] = onGround(az, R); svg.append(el('line', { x1, y1, x2, y2, stroke: '#d6dde6', 'stroke-width': 1, 'stroke-dasharray': az % 180 ? '3 4' : null })); }
  for (const [az, name] of [[0, 'N'], [90, 'E'], [180, 'S'], [270, 'W']]) { const [x, y] = onGround(az, R + 16); svg.append(el('text', { x, y: y + 4, 'text-anchor': 'middle', class: 'sun-compass' + (az === 0 ? ' north' : '') }, name)); }
  // the window's field of view: a wedge on the ground, facing ± 85°
  if (facing != null) {
    const pts = [P(0, 0, 0)]; for (let a = facing - HALF; a <= facing + HALF; a += 5) pts.push(onGround(a)); pts.push(onGround(facing + HALF));
    svg.append(el('polygon', { points: fmt(pts), fill: '#f4c66a', 'fill-opacity': 0.22, stroke: '#e0a93a', 'stroke-width': 1, 'stroke-dasharray': '4 3' }));
  }
  // the block: a box with as many storeys as the floor suggests (ground + floor, at least 2, at most 8), the window drawn on the facing side
  const storeys = Math.min(8, Math.max(2, (typeof sun.floor === 'number' ? sun.floor : 2) + 1));
  const hw = 26, hgt = storeys * 11;
  const box = [[hw, hw], [hw, -hw], [-hw, -hw], [-hw, hw]];
  const top = box.map(([x, y]) => P(x, y, hgt));
  svg.append(el('polygon', { points: fmt([P(hw, hw, 0), P(hw, -hw, 0), P(hw, -hw, hgt), P(hw, hw, hgt)]), fill: '#d9dfd6', stroke: '#9aa89a', 'stroke-width': 1 }));   // east face
  svg.append(el('polygon', { points: fmt([P(hw, hw, 0), P(-hw, hw, 0), P(-hw, hw, hgt), P(hw, hw, hgt)]), fill: '#c9d1c4', stroke: '#9aa89a', 'stroke-width': 1 }));   // north face
  svg.append(el('polygon', { points: fmt(top), fill: '#eef1ea', stroke: '#9aa89a', 'stroke-width': 1 }));
  for (let s = 1; s < storeys; s++) { svg.append(el('polyline', { points: fmt([P(-hw, hw, s * 11), P(hw, hw, s * 11), P(hw, -hw, s * 11)]), fill: 'none', stroke: '#b4bfb2', 'stroke-width': 0.8 })); }
  if (facing != null) {  // the main window: a warm panel on the face that looks the window's way (dashed through the box when that face is hidden)
    const z0 = (typeof sun.floor === 'number' ? Math.min(sun.floor, storeys - 1) : 1) * 11 + 2, z1 = z0 + 7;
    const face = facing < 45 || facing >= 315 ? 'N' : facing < 135 ? 'E' : facing < 225 ? 'S' : 'W';
    const win = { N: [[-10, hw], [10, hw]], E: [[hw, 10], [hw, -10]], S: [[10, -hw], [-10, -hw]], W: [[-hw, -10], [-hw, 10]] }[face];
    const pts = [P(win[0][0], win[0][1], z0), P(win[1][0], win[1][1], z0), P(win[1][0], win[1][1], z1), P(win[0][0], win[0][1], z1)];
    const hidden = face === 'S' || face === 'W';
    svg.append(el('polygon', { points: fmt(pts), fill: hidden ? 'none' : '#f4c66a', stroke: '#c98a1c', 'stroke-width': 1.2, 'stroke-dasharray': hidden ? '3 3' : null }));
    const [ax, ay] = onGround(facing, hw + 14), [bx, by] = onGround(facing, hw + 34);
    svg.append(el('line', { x1: ax, y1: ay, x2: bx, y2: by, stroke: '#c98a1c', 'stroke-width': 1.6, 'marker-end': null }));
    svg.append(el('circle', { cx: bx, cy: by, r: 3, fill: '#c98a1c' }));
  }
  // the two sun tracks: lit stretches thick and warm, the rest thin and grey; small hour ticks
  const tracks = sun.tracks || {};
  const colors = { winter: '#d9821b', summer: '#e05a2f' };
  let firstLit = null;
  for (const name of ['winter', 'summer']) {
    const t = tracks[name] || []; if (!t.length) continue;
    const pts = t.map((p) => onDome(p.az, p.elev));
    svg.append(el('polyline', { points: fmt(pts), fill: 'none', stroke: '#9aa5b1', 'stroke-width': 1.2, 'stroke-dasharray': '2 3', 'stroke-linecap': 'round' }));
    if (facing != null) {
      let run = [];
      const flush = () => { if (run.length > 1) { const pl = el('polyline', { points: fmt(run), fill: 'none', stroke: colors[name], 'stroke-width': 3.2, 'stroke-linecap': 'round' }); svg.append(pl); if (!firstLit) firstLit = { name, run }; } run = []; };
      t.forEach((p, i) => { const lit = p.elev > obstruction && azDiff(p.az, facing) < HALF; if (lit) run.push(pts[i]); else flush(); }); flush();
    }
    t.forEach((p, i) => { if (/^(06|09|12|15|18):00$/.test(p.t)) { const [x, y] = pts[i]; svg.append(el('circle', { cx: x, cy: y, r: 2.2, fill: '#6b7785' })); svg.append(el('text', { x: x + 5, y: y - 4, class: 'sun-hour' }, p.t.slice(0, 2))); } });
    const [lx, ly] = pts[Math.floor(pts.length * (name === 'winter' ? 0.5 : 0.52))];
    svg.append(el('text', { x: lx, y: ly - 12, 'text-anchor': 'middle', class: 'sun-track-label', fill: colors[name] }, name === 'winter' ? '21 June' : '21 December'));
  }
  // a moving sun on the winter track (the one people ask about), unless motion is reduced
  const wt = tracks.winter || [];
  if (wt.length > 1 && !reduced.matches) {
    const d = wt.map((p, i) => (i ? 'L' : 'M') + onDome(p.az, p.elev).map((v) => v.toFixed(1)).join(' ')).join(' ');
    const sunDot = el('circle', { r: 6, fill: '#f7b733', stroke: '#fff', 'stroke-width': 1.5, class: 'sun-dot' });
    const mo = el('animateMotion', { dur: '9s', repeatCount: 'indefinite', path: d }); sunDot.append(mo); svg.append(sunDot);
  }
  return svg;
}

export function sunLegend(sun) {
  // 10-27: two lines of numbers (the figure carries the rest); the explanation lives in sunHow() behind "How this is worked out"
  const ul = document.createElement('ul'); ul.className = 'sun-legend';
  const li = (t, cls) => { const n = document.createElement('li'); if (cls) n.className = cls; n.textContent = t; ul.append(n); return n; };
  const d = sun.direct || {};
  const when = (x) => (x && x.spans && x.spans.length ? ` (${x.spans[0][0]}–${x.spans[x.spans.length - 1][1]})` : '');
  if (sun.aspect) {
    if (d.winter && d.winter.hours != null) li(`21 June: ~${d.winter.hours} h direct sun${when(d.winter)}`, 'sun-winter');
    if (d.summer && d.summer.hours != null) li(`21 December: ~${d.summer.hours} h${when(d.summer)}`, 'sun-summer');
    if (!(d.winter && d.winter.hours != null) && !(d.summer && d.summer.hours != null)) li(`Window facing ${sun.aspect}`, 'sun-facing');
    li('sky geometry only', 'sun-caveat');
  } else {
    li('Facing: not in the listing', 'sun-unknown');
    li('ask the agent for the north arrow · sky geometry only', 'sun-caveat');
  }
  return ul;
}

export function sunHow(sun) {
  // the sentences that used to sit under the figure, folded
  const d = sun.direct || {};
  const lines = ['Where the sun is over this block on the shortest and the longest day, and the stretch the main window can see. Worked out from the latitude and the facing, not promised by anyone.'];
  if (sun.aspect) {
    lines.push(`Window facing ${sun.aspect}` + (sun.aspect_source ? ` (${sun.aspect_source === 'listing text' ? 'the listing says so' : 'read off the floor plan, ' + (sun.aspect_confidence || 'low') + ' confidence'})` : '') + '.');
    if (d.winter) lines.push(`21 June: about ${hours(d.winter.hours)} of direct sun on that window, ${span(d.winter)}.`);
    if (d.summer) lines.push(`21 December: about ${hours(d.summer.hours)}, ${span(d.summer)}.`);
  } else {
    lines.push('Which way the main window faces is not in the listing, so the lit stretch cannot be drawn. The arcs show where the sun is; ask the agent for the north arrow.');
  }
  if (typeof sun.floor === 'number') lines.push(`Level ${sun.floor}` + (sun.floor_source === 'unit number' ? ', worked out from the unit number' : sun.floor_source === 'listing text' ? ', from the listing' : '') + '.');
  lines.push((sun.approx_location ? `Sun position for the ${sun.approx_location}. ` : '') + 'Neighbouring buildings are not in the data: sky geometry only, computed, not observed.');
  const det = document.createElement('details'); det.className = 'ht-fold sun-how';
  const sum = document.createElement('summary'); sum.textContent = 'How this is worked out'; det.append(sum);
  const body = document.createElement('div'); body.className = 'ht-fold-body';
  lines.forEach((t) => { const p = document.createElement('p'); p.textContent = t; body.append(p); });
  det.append(body);
  return det;
}

export function sunSection(home) {
  const sec = document.createElement('section'); sec.className = 'listing-section listing-sun'; sec.id = 'listing-sun';
  const h2 = document.createElement('h2'); h2.textContent = 'Sun'; sec.append(h2);
  const wrap = document.createElement('div'); wrap.className = 'sun-figure-wrap';
  const notes = document.createElement('div'); notes.className = 'sun-notes'; notes.append(sunLegend(home.sun), sunHow(home.sun));
  wrap.append(sunFigure(home.sun), notes); sec.append(wrap);
  return sec;
}
