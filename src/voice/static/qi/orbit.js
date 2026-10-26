// Motion study: Augen Pro's isolated subjects, soft depth and restrained reveals.
// Images always use object-fit: cover; no photo is scaled independently on x/y.
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const ease = 'cubic-bezier(.19,1,.22,1)';
let cards = [], host, geometry, frame, lastTime = 0, phase = .34;
let offscreen = false, frozen = false, resizeObserver, visibilityObserver;
let transitionId = 0, prepared = null, watchdog;
let searching = false, searchDepth = 0, velocity = 1;
const animations = new Set();
const layers = new Set();
const hiddenNodes = new Map();

function rectOf(node) {
  if (!node) return null;
  const r = node.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return { left:r.left, top:r.top, width:r.width, height:r.height };
}
function snapshot(node) {
  const rect = rectOf(node);
  if (!rect) return null;
  const style = getComputedStyle(node);
  return { rect, src:node.currentSrc || node.src, position:style.objectPosition || '50% 50%', opacity:Number(style.opacity), naturalWidth:node.naturalWidth, naturalHeight:node.naturalHeight };
}
function hide(node) {
  if (!node || hiddenNodes.has(node)) return;
  hiddenNodes.set(node, node.style.opacity);
  node.style.opacity = '0';
}
function unhide(node) {
  if (!node || !hiddenNodes.has(node)) return;
  node.style.opacity = hiddenNodes.get(node);
  hiddenNodes.delete(node);
}
function cancelMotion() {
  transitionId++;
  clearTimeout(watchdog);
  animations.forEach(animation => animation.cancel());
  animations.clear();
  layers.forEach(layer => layer.remove());
  layers.clear();
  [...hiddenNodes.keys()].forEach(unhide);
  document.querySelector('.hero')?.classList.remove('is-lifting', 'is-switching', 'is-preparing');
}
function animate(node, keyframes, options) {
  const animation = node.animate(keyframes, { fill:'both', ...options });
  animations.add(animation);
  // Keep finished effects registered until the transition is settled. Their
  // fill state must also be cancelled on a repeated query or reset.
  return animation.finished.catch(() => {}).then(() => animation);
}
function removeLayer(layer) { if (layer) { layer.remove(); layers.delete(layer); } }
function settleMotion(turn = transitionId) {
  if (turn !== transitionId) return;
  cancelMotion(); prepared = null; searching = false;
  frozen = !!document.querySelector('.hero')?.classList.contains('has-results');
  lastTime = 0;
}
function guardTurn(turn, duration = 4200) {
  clearTimeout(watchdog);
  watchdog = setTimeout(() => settleMotion(turn), duration);
}
async function bounded(promise, duration) {
  let timer;
  await Promise.race([promise, new Promise(resolve => { timer = setTimeout(resolve,duration); })]);
  clearTimeout(timer);
}
function settleLayout() {
  return new Promise(resolve => {
    let raf, done = false;
    const complete = () => { if(done)return;done=true;clearTimeout(timer);cancelAnimationFrame(raf);resolve(); };
    const timer = setTimeout(complete,100);
    raf = requestAnimationFrame(() => { raf=requestAnimationFrame(complete); });
  });
}
function resumeFrozenLayers(held) {
  held.forEach(layer => { document.body.append(layer); layers.add(layer); });
}
function makeHeldPhoto(photo) {
  const layer = createLayer(photo,'held-subject');
  layer.style.zIndex = '44';
  return layer;
}
function presentationNodes(target) {
  const main = target.closest('.result-main');
  return [
    document.querySelector('.result-heading'),
    main?.querySelector('.result-title-row'),
    main?.querySelector('.result-meta'),
    main?.querySelector('.result-reasons'),
    main?.querySelector('.result-actions') || main?.querySelector('.result-detail-button'),
    ...document.querySelectorAll('.result-mini'),
  ].filter(Boolean);
}

