// style-match.js — "Looks like this" (soft preference). The renter picks one to three photos of rooms they like; the server
// (src/photo/style.py: Nemotron VL through src/llm/provider.py) reads their finishes and scores every place's lead photo against
// them. It is never a hard condition, never changes the ranking and never enters the narration: the badge says so.
// This module does not touch ui-qi.js. It injects a button into #collection-controls (or after #filters-open), a small panel above
// #property-grid, a badge on each property card (re-applied whenever the grid re-renders) and exposes window.HT_STYLE for the
// detail page: { get(listingId) -> match|null, profile() -> profile|null }; 'ht-style-change' fires on document when results change.
const RENTER_KEY = 'ht_renter';            // app.js / pipecat.js keep the renter id here
const CLEARED_KEY = 'ht_style_cleared';    // Clear: hide the stored result in this browser until the next upload (the server keeps it; Forget me deletes it)
const MAX_FILES = 3, MAX_SIDE = 1024, JPEG_QUALITY = 0.85;
const PHRASE = {
  floor: { timber: 'timber floors', carpet: 'carpet', tile: 'tiled floors', stone: 'stone floors', concrete: 'concrete floors' },
  palette: { light: 'light palette', dark: 'dark palette', warm: 'warm palette', cool: 'cool palette', neutral: 'neutral palette' },
  kitchen: { modern: 'modern kitchen', classic: 'classic kitchen', dated: 'dated kitchen' },
  light: { bright: 'bright rooms', moderate: 'moderate light', dim: 'dim rooms' },
  era: { new: 'new finishes', recent: 'recent finishes', older: 'older finishes' },
};
const SOFT = 'Soft preference — not used for ranking';

const state = { profile: null, matches: {}, busy: false, error: '' };
let button = null, input = null, panel = null, gridObserver = null, raf = 0;

function renter() {
  let id = null;
  try { id = localStorage.getItem(RENTER_KEY); } catch (e) { /* private browsing */ }
  if (!id) {  // app.js normally sets it first; make one the same way if it has not
    id = 'r-' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 24) : String(Date.now()));
    try { localStorage.setItem(RENTER_KEY, id); } catch (e) { /* ignore */ }
  }
  return id;
}
const cleared = () => { try { return localStorage.getItem(CLEARED_KEY) === '1'; } catch (e) { return false; } };
const setCleared = (on) => { try { if (on) localStorage.setItem(CLEARED_KEY, '1'); else localStorage.removeItem(CLEARED_KEY); } catch (e) { /* ignore */ } };
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const chips = (p) => ['floor', 'palette', 'kitchen', 'light', 'era'].map((a) => (PHRASE[a] || {})[p && p[a]]).filter(Boolean);

/* ---------------- results ---------------- */
function setResult(profile, matches) {
  state.profile = profile || null; state.matches = (profile && matches) || {}; state.error = '';
  renderPanel(); applyBadges(); if (button) button.classList.toggle('has-result', !!state.profile);
  document.dispatchEvent(new CustomEvent('ht-style-change', { detail: { profile: state.profile, matches: state.matches } }));
}
async function load() {
  if (cleared()) return;
  try {
    const r = await fetch('/api/style?renter=' + encodeURIComponent(renter()));
    if (!r.ok) return;
    const j = await r.json();
    if (j && j.profile) setResult(j.profile, j.matches || {});
  } catch (e) { /* offline: nothing to show */ }
}
function clear() { setCleared(true); setResult(null, {}); }

/* ---------------- upload ---------------- */
function shrink(file) {  // longest side ≤ 1024, JPEG 0.85, as base64 without the data: prefix
  return new Promise((resolve, reject) => {
    const draw = (src, w, h) => {
      const k = Math.min(1, MAX_SIDE / Math.max(w, h)); const cw = Math.max(1, Math.round(w * k)), ch = Math.max(1, Math.round(h * k));
      const c = document.createElement('canvas'); c.width = cw; c.height = ch; c.getContext('2d').drawImage(src, 0, 0, cw, ch);
      c.toBlob((blob) => {
        if (!blob) return reject(new Error('could not encode ' + file.name));
        const fr = new FileReader(); fr.onload = () => resolve(String(fr.result).split(',')[1] || ''); fr.onerror = () => reject(fr.error); fr.readAsDataURL(blob);
      }, 'image/jpeg', JPEG_QUALITY);
    };
    const viaImage = () => {
      const url = URL.createObjectURL(file); const img = new Image();
      img.onload = () => { try { draw(img, img.naturalWidth, img.naturalHeight); } finally { URL.revokeObjectURL(url); } };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(file.name + ' is not a photo this browser can read')); };
      img.src = url;
    };
    if (window.createImageBitmap) createImageBitmap(file, { imageOrientation: 'from-image' }).then((bm) => { draw(bm, bm.width, bm.height); bm.close && bm.close(); }).catch(viaImage);
    else viaImage();
  });
}
async function upload(files) {
  const list = [...files].filter((f) => /^image\//.test(f.type) || /\.(jpe?g|png|heic|webp)$/i.test(f.name)).slice(0, MAX_FILES);
  if (!list.length) { state.error = 'Pick one to three photos (JPEG or PNG).'; renderPanel(); return; }
  state.busy = true; state.error = ''; renderPanel();
  try {
    const images = [];
    for (const f of list) images.push({ name: f.name, data: await shrink(f) });
    const r = await fetch('/api/style', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ renter: renter(), images }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ('The photo reader answered ' + r.status));
    setCleared(false); state.busy = false; setResult(j.profile, j.matches || {});
  } catch (e) {
    state.busy = false; state.error = e.message || String(e); renderPanel();
  }
}
const pick = () => { if (input && !state.busy) { input.value = ''; input.click(); } };

