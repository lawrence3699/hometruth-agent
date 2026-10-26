/**
 * Shopify Design masonry / card-slide-in study, inspected 2026-10-25.
 * Copied: scale 1.5 → 1 (mobile 1.15), expo (.16,1,.3,1), 5% opacity
 * arrival, 1.5/1.7/1.9/2.1 s durations and zero scroll-triggered delay.
 * Adapted: ±350 px / (300 + column-row*100) px at a 432 px card width;
 * mobile uses its observed 120 px vertical travel, without lateral spread.
 * A stationary article is the observer/masonry anchor. Its inner surface
 * moves, preserving DOM order and the original buttons and their handlers.
 */
const instances = new WeakMap();
const EASE = 'cubic-bezier(.16,1,.3,1)';
const DURATIONS = [1500,1700,1900,2100];
const ROW_UNIT = 8;

export function setupCollectionMotion(grid) {
  if (!grid) return {refresh(){},destroy(){}};
  if (instances.has(grid)) { const current=instances.get(grid);current.refresh();return current; }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const mobile = matchMedia('(max-width: 760px)');
  const section = grid.closest('.explore');
  const records = new Map();
  let frame=0, disposed=false, measuring=false;
  grid.classList.add('collection-motion-grid');
  section?.classList.add('collection-motion-section');

  function settle(record) {
    if (!record) return;
    clearTimeout(record.timer);
    record.played=true;
    record.card.classList.remove('cm-pending','cm-running');
    record.card.classList.add('cm-ready','is-visible');
    record.surface.style.willChange='';
    const animation=record.animation;record.animation=null;
    animation?.cancel();
    intersection.unobserve(record.card);
  }
  function reveal(record) {
    if (!record || record.played || record.animation || disposed) return;
    if (reduced.matches || document.hidden || !record.card.isConnected || record.card.getBoundingClientRect().bottom<=0) {settle(record);return;}
    const transform=`translate3d(${record.x}px,${record.y}px,0) scale(${mobile.matches?1.15:1.5})`;
    record.card.classList.remove('cm-pending');
    record.card.classList.add('cm-running');
    record.surface.style.willChange='transform, opacity';
    try {
      const animation=record.surface.animate([
        {offset:0,opacity:0,transform},
        {offset:.05,opacity:1},
        {offset:1,opacity:1,transform:'translate3d(0,0,0) scale(1)'},
      ],{duration:record.duration,easing:EASE,fill:'both'});
      record.animation=animation;
      record.timer=setTimeout(()=>settle(record),record.duration+450);
      animation.finished.then(()=>{if(record.animation===animation)settle(record);}).catch(()=>{});
    } catch {settle(record);}
  }
  const intersection = new IntersectionObserver(entries=>{
    for(const entry of entries)if(entry.isIntersecting)reveal(records.get(entry.target));
  },{threshold:.01,rootMargin:'0px 0px -3% 0px'});
  const resize = new ResizeObserver(()=>scheduleMeasure());
  const mutation = new MutationObserver(()=>refresh());

  function measure() {
    cancelAnimationFrame(frame);frame=0;
    if(disposed||measuring)return;
    // A detail view may temporarily take the collection out of layout. Keep
    // its last valid spans instead of collapsing all cards to an 8px row.
    if(!grid.isConnected||!grid.clientWidth)return;
    measuring=true;
    const gridStyle=getComputedStyle(grid);
    const columns=mobile.matches?2:3;
    const gap=parseFloat(gridStyle.columnGap)||0;
    const verticalGap=mobile.matches?28:36;
    const ranks=Array(columns).fill(0);
    // Natural surface heights do not include transformed bounds. Updating a
    // row span therefore cannot feed back into its own ResizeObserver height.
    const measurements=[...records.values()].filter(r=>r.card.isConnected).map(record=>{
      const width=record.card.clientWidth;
      const height=record.surface.offsetHeight;
      const span=Math.max(1,Math.ceil((height+verticalGap)/ROW_UNIT));
      return {record,width,span};
    });
    for(const {record,span} of measurements){
      const value=String(span);
      if(record.card.style.getPropertyValue('--cm-row-span')!==value)record.card.style.setProperty('--cm-row-span',value);
    }
    for(const {record,width} of measurements){
      const column=Math.max(0,Math.min(columns-1,Math.round(record.card.offsetLeft/(width+gap))));
      const rank=ranks[column]++;
      const ratio=width/432;
      record.x=mobile.matches?0:(column-(columns-1)/2)*350*ratio;
      record.y=mobile.matches?120:(300+rank*100)*ratio;
      record.duration=DURATIONS[(column*9+rank)%DURATIONS.length];
      record.card.style.setProperty('--cm-enter-x',record.x+'px');
      record.card.style.setProperty('--cm-enter-y',record.y+'px');
      if(!record.observed){record.observed=true;intersection.observe(record.card);}
    }
    measuring=false;
  }
  function scheduleMeasure(){
    if(disposed)return;
    if(document.hidden){measure();return;}
    if(!frame)frame=requestAnimationFrame(measure);
  }
  function removeRecord(record,unwrap=false){
    settle(record);resize.unobserve(record.surface);records.delete(record.card);
    if(unwrap&&record.surface.parentNode===record.card){
      while(record.surface.firstChild)record.card.insertBefore(record.surface.firstChild,record.surface);
      record.surface.remove();
    }
    record.card.classList.remove('cm-pending','cm-running','cm-ready');
    for(const variable of ['--cm-row-span','--cm-enter-x','--cm-enter-y'])record.card.style.removeProperty(variable);
  }
  function refresh(){
    if(disposed)return;
    const cards=[...grid.children].filter(node=>node.matches('.property-card'));
    const current=new Set(cards);
    for(const record of [...records.values()])if(!current.has(record.card))removeRecord(record);
    for(const card of cards){
      if(records.has(card))continue;
      const surface=document.createElement('div');surface.className='collection-card-motion';
      while(card.firstChild)surface.append(card.firstChild);
      card.append(surface);
      const record={card,surface,played:false,observed:false,animation:null,timer:0,x:0,y:120,duration:1700};
      records.set(card,record);
      card.classList.add('cm-pending');
      resize.observe(surface);
      if(reduced.matches||document.hidden)settle(record);
    }
    // Synchronous first measure prevents an auto-row of 8px from briefly
    // stacking unmeasured cards on top of one another after a filter change.
    measure();
  }
  function showAll(){for(const record of records.values())settle(record);}
  function onVisibility(){if(document.hidden)showAll();else scheduleMeasure();}
  function onPreference(){if(reduced.matches)showAll();scheduleMeasure();}
  function onBreakpoint(){showAll();scheduleMeasure();}
  function onFocus(event){const card=event.target.closest('.property-card');if(card)settle(records.get(card));}
  function onImageLoad(){scheduleMeasure();}
  function destroy(){
    if(disposed)return;
    disposed=true;cancelAnimationFrame(frame);
    mutation.disconnect();intersection.disconnect();resize.disconnect();
    for(const record of [...records.values()])removeRecord(record,true);
    grid.classList.remove('collection-motion-grid');section?.classList.remove('collection-motion-section');
    document.removeEventListener('visibilitychange',onVisibility);
    reduced.removeEventListener('change',onPreference);mobile.removeEventListener('change',onBreakpoint);
    grid.removeEventListener('focusin',onFocus);grid.removeEventListener('load',onImageLoad,true);
    instances.delete(grid);
  }
  const controller={refresh,destroy};instances.set(grid,controller);
  document.addEventListener('visibilitychange',onVisibility);
  reduced.addEventListener('change',onPreference);mobile.addEventListener('change',onBreakpoint);
  grid.addEventListener('focusin',onFocus);grid.addEventListener('load',onImageLoad,true);
  resize.observe(grid);mutation.observe(grid,{childList:true});
  refresh();
  document.fonts?.ready.then(()=>{if(!disposed)scheduleMeasure();});
  return controller;
}
