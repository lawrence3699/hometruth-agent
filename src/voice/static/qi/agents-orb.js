/**
 * The voice orb: a small canvas drawing of our own (public repository version).
 * Same interface the pages use: createAgentsOrb(host) → { ready, setState(state), setLevel(0..1), destroy() },
 * states idle / listening / thinking / speaking / error, and an 'agents-orb-ready' event on the host.
 * The hosted demo uses ElevenLabs' marketing orb renderer, which we do not redistribute.
 */
const states = new Set(['idle', 'listening', 'thinking', 'speaking', 'error']);
const PALETTE = {  // [base inner, base outer, blob A, blob B]
  idle: ['#e8f1ff', '#6b8fd6', '#7fd1c7', '#f2c879'],
  listening: ['#e6f4ff', '#3d7be0', '#58c4dd', '#9bd88f'],
  thinking: ['#eef0f6', '#7d86a8', '#a9b4d8', '#c9b8e8'],
  speaking: ['#eaf2ff', '#2f6fdc', '#4fd1c5', '#f6c453'],
  error: ['#fff0ee', '#d0644f', '#f2a08f', '#f6c453'],
};

export function createAgentsOrb(host) {
  if (!host || host.nodeType !== 1) throw new TypeError('createAgentsOrb requires a DOM element');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const holder = document.createElement('span');
  holder.className = 'agents-original-orb';
  holder.dataset.state = 'idle';
  holder.dataset.renderer = 'canvas';
  holder.setAttribute('aria-hidden', 'true');
  holder.style.cssText = 'position:relative;display:block;width:100%;height:100%;overflow:hidden;border-radius:50%;pointer-events:none';
  if (!(parseFloat(getComputedStyle(host).height) > 0)) holder.style.width = holder.style.height = '160px';
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
  holder.append(canvas);
  host.append(holder);
  const ctx = canvas.getContext('2d');

  let state = 'idle', level = null, shown = 0, frame = 0, disposed = false, visible = true;
  function size() {
    const r = holder.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  }
  function blob(x, y, r, color) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, color); g.addColorStop(1, color + '00');
    ctx.fillStyle = g; ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  function draw(now) {
    size();
    const w = canvas.width, h = canvas.height, R = Math.min(w, h) / 2, cx = w / 2, cy = h / 2, t = now / 1000;
    const [inner, outer, a, b] = PALETTE[state];
    // how lively: the measured level when we have one, otherwise a gentle state-dependent breath
    const auto = state === 'speaking' ? 0.35 + 0.25 * Math.sin(t * 3.4) ** 2 : state === 'listening' ? 0.2 + 0.1 * Math.sin(t * 2.2) ** 2 : state === 'thinking' ? 0.15 : 0.08;
    shown += ((level ?? auto) - shown) * 0.15;
    const speed = state === 'thinking' ? 1.6 : 0.5 + shown;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.clip();
    const base = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, R * 0.1, cx, cy, R);
    base.addColorStop(0, inner); base.addColorStop(1, outer);
    ctx.fillStyle = base; ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';
    blob(cx + Math.cos(t * speed) * R * 0.38, cy + Math.sin(t * speed * 0.8) * R * 0.32, R * (0.65 + shown * 0.35), a + '99');
    blob(cx + Math.cos(t * speed * 0.7 + 2) * R * 0.42, cy + Math.sin(t * speed * 1.1 + 1) * R * 0.36, R * (0.55 + shown * 0.3), b + '80');
    ctx.globalCompositeOperation = 'source-over';
    const shine = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.45, 0, cx - R * 0.35, cy - R * 0.45, R * 0.7);
    shine.addColorStop(0, 'rgba(255,255,255,0.55)'); shine.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = shine; ctx.fillRect(0, 0, w, h);
    ctx.restore();
  }
  function loop(now) {
    frame = 0;
    if (disposed) return;
    draw(now);
    if (visible && !document.hidden && !reduced.matches) frame = requestAnimationFrame(loop);
  }
  function sync() { if (frame) cancelAnimationFrame(frame); frame = requestAnimationFrame(loop); }
  const resize = new ResizeObserver(() => sync());
  resize.observe(holder);
  const intersection = new IntersectionObserver((entries) => { visible = entries[0]?.isIntersecting ?? true; sync(); }, { rootMargin: '32px' });
  intersection.observe(holder);
  document.addEventListener('visibilitychange', sync);
  reduced.addEventListener('change', sync);
  sync();
  const ready = Promise.resolve({ renderer: true });
  queueMicrotask(() => host.dispatchEvent(new CustomEvent('agents-orb-ready', { detail: { renderer: 'canvas' } })));

  return {
    ready,
    setState(next) {
      if (disposed || !states.has(next)) return;
      state = next; level = null; holder.dataset.state = state; sync();
    },
    setLevel(value) {
      if (disposed) return;
      level = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    },
    destroy() {
      if (disposed) return;
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      resize.disconnect(); intersection.disconnect();
      document.removeEventListener('visibilitychange', sync);
      reduced.removeEventListener('change', sync);
      holder.remove();
    },
  };
}
