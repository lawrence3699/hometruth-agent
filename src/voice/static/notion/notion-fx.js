// notion-fx.js · motion for the Notion-style HomeTruth preview (fork, 2026-10-27).
// Every function is a port of one Lucian UX/UI Prompt element (MIT License, (c) 2026 Seokwoooo, https://lucianlabs.dev/uxui-prompt/);
// the originals are kept in ../qi/vendor/lucian/NNN-*.txt with the licence in ../qi/vendor/lucian/LICENSE.md, and the #NNN below is
// Lucian's element number. The motion recipes (timings, easings, what moves first) are theirs; the DOM is ours. With
// prefers-reduced-motion: reduce each function still changes what it has to change, only without the movement.
const RMQ = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
export const reduced = () => RMQ.matches;
const raf = (f) => requestAnimationFrame(f);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* #216 Staggered hero entrance: the nav settles from above, then every [data-enter] rises in turn, the product window last,
   tilted back and blurred. Classes come off after the run so later hovers carry no delay. */
export function heroEntrance(root) {
  const items = [...root.querySelectorAll('[data-enter]')];
  items.forEach((n, i) => n.style.setProperty('--d', (n.dataset.enter ? Number(n.dataset.enter) : i * 90) + 'ms'));
  if (reduced()) return;
  root.classList.add('fx-pre');
  void root.offsetHeight;  // flush the hidden starting state, then start: no requestAnimationFrame, which a background page never gets
  root.classList.add('fx-go');
  setTimeout(() => root.classList.remove('fx-pre', 'fx-go'), 2600);
}

/* #237 Line-by-line mask reveal, for the rotating word in the hero pill: the old word leaves upward, the new one rises from under
   the mask with a small tilt, and the pill's width follows. Stops while the tab is hidden; with reduced motion it stays on the first word. */
export function rotateWord(pill, words, every = 2600) {
  const mask = pill.querySelector('.nt-pill-mask'); if (!mask || words.length < 2) return () => {};
  const probe = document.createElement('span'); probe.className = 'nt-pill-word nt-pill-probe'; mask.appendChild(probe);
  const widthOf = (t) => { probe.textContent = t; return probe.getBoundingClientRect().width; };
  let i = 0, timer = null, curText = words[0].text;
  const show = (w) => {
    pill.dataset.tone = w.tone; curText = w.text;
    const old = mask.querySelector('.nt-pill-word:not(.nt-pill-probe):not(.out)');
    const next = document.createElement('span'); next.className = 'nt-pill-word enter'; next.textContent = w.text;
    mask.style.width = widthOf(old ? old.textContent : w.text) + 'px';
    mask.appendChild(next);
    // widthOf() forces a layout, so the old width and the new word's "below the mask" state are computed before they change
    const to = widthOf(w.text);
    mask.style.width = to + 'px'; next.classList.remove('enter'); if (old) old.classList.add('out');
    if (old) setTimeout(() => old.remove(), 700);
  };
  const tick = () => { if (!document.hidden) { i = (i + 1) % words.length; show(words[i]); } timer = setTimeout(tick, every); };
  pill.dataset.tone = words[0].tone;
  if (!reduced()) {
    // fit the mask to whatever word is showing; again whenever a web font arrives (Inter replaces the fallback and every width changes)
    const fit = () => { mask.style.width = widthOf(curText) + 'px'; mask.classList.add('live'); };
    fit();
    if (document.fonts) { document.fonts.addEventListener && document.fonts.addEventListener('loadingdone', fit); if (document.fonts.ready) document.fonts.ready.then(fit); }
    timer = setTimeout(tick, every);
  }
  return () => clearTimeout(timer);
}

/* #237 again, for section headings: each line (split on <br>) slides up from under its own mask when the heading scrolls in */
export function maskHeadings(nodes) {
  nodes.forEach((h) => {
    const parts = h.innerHTML.split(/<br\s*\/?>/i);
    h.innerHTML = parts.map((p, i) => `<span class="fx-ln"><span class="fx-ln-in" style="--i:${i}">${p.trim()}</span></span>`).join('');
  });
  if (reduced() || !('IntersectionObserver' in window)) { nodes.forEach((h) => h.classList.add('fx-ln-on')); return; }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('fx-ln-on'); io.unobserve(e.target); } }), { threshold: 0.3 });
  nodes.forEach((h) => { h.classList.add('fx-ln-wait'); io.observe(h); });
}