function createLayer(photo, className = '') {
  const layer = document.createElement('div');
  layer.className = 'focus-photo-layer ' + className;
  layer.setAttribute('aria-hidden', 'true');
  Object.assign(layer.style, {
    position:'fixed', zIndex:'45', pointerEvents:'none', overflow:'hidden',
    borderRadius:'10px', margin:'0', transformOrigin:'50% 50%',
    contain:'layout style', willChange:'transform, opacity',
    left:photo.rect.left+'px', top:photo.rect.top+'px',
    width:photo.rect.width+'px', height:photo.rect.height+'px',
  });
  const image = document.createElement('img');
  image.src = photo.src; image.alt = ''; image.draggable = false;
  Object.assign(image.style, { width:'100%', height:'100%', display:'block', objectFit:'cover', objectPosition:photo.position, maxWidth:'none' });
  layer.append(image);
  document.body.append(layer); layers.add(layer);
  return layer;
}
// Freeze the currently composited picture before the application removes its
// DOM. This also preserves a partially completed dissolve on a quick click.
function freezeVisibleLayers() {
  return [...layers].sort((a,b) => Number(a.style.zIndex)-Number(b.style.zIndex)).filter(layer => Number(getComputedStyle(layer).opacity) > .015).slice(-6).map(layer => {
    const copy = layer.cloneNode(true);
    copy.className = 'focus-photo-layer held-subject';
    const oldNodes = [layer, ...layer.querySelectorAll('*')];
    const newNodes = [copy, ...copy.querySelectorAll('*')];
    oldNodes.forEach((node,index) => {
      const style = getComputedStyle(node);
      for (const property of ['transform','opacity','filter','clipPath']) newNodes[index].style[property] = style[property];
    });
    copy.style.zIndex = '44';
    return copy;
  });
}
// A fixed image plane plus a moving crop produces the same cover composition
// as resizing a frame, without changing layout dimensions on every frame.
function coverPlane(layer, photo, to) {
  const image = layer.querySelector('img');
  const ratio = photo.naturalWidth / photo.naturalHeight || to.width / to.height;
  const width = Math.max(to.width, to.height * ratio);
  const height = width / ratio;
  Object.assign(layer.style, {overflow:'visible', clipPath:'inset(0px round 10px)', willChange:'transform, opacity, clip-path'});
  Object.assign(image.style, {position:'absolute', width:width+'px', height:height+'px', left:(to.width-width)/2+'px', top:(to.height-height)/2+'px', objectFit:'cover'});
  return {width,height};
}
function cropAt(rect, to, plane, extraScale = 1, offsetY = 0) {
  const scale = Math.max(rect.width / plane.width, rect.height / plane.height);
  const insetX = (to.width-rect.width/scale)/2;
  const insetY = (to.height-rect.height/scale)/2;
  const x = rect.left + rect.width/2 - to.left - to.width/2;
  const y = rect.top + rect.height/2 - to.top - to.height/2 + offsetY;
  return { transform:`translate3d(${x}px,${y}px,0) scale(${scale*extraScale})`, clipPath:`inset(${insetY}px ${insetX}px ${insetY}px ${insetX}px round ${10/scale}px)` };
}
function grow(rect, amount, y = 0) {
  return { left:rect.left-rect.width*(amount-1)/2, top:rect.top-rect.height*(amount-1)/2+y, width:rect.width*amount, height:rect.height*amount };
}

export function setupOrbit(homes) {
  cancelMotion();
  cancelAnimationFrame(frame);
  resizeObserver?.disconnect(); visibilityObserver?.disconnect();
  host = document.querySelector('#orbit');
  if (!host || !homes.length) return;
  host.replaceChildren();
  cards = homes.map((home, index) => {
    const card = document.createElement('div');
    card.className = 'orbit-card'; card.dataset.homeId = home.id;
    const photo = document.createElement('img');
    photo.src = home.image; photo.alt = ''; photo.draggable = false;
    const label = document.createElement('div'); label.className = 'orbit-card-label';
    const name = document.createElement('span'); name.textContent = home.area.split(',')[0];
    const price = document.createElement('span'); price.textContent = '$' + home.price + '/wk';
    label.append(name,price); card.append(photo,label); host.append(card);
    return { element:card, home, index };
  });
  const resize = () => {
    const w = host.clientWidth, h = host.clientHeight;
    const cw = cards[0].element.offsetWidth;
    const ch = cards[0].element.offsetHeight;
    geometry = { w, h, cw, ch, rx:Math.max(w < 760 ? 225 : 330, Math.min(690,w*.37)), ry:Math.min(135,h*.17), cy:h*.44 };
    draw();
  };
  resizeObserver = new ResizeObserver(resize); resizeObserver.observe(host); resize();
  visibilityObserver = new IntersectionObserver(([entry]) => { offscreen = !entry.isIntersecting; }, {threshold:0});
  visibilityObserver.observe(host);
  lastTime = 0; frozen = false; prepared = null; searching = false; searchDepth = 0; velocity = 1;
  function tick(time) {
    if (lastTime && !reduced.matches && !offscreen && !frozen && !document.hidden && host.dataset.detailOpen !== 'true' && !document.querySelector('.hero')?.classList.contains('has-results')) {
      const dt = Math.min(40,time-lastTime);
      velocity += ((searching ? .055 : 1)-velocity)*(1-Math.exp(-dt/210));
      searchDepth += ((searching ? 1 : 0)-searchDepth)*(1-Math.exp(-dt/260));
      if (host.dataset.paused !== 'true') phase += dt*.000026*velocity;
      draw();
    }
    lastTime=time;
    frame=requestAnimationFrame(tick);
  }
  frame=requestAnimationFrame(tick);
}
function draw() {
  if (!geometry) return;
  const {w,cw,ch,rx,ry,cy}=geometry;
  cards.forEach(({element,index}) => {
    const angle=phase+index*(Math.PI*2/cards.length);
    const depth=(Math.sin(angle)+1)/2;
    const scale=(.58+depth*.35)*(1-searchDepth*.045);
    const x=w/2+Math.cos(angle)*rx-cw/2;
    const y=cy+Math.sin(angle)*ry-ch/2;
    element.style.transform=`translate3d(${x}px,${y}px,0) scale(${scale})`;
    element.style.opacity=String((.16+depth*.64)*(1-searchDepth*.34));
    element.style.filter=`blur(${(1-depth)*1.5+searchDepth*.65}px)`;
    element.style.zIndex=String(Math.round(depth*10));
  });
}

