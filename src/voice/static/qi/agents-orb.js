/**
 * Standalone adapter for the existing ElevenLabs Agents marketing Orb.
 * The original PNG, texture, fluid simulation and shaders are retained.
 * Provenance and exact adaptations: assets/elevenlabs/orb-source-manifest.json.
 * This module never starts audio capture, a call, or a remote agent session.
 */
const asset = name => new URL(`./assets/elevenlabs/${name}`, import.meta.url).href;
const states = new Set(['idle', 'listening', 'thinking', 'speaking', 'error']);

export function createAgentsOrb(host) {
  if (!host || host.nodeType !== 1) throw new TypeError('createAgentsOrb requires a DOM element');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const holder = document.createElement('span');
  holder.className = 'agents-original-orb';
  holder.dataset.state = 'idle';
  holder.dataset.renderer = 'loading';
  holder.setAttribute('aria-hidden', 'true');
  holder.style.cssText = 'position:relative;display:block;width:100%;height:100%;overflow:hidden;border-radius:50%;isolation:isolate;pointer-events:none';
  if (!(parseFloat(getComputedStyle(host).height) > 0)) holder.style.width = holder.style.height = '160px';
  const fallback = document.createElement('img');
  fallback.src = asset('orb-agents-2.png');
  fallback.alt = '';
  fallback.width = fallback.height = 512;
  fallback.decoding = 'async';
  fallback.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;border-radius:50%';
  const surface = document.createElement('span');
  surface.style.cssText = 'position:absolute;inset:0;display:block;opacity:0;transition:opacity 400ms ease';
  const grain = document.createElement('span');
  grain.style.cssText = `position:absolute;inset:0;mix-blend-mode:overlay;opacity:.5;image-rendering:pixelated;background-image:url("${asset('orb-noise.png')}");background-size:${devicePixelRatio >= 2 ? 128 : 256}px;pointer-events:none;border-radius:50%`;  // the grain layer clips itself to the circle: Chrome left it square behind the Orb at 160px (overflow+radius on the holder alone did not clip it)
  holder.append(fallback, surface, grain);
  host.append(holder);

  let renderer = null, disposed = false, frame = 0, lastTime = 0, state = 'idle';
  let visible = true, manualLevel = null;
  let pendingLayout = null, resolveDestroyed;
  const destroyedReady = new Promise(resolve => { resolveDestroyed = resolve; });
  function emit(name, detail) { host.dispatchEvent(new CustomEvent(name, { detail })); }
  function hasSize() { return surface.clientWidth > 0 && surface.clientHeight > 0; }
  function canPaint() { return renderer && renderer.loaded && !disposed && !document.hidden && visible && hasSize(); }
  function shouldAnimate() { return canPaint() && !reduced.matches && state !== 'error'; }
  function audioBands(level) { return {low:level, mid:level*.68, high:level*.28, all:level*.74}; }
  function advance(now) {
    frame = 0;
    if (!shouldAnimate()) return;
    const dt = Math.min(.05, Math.max(.001, (now - (lastTime || now - 16.667)) / 1000));
    lastTime = now;
    const phase = now / 1000;
    // UI-state feedback only. Real measured levels can be supplied through setLevel().
    const output = state === 'speaking'
      ? (manualLevel ?? (.18 + .10 * Math.sin(phase*3.6) ** 2 + .06 * Math.sin(phase*7.1) ** 2))
      : state === 'thinking' ? .025 : 0;
    const input = state === 'listening' ? (manualLevel ?? (.08 + .05 * Math.sin(phase*2.4) ** 2)) : 0;
    try {
      renderer.setAudioData(audioBands(output), audioBands(input), dt);
      renderer.update(dt);
      frame = requestAnimationFrame(advance);
    } catch (error) { fail(error); }
  }
  function sync() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    lastTime = 0;
    if (!canPaint()) return;
    try {
      if (shouldAnimate()) frame = requestAnimationFrame(advance);
      else { renderer.setAudioData(null, null, 0); renderer.update(0); }
    } catch (error) { fail(error); }
  }
  function fail(error) {
    if (disposed) return;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    try { renderer?.dispose(); } catch {}
    renderer = null;
    surface.replaceChildren();
    surface.style.opacity = '0';
    holder.dataset.renderer = 'original-image-fallback';
    emit('agents-orb-error', error);
  }
  const resize = new ResizeObserver(() => {
    if (disposed || !hasSize()) return;
    if (pendingLayout) { pendingLayout(true); pendingLayout = null; }
    if (!renderer) return;
    try { renderer.resize(); if (canPaint()) renderer.update(0); } catch (error) { fail(error); }
  });
  resize.observe(surface);
  const intersection = new IntersectionObserver(entries => {
    visible = entries[0]?.isIntersecting ?? true;
    sync();
  }, {rootMargin:'32px'});
  intersection.observe(holder);
  const onVisibility = () => sync();
  const onReduced = () => { surface.style.transitionDuration = reduced.matches ? '0ms' : '400ms'; sync(); };
  document.addEventListener('visibilitychange', onVisibility);
  reduced.addEventListener('change', onReduced);

  const loading = import('./assets/elevenlabs/orb-renderer.js').then(async ({MarketingOrbRenderer}) => {
    if (disposed) return {renderer:false, destroyed:true};
    if (!hasSize()) await new Promise(resolve => { pendingLayout = resolve; });
    if (disposed) return {renderer:false, destroyed:true};
    if (typeof WebGL2RenderingContext === 'undefined') throw new Error('WebGL2 is unavailable');
    renderer = new MarketingOrbRenderer(surface, {animated:false, dpr:Math.min(devicePixelRatio || 1, 2), cornerRadius:Infinity, fadeInDuration:0, saturation:1, exposure:.15});
    // Upstream loadTexture calls playOnce in non-animated mode; guard that late frame too.
    const originalPlayOnce = renderer.playOnce.bind(renderer);
    renderer.playOnce = () => { if (canPaint()) originalPlayOnce(); };
    await renderer.loadTexture(asset('orb-agents-2-texture.jpg'));
    if (disposed) return {renderer:false, destroyed:true};
    const canvas = renderer.gl.canvas;
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
    if (!renderer.gl.getProgramParameter(renderer.program.program, renderer.gl.LINK_STATUS)) throw new Error('Original Orb shader failed to link');
    if (canPaint()) { renderer.setAudioData(null, null, 0); renderer.update(1/60); }
    surface.style.opacity = '1';
    holder.dataset.renderer = 'original-webgl';
    emit('agents-orb-ready', {renderer:'original-webgl'});
    sync();
    return {renderer:true};
  }).catch(error => {
    fail(error);
    return {renderer:false, fallback:'original-image'};
  });
  const ready = Promise.race([loading, destroyedReady]);

  return {
    ready,
    setState(next) {
      if (disposed || !states.has(next)) return;
      state = next;
      manualLevel = null;
      holder.dataset.state = state;
      sync();
    },
    setLevel(value) {
      if (disposed) return;
      manualLevel = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
    },
    destroy() {
      if (disposed) return;
      disposed = true;
      resolveDestroyed({renderer:false, destroyed:true});
      if (pendingLayout) { pendingLayout(false); pendingLayout = null; }
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      resize.disconnect();
      intersection.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      reduced.removeEventListener('change', onReduced);
      try { renderer?.dispose(); } catch {}
      renderer = null;
      holder.remove();
    }
  };
}