/* #251 Staggered scroll-in feature cards: cards entering the screen together rise from below one after another */
let revealIO = null;
export function reveal(nodes) {
  nodes = [...nodes].filter((n) => !n.dataset.fxSeen);
  nodes.forEach((n) => { n.dataset.fxSeen = '1'; });
  if (reduced() || !('IntersectionObserver' in window)) return;
  if (!revealIO) {
    revealIO = new IntersectionObserver((es) => {
      const inView = es.filter((e) => e.isIntersecting).map((e) => e.target)
        .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top || a.getBoundingClientRect().left - b.getBoundingClientRect().left);
      inView.forEach((n, k) => {
        revealIO.unobserve(n); n.style.setProperty('--d', k * 70 + 'ms'); n.classList.add('fx-rise-in');
        setTimeout(() => n.classList.remove('fx-rise', 'fx-rise-in'), 900 + k * 70);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  }
  nodes.forEach((n) => { n.classList.add('fx-rise'); revealIO.observe(n); });
}

/* #251 again, for the bento cards: each card's slice of product UI plays once, the first time the card is on screen */
export function playInView(nodes) {
  if (reduced() || !('IntersectionObserver' in window)) { nodes.forEach((n) => n.classList.add('is-play')); return; }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-play'); io.unobserve(e.target); } }), { threshold: 0.4 });
  nodes.forEach((n) => io.observe(n));
}

/* #047 Period segmented control (and #039 Sliding pill tabs): the knob stretches toward the new option first, then its trailing
   edge catches up. Works for any row of buttons with one .is-on; returns place(btn). */
export function slider(group, knob) {
  let last = null;
  const place = (btn, animate = true) => {
    if (!btn) return;
    const g = group.getBoundingClientRect(), b = btn.getBoundingClientRect();
    const left = b.left - g.left + group.scrollLeft, right = g.width - left - b.width;
    if (!animate || !last || reduced()) { group.classList.remove('go-r', 'go-l'); knob.style.transition = 'none'; }
    else { knob.style.transition = ''; const toRight = left > last; group.classList.toggle('go-r', toRight); group.classList.toggle('go-l', !toRight); }
    knob.style.left = left + 'px'; knob.style.right = right + 'px'; last = left;
    if (knob.style.transition === 'none') raf(() => { knob.style.transition = ''; });
  };
  if ('ResizeObserver' in window) new ResizeObserver(() => place(group.querySelector('.is-on'), false)).observe(group);
  return place;
}

/* #056 Monthly–yearly pricing toggle / #018 rolling stepper: only the digits that change roll, one column after another */
export function roll(node, text) {
  text = String(text);
  const old = node.dataset.val || '';
  node.dataset.val = text; node.setAttribute('aria-label', text);
  if (reduced() || !old) { node.textContent = text; return; }
  const pad = (s, n) => ' '.repeat(Math.max(0, n - s.length)) + s;
  const n = Math.max(old.length, text.length); const a = pad(old, n), b = pad(text, n); const lead = n - text.length;
  node.innerHTML = [...b].map((ch, k) => {
    if (k < lead) return '';  // padding that only lines the old and new strings up from the right
    if (!/\d/.test(ch)) return `<span class="fx-od-ch" aria-hidden="true">${ch === ' ' ? ' ' : ch}</span>`;
    const from = /\d/.test(a[k]) ? Number(a[k]) : 0;
    return `<span class="fx-od" aria-hidden="true"><span class="fx-od-col" style="--v:${from};--k:${k}">${'0123456789'.split('').map((d) => `<span>${d}</span>`).join('')}</span></span>`;
  }).join('');
  void node.offsetWidth;  // the old digits are on screen now; rolling to the new ones animates
  const digits = b.replace(/[^\d]/g, '');
  node.querySelectorAll('.fx-od-col').forEach((c, k) => c.style.setProperty('--v', digits[k]));
  clearTimeout(node._fxRoll); node._fxRoll = setTimeout(() => { if (node.dataset.val === text) node.textContent = text; }, 1200);
}

/* #070 Stacking toasts: a new toast rises to the front, the earlier ones tuck behind it, smaller and fainter; each leaves on its own */
export function toaster(box) {
  const live = [];
  const layout = () => live.forEach((t, k) => { t.style.setProperty('--k', k); t.classList.toggle('back', k > 0); t.hidden = k > 2; });
  return (html, ms = 6000) => {
    const t = document.createElement('div'); t.className = 'fx-toast enter'; t.innerHTML = html; t.setAttribute('role', 'status');
    box.prepend(t); live.unshift(t); layout();
    void t.offsetWidth; t.classList.remove('enter');
    const leave = () => { const i = live.indexOf(t); if (i < 0) return; live.splice(i, 1); t.classList.add('leave'); layout(); setTimeout(() => t.remove(), 450); };
    t.addEventListener('click', leave); setTimeout(leave, ms);
  };
}


/* #086 Streaming AI answer: the sentence flows in word by word out of a light blur, a caret blinking at the end until it is done */
export function stream(node, text) {
  if (reduced()) { node.textContent = text; return; }
  const words = String(text).split(/(\s+)/);
  const step = Math.min(26, 900 / Math.max(1, words.length / 2));
  let k = 0;
  node.innerHTML = words.map((w) => (/^\s+$/.test(w) ? w : `<span class="fx-w" style="animation-delay:${Math.round(k++ * step)}ms">${w.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))}</span>`)).join('') + '<i class="fx-caret" aria-hidden="true"></i>';
  clearTimeout(node._fxCaret); node._fxCaret = setTimeout(() => { const c = node.querySelector('.fx-caret'); if (c) c.remove(); }, k * step + 700);
}

/* #083 Queue bar turning into progress: two segments chase each other while nothing has finished; then a bar fills with the share done */
export function queueBar(bar, done, total) {
  if (!bar) return;
  const p = total ? done / total : 0;
  bar.classList.toggle('is-queue', done === 0 && total > 0);
  bar.classList.toggle('is-done', total > 0 && done >= total);
  bar.style.setProperty('--p', p.toFixed(3));
  bar.hidden = !total;
}

/* #212 Hide-on-scroll header: roomy and clear at the top, a hairline once you scroll, out of the way while you read down, back the moment
   you scroll up; a thin bar along its bottom edge shows how far down the page you are. */
export function hideOnScroll(nav, bar) {
  let y0 = window.scrollY, ticking = false;
  const run = () => {
    ticking = false; const y = window.scrollY, dy = y - y0; y0 = y;
    nav.classList.toggle('is-solid', y > 8);
    if (!reduced()) { if (dy > 6 && y > 420) nav.classList.add('is-hide'); else if (dy < -6 || y < 200) nav.classList.remove('is-hide'); }
    const max = document.documentElement.scrollHeight - innerHeight;
    if (bar) bar.style.transform = `scaleX(${max > 0 ? clamp(y / max, 0, 1).toFixed(4) : 0})`;
  };
  addEventListener('scroll', () => { if (!ticking) { ticking = true; raf(run); } }, { passive: true }); run();
  nav.addEventListener('focusin', () => nav.classList.remove('is-hide'));
}

/* #233 Rotating-example AI prompt box: while the box is empty and not focused, example requests type themselves out, wait, erase and
   change. An overlay span does the typing (a placeholder cannot carry the caret); clicking a suggestion still fills the real input. */
export function typingPlaceholder(input, overlay, examples, idle = () => 'Or type what you need…', when = () => true) {
  let i = 0, j = 0, dir = 1, timer = null, stopped = false;
  const active = () => !stopped && when() && !input.value && document.activeElement !== input && !document.hidden;
  const sync = () => { const on = !stopped && when() && !input.value && document.activeElement !== input; overlay.hidden = !on; input.placeholder = on ? '' : idle(); };
  const step = () => {
    if (!active()) { sync(); timer = setTimeout(step, 400); return; }
    sync(); const s = examples[i];
    if (dir > 0) { j++; overlay.textContent = s.slice(0, j); if (j >= s.length) { dir = -1; timer = setTimeout(step, 2200); return; } timer = setTimeout(step, 34 + Math.random() * 30); }
    else { j -= 2; overlay.textContent = s.slice(0, Math.max(0, j)); if (j <= 0) { dir = 1; j = 0; i = (i + 1) % examples.length; timer = setTimeout(step, 420); return; } timer = setTimeout(step, 14); }
  };
  ['input', 'focus', 'blur'].forEach((e) => input.addEventListener(e, sync));
  if (reduced()) { overlay.textContent = examples[0]; overlay.classList.add('still'); sync(); }
  else timer = setTimeout(step, 1400);
  return { sync, stop() { stopped = true; clearTimeout(timer); overlay.hidden = true; input.placeholder = idle(); } };
}

/* #044 FAQ accordion: the panel lifts as its answer unfolds, one stroke of the plus lies down into a minus, only one open at a time;
   arrow keys move between questions */
export function accordion(list) {
  const items = [...list.querySelectorAll('.fx-acc')];
  const set = (it, open) => { it.classList.toggle('open', open); it.querySelector('.fx-acc-q').setAttribute('aria-expanded', String(open)); };
  items.forEach((it, k) => {
    const q = it.querySelector('.fx-acc-q');
    q.addEventListener('click', () => { const open = !it.classList.contains('open'); items.forEach((o) => set(o, false)); set(it, open); });
    q.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return; e.preventDefault();
      const n = items[(k + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]; n.querySelector('.fx-acc-q').focus();
    });
  });
}

/* #260 Scroll-filled sentence: the big sentence sits in faint grey and fills in, word by word, as far as you have scrolled through it */
export function scrollFill(section, p) {
  const words = [];
  const src = p.innerHTML; p.innerHTML = '';
  src.split(/(<em>.*?<\/em>)/).forEach((chunk) => {
    const em = /^<em>/.test(chunk); const txt = chunk.replace(/<\/?em>/g, '');
    txt.split(/\s+/).filter(Boolean).forEach((w) => { const s = document.createElement('span'); s.className = 'fx-fw' + (em ? ' em' : ''); s.textContent = w; p.append(s, ' '); words.push(s); });
  });
  if (reduced()) { words.forEach((w) => w.style.setProperty('--f', 1)); return; }
  let ticking = false;
  const draw = () => {
    ticking = false;
    const r = section.getBoundingClientRect(); const run = r.height - innerHeight;
    const t = run > 0 ? clamp(-r.top / run, 0, 1) : clamp(1 - r.top / innerHeight, 0, 1);
    const f = t * 1.15 * words.length;
    words.forEach((w, i) => { const v = clamp(f - i, 0, 1); w.style.setProperty('--f', v.toFixed(2)); w.classList.toggle('on', v >= 1); });
  };
  addEventListener('scroll', () => { if (!ticking) { ticking = true; raf(draw); } }, { passive: true }); draw();
}

/* #217 Plan comparison with differences only: hovering a cell lights its whole column; the switch folds rows that say the same thing
   in every column */
export function compareTable(table, sw) {
  table.addEventListener('pointerover', (e) => { const c = e.target.closest('[data-col]'); table.dataset.hot = c ? c.dataset.col : ''; });
  table.addEventListener('pointerleave', () => { table.dataset.hot = ''; });
  if (sw) sw.addEventListener('click', () => { const on = sw.getAttribute('aria-checked') !== 'true'; sw.setAttribute('aria-checked', String(on)); table.classList.toggle('diff-only', on); });
}

/* #271 Filterable changelog: the pill slides to the chosen chip, entries that don't match fold away and the rest close up; the newest
   entry's dot pulses */
export function changelog(root, place) {
  root.querySelectorAll('.fx-cl-chip').forEach((c) => c.addEventListener('click', () => {
    root.querySelectorAll('.fx-cl-chip').forEach((o) => o.classList.toggle('is-on', o === c)); place(c);
    const f = c.dataset.filter; root.querySelectorAll('.fx-cl-en').forEach((en) => en.classList.toggle('is-off', f !== 'all' && en.dataset.kind !== f));
  }));
}

/* #275 Scroll-following table of contents: the entries for the sections on screen darken and a marker stretches to cover them;
   pressing an entry scrolls there smoothly. Given opts.place it drives a row of tabs instead: only the section you are in is on, and
   place(link) slides the row's knob under it (opts.offset: how far down the scroller a section counts as reached; opts.gap: where a
   pressed section lands). */
export function toc(scroller, nav, opts = {}) {
  const links = [...nav.querySelectorAll('a[data-to]')]; const mk = nav.querySelector('.fx-toc-mk');
  const secs = links.map((a) => scroller.querySelector('#' + a.dataset.to));
  const off = opts.offset || 60, gap = opts.gap || 24;
  let ticking = false, cur = -1;
  const draw = () => {
    ticking = false; const view = scroller.getBoundingClientRect();
    if (opts.place) {
      let k = 0; secs.forEach((s, i) => { if (s && s.getBoundingClientRect().top - view.top <= off) k = i; });
      if (scroller.scrollTop > 0 && scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4) k = secs.length - 1;  // a short last section never reaches the top
      if (k !== cur) { cur = k; links.forEach((a, i) => a.classList.toggle('is-on', i === k)); opts.place(links[k]); }
      return;
    }
    const on = [];
    secs.forEach((s, i) => { if (!s) return; const r = s.getBoundingClientRect(); if (r.bottom > view.top + off && r.top < view.bottom - 80) on.push(i); });
    links.forEach((a, i) => a.classList.toggle('on', on.includes(i)));
    if (!on.length || !mk) return;
    const a = links[on[0]], b = links[on[on.length - 1]];
    mk.style.transform = `translateY(${a.offsetTop}px)`; mk.style.height = (b.offsetTop + b.offsetHeight - a.offsetTop) + 'px';
  };
  scroller.addEventListener('scroll', () => { if (!ticking) { ticking = true; raf(draw); } }, { passive: true });
  links.forEach((a, i) => a.addEventListener('click', (e) => { e.preventDefault(); const s = secs[i]; if (s) scroller.scrollTo({ top: s.offsetTop - gap, behavior: reduced() ? 'auto' : 'smooth' }); }));
  draw(); return draw;
}

/* #061 Thumbnail-to-lightbox zoom: the photo grows from its thumbnail to fill the frame and shrinks back into it on close;
   arrow keys page through the set */
export function lightbox(box) {
  let list = [], k = 0, from = null;
  const img = box.querySelector('img'), cap = box.querySelector('.fx-lb-cap');
  const flip = (rect, toBig) => {
    if (reduced() || !rect) return Promise.resolve();
    const r = img.getBoundingClientRect(); if (!r.width) return Promise.resolve();
    const t = `translate(${rect.left + rect.width / 2 - (r.left + r.width / 2)}px, ${rect.top + rect.height / 2 - (r.top + r.height / 2)}px) scale(${rect.width / r.width}, ${rect.height / r.height})`;
    const a = img.animate(toBig ? [{ transform: t, borderRadius: '24px' }, { transform: 'none', borderRadius: '8px' }] : [{ transform: 'none' }, { transform: t, borderRadius: '24px' }], { duration: toBig ? 460 : 340, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
    return a.finished.catch(() => {});
  };
  const show = (i) => { k = (i + list.length) % list.length; img.src = list[k].src; img.alt = list[k].alt || ''; cap.textContent = list[k].caption || ''; };
  const close = async () => { if (box.hidden) return; box.classList.remove('open'); await flip(from && from.isConnected ? from.getBoundingClientRect() : null, false); box.hidden = true; img.getAnimations().forEach((a) => a.cancel()); };
  box.addEventListener('click', (e) => { if (e.target.closest('[data-lb-prev]')) show(k - 1); else if (e.target.closest('[data-lb-next]')) show(k + 1); else close(); });
  document.addEventListener('keydown', (e) => { if (box.hidden) return; if (e.key === 'ArrowRight') show(k + 1); if (e.key === 'ArrowLeft') show(k - 1); });  // Escape: the page's capture handler (it must not reach app.js's "stop talking")
  return { isOpen: () => !box.hidden, open(items, i, thumb) { list = items; from = thumb; show(i); box.hidden = false; void box.offsetWidth; box.classList.add('open'); img.decode().catch(() => {}).then(() => flip(thumb && thumb.getBoundingClientRect(), true)); }, close };
}

/* #002 Magnetic arrow button: the round arrow leans toward the pointer as it comes near and springs back when it leaves */
export function magnetic(nodes) {
  if (reduced()) return;
  nodes.forEach((n) => {
    const host = n.closest('[data-mag-host]') || n;
    host.addEventListener('pointermove', (e) => { const r = n.getBoundingClientRect(); const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2); n.style.translate = `${clamp(dx * 0.22, -10, 10)}px ${clamp(dy * 0.22, -8, 8)}px`; });
    host.addEventListener('pointerleave', () => { n.style.translate = '0 0'; });
  });
}