// Start during the matching beat, before results are known. The orbit eases
// down instead of stopping on a frame; an existing subject stays visible while
// gently receding so a follow-up query never creates an empty stage.
export function prepareSearch() {
  if (reduced.matches || document.hidden) { settleMotion(); searching = true; return; }
  const oldMain = document.querySelector('.result-image');
  const oldPhoto = snapshot(oldMain);
  const held = freezeVisibleLayers();
  cancelMotion();
  resumeFrozenLayers(held);
  if (!held.length && oldPhoto) held.push(makeHeldPhoto(oldPhoto));
  if (held.length) {
    hide(oldMain);
    held.forEach(layer => {
      const style = getComputedStyle(layer);
      const transform = style.transform === 'none' ? '' : style.transform;
      animate(layer,[{opacity:Number(style.opacity),transform:style.transform,filter:style.filter},{opacity:Number(style.opacity)*.76,transform:transform+' scale(.988)',filter:'blur(.7px)'}],{duration:540,easing:'cubic-bezier(.25,.1,.3,1)'});
    });
  }
  searching = true;
  frozen = !!oldPhoto;
  document.querySelector('.hero')?.classList.add('is-preparing');
  guardTurn(transitionId,4800);
}

// Call before replacing the result DOM. Capture the existing subject, not stale
// positions from a previous viewport; interrupted transitions resume from pixels.
export function prepareResultTransition(homeId) {
  const oldMain = document.querySelector('.result-image');
  const interrupted = [...layers].find(layer => layer.classList.contains('incoming-subject'));
  const outgoing = interrupted ? snapshot(interrupted.querySelector('img')) : snapshot(oldMain);
  const card = cards.find(item => item.home.id === homeId)?.element;
  const inView=photo=>photo&&photo.rect.top+photo.rect.height>0&&photo.rect.top<innerHeight&&photo.rect.left+photo.rect.width>0&&photo.rect.left<innerWidth;
  const fromGrid=snapshot(document.querySelector(`.property-card[data-home-id="${homeId}"] .property-image`));
  const fromOrbit=snapshot(card?.querySelector('img'));
  const source = inView(fromGrid)?fromGrid:inView(fromOrbit)?fromOrbit:null;
  const held = reduced.matches || document.hidden ? [] : freezeVisibleLayers();
  cancelMotion();
  resumeFrozenLayers(held);
  if (!held.length && outgoing && !reduced.matches && !document.hidden) held.push(makeHeldPhoto(outgoing));
  frozen = true;
  prepared = { homeId, outgoing, source, held, turn:transitionId };
  guardTurn(transitionId);
  return prepared;
}