/* ---------------- the panel above the grid ---------------- */
function renderPanel() {
  if (!panel) return;
  panel.replaceChildren();
  const show = state.busy || state.error || state.profile;
  panel.hidden = !show; if (!show) return;
  if (state.busy) { panel.append(el('span', 'ht-style-dot'), el('span', '', 'Reading your photos…')); return; }
  if (state.error) {
    panel.append(el('span', 'ht-style-error', state.error)); const again = el('button', 'ht-style-clear', 'Try again'); again.type = 'button'; again.addEventListener('click', pick);
    const dismiss = el('button', 'ht-style-clear', 'Dismiss'); dismiss.type = 'button'; dismiss.addEventListener('click', () => { state.error = ''; renderPanel(); }); panel.append(again, dismiss); return;
  }
  const p = state.profile; const n = Object.keys(state.matches).length;
  panel.append(el('b', '', 'Looks like this'));
  const parts = chips(p); if (!parts.length) parts.push('no finishes read');
  parts.forEach((t) => panel.append(el('span', 'ht-style-chip', t)));
  (p.style_words || []).slice(0, 3).forEach((w) => panel.append(el('span', 'ht-style-chip word', w)));
  panel.append(el('span', 'ht-style-soft', `${SOFT} · from ${p.photos || 1} photo${(p.photos || 1) === 1 ? '' : 's'}, ${n} place${n === 1 ? '' : 's'} scored`));
  const c = el('button', 'ht-style-clear', 'Clear'); c.type = 'button'; c.title = 'Hide this in this browser (Forget me deletes it on the server)'; c.addEventListener('click', clear);
  const more = el('button', 'ht-style-clear', 'Other photos'); more.type = 'button'; more.addEventListener('click', pick);
  panel.append(more, c);
}

/* ---------------- badges on the grid cards ---------------- */
function applyBadges() {
  raf = 0;
  document.querySelectorAll('#property-grid .property-card[data-home-id]').forEach((card) => {
    const m = state.matches[card.dataset.homeId]; let b = card.querySelector('.ht-style-badge');
    if (!m) { if (b) b.remove(); return; }
    const text = `Style ${m.score}%`; if (b && b.textContent === text) return;
    if (!b) { b = el('span', 'ht-style-badge'); (card.querySelector('.property-image-wrap') || card).append(b); }
    b.textContent = text;
    b.title = [m.reasons && m.reasons.length ? 'Matches: ' + m.reasons.join(', ') : '', m.misses && m.misses.length ? 'Differs: ' + m.misses.join('; ') : '', SOFT + (m.basis ? ' · ' + m.basis : '')].filter(Boolean).join('\n');
  });
}
const scheduleBadges = () => { if (!raf) raf = requestAnimationFrame(applyBadges); };
function watchGrid() {
  const grid = document.querySelector('#property-grid'); if (!grid || gridObserver) return;
  gridObserver = new MutationObserver(scheduleBadges); gridObserver.observe(grid, { childList: true, subtree: true }); scheduleBadges();
}

/* ---------------- mounting (ui-qi.js builds the page itself, so wait for the pieces and re-add after it rebuilds them) ---------------- */
function mount() {
  if (!input) {
    input = el('input'); input.type = 'file'; input.accept = 'image/*'; input.multiple = true; input.hidden = true; input.className = 'ht-style-input';
    input.addEventListener('change', () => { if (input.files && input.files.length) upload(input.files); });
    document.body.append(input);
  }
  if (!button) {
    button = el('button', 'ht-style-button', 'Looks like this'); button.type = 'button';
    button.title = 'Pick one to three photos of rooms you like; every place gets a style match (a soft preference, not a filter)';
    button.addEventListener('click', pick);
  }
  const controls = document.querySelector('#collection-controls');
  if (controls) { if (button.parentNode !== controls) controls.append(button); }
  else { const fo = document.querySelector('#filters-open'); if (fo && button.parentNode !== fo.parentNode) fo.after(button); }
  if (!panel) { panel = el('div', 'ht-style-panel'); panel.id = 'ht-style-panel'; panel.hidden = true; panel.setAttribute('aria-live', 'polite'); }
  const grid = document.querySelector('#property-grid');
  if (grid) { if (panel.parentNode !== grid.parentNode) grid.before(panel); }
  else if (!panel.parentNode) { const dock = document.querySelector('#dock'); if (dock) dock.append(panel); }
  watchGrid();
}
mount();
let mountRaf = 0;  // ui-qi.js rebuilds #collection-controls and the grid after /api/listings: re-add our pieces, at most once a frame
new MutationObserver(() => { if (!mountRaf) mountRaf = requestAnimationFrame(() => { mountRaf = 0; mount(); }); }).observe(document.documentElement, { childList: true, subtree: true });
load();

window.HT_STYLE = { get: (id) => state.matches[id] || null, profile: () => state.profile, pick, clear, SOFT };