export async function liftToResult(homeId, target, {fast=false}={}) {
  if (!target || !target.isConnected) return;
  const context = prepared?.homeId === homeId ? prepared : prepareResultTransition(homeId);
  prepared = null;
  const turn = context.turn;
  const hero = document.querySelector('.hero');
  if (reduced.matches || document.hidden) { settleMotion(turn); return; }
  const switching = !!context.outgoing;
  hero?.classList.add(switching ? 'is-switching' : 'is-lifting');
  const content = presentationNodes(target);
  [target,...content].forEach(hide);
  // Neither a slow decode nor a throttled background rAF may strand a hidden
  // result. The old picture remains present during these bounded waits.
  if (!target.complete || !target.naturalWidth) await bounded(target.decode().catch(() => {}),900);
  await settleLayout();
  if (turn !== transitionId) return;
  if (!target.isConnected || document.hidden || reduced.matches) { settleMotion(turn); return; }
  const to = rectOf(target);
  if (!to) { settleMotion(turn); return; }
  const incomingPhoto = { rect:to, src:target.currentSrc || target.src, position:getComputedStyle(target).objectPosition || '50% 50%', naturalWidth:target.naturalWidth || context.source?.naturalWidth, naturalHeight:target.naturalHeight || context.source?.naturalHeight };
  const incoming = createLayer(incomingPhoto, 'incoming-subject');
  let duration;
  let visual;
  if (switching || fast) {
    // A camera-like change of subject within one quiet frame. Secondary photos
    // remain in their own row instead of criss-crossing the screen.
    duration = fast?320:760;
    context.held.forEach(layer => animate(layer, [{opacity:Number(getComputedStyle(layer).opacity)},{opacity:0}], {duration:fast?220:560,easing:'cubic-bezier(.3,0,.3,1)'}));
    visual = animate(incoming, [
      {opacity:0,transform:'scale(1.025)',filter:'blur(2px)',clipPath:'inset(1.2% 1.2% 1.2% 1.2% round 10px)'},
      {opacity:1,transform:'scale(1)',filter:'blur(0)',clipPath:'inset(0% 0% 0% 0% round 10px)'}
    ], {duration,easing:ease});
  } else {
    const source = context.source?.rect || grow(to,.82,18);
    const plane = coverPlane(incoming,incomingPhoto,to);
    const start = cropAt(source,to,plane);
    const focus = cropAt(source,to,plane,1.055,-7);
    const finish = {transform:'translate3d(0,0,0) scale(1)',clipPath:'inset(0px 0px 0px 0px round 10px)'};
    Object.assign(incoming.style,start);
    incoming.style.opacity = '.72';
    const mist = document.createElement('div');
    const paper = getComputedStyle(document.body).backgroundColor || '#fff';
    Object.assign(mist.style, {position:'absolute',inset:'-1px',pointerEvents:'none',background:`linear-gradient(180deg, ${paper}, transparent 17%, transparent 83%, ${paper})`,opacity:'.36'});
    incoming.append(mist);
    duration = 1260;
    visual = (async () => {
      await animate(incoming, [{...start,opacity:.72,filter:'blur(.8px)'},{...focus,opacity:1,filter:'blur(0)'}], {duration:230,easing:'cubic-bezier(.2,.8,.3,1)'});
      if (turn !== transitionId) return;
      // The second effect starts from the exact transform and crop of the
      // focus beat; the underlying bitmap keeps its intrinsic proportions.
      animate(mist,[{opacity:.36},{opacity:0}],{duration:850,easing:ease});
      await animate(incoming,[focus,finish],{duration:1030,easing:ease});
    })();
  }
  const revealDelays = fast?[0,25,40,50,60,80,100]:switching ? [120,230,300,370,420,490,560] : [610,790,880,970,1030,1120,1200];
  const reveals = content.map((node,index) => {
    unhide(node);
    return animate(node,[{opacity:0,transform:`translateY(${index>4?6:8}px)`,filter:'blur(1px)'},{opacity:1,transform:'translateY(0)',filter:'blur(0)'}],{duration:fast?210:390,delay:revealDelays[index]??(fast?100:1200),easing:ease});
  });
  try {
    await visual;
    if (turn !== transitionId) return;
    if (!target.isConnected) { settleMotion(turn); return; }
    unhide(target);
    removeLayer(incoming); context.held.forEach(removeLayer);
    await Promise.all(reveals);
    settleMotion(turn);
  } catch {
    settleMotion(turn);
  }
}

export function resetOrbit() {
  cancelMotion();
  prepared = null;
  frozen = false;
  searching = false; searchDepth = 0; velocity = 1;
  lastTime = 0;
  draw();
}

// Suspend in a final, readable state instead of resuming a stale flight after
// the user returns to the tab. Respect preference changes during a transition.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) settleMotion();
  lastTime = 0;
});
reduced.addEventListener('change', () => {
  if (reduced.matches) settleMotion();
  lastTime = 0;
});
