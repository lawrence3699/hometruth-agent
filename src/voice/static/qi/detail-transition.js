// Shared photograph continuity: the same original bitmap is clipped and
// uniformly scaled between its card and detail frame. No x/y image stretching.
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const ease = 'cubic-bezier(.19,1,.22,1)';
const absolute = src => new URL(src,document.baseURI).href;
const px = value => Number.parseFloat(value)||0;
function visible(rect){return rect&&rect.width>16&&rect.height>16&&rect.right>0&&rect.bottom>0&&rect.left<innerWidth&&rect.top<innerHeight;}
function box(rect){return {left:rect.left,top:rect.top,width:rect.width,height:rect.height,right:rect.right,bottom:rect.bottom};}
function corners(frame){
 const style=getComputedStyle(frame);let values=[style.borderTopLeftRadius,style.borderTopRightRadius,style.borderBottomRightRadius,style.borderBottomLeftRadius].map(px);
 if(frame.classList.contains('listing-photo-main')){
  const media=frame.closest('.listing-media');
  if(media){const s=getComputedStyle(media);values=[px(s.borderTopLeftRadius),media.classList.contains('single-photo')?px(s.borderTopRightRadius):0,media.classList.contains('single-photo')?px(s.borderBottomRightRadius):0,px(s.borderBottomLeftRadius)];}
 }
 return values;
}
export function captureDetailPhoto(value){
 const image=value?.matches?.('img')?value:value?.querySelector?.('img');
 if(!image?.isConnected)return null;
 const frame=image.closest('button')||image;
 const rect=frame.getBoundingClientRect();
 const style=getComputedStyle(image);
 if(!visible(rect)||style.visibility==='hidden'||Number(style.opacity)<.025)return null;
 const imageRect=image.getBoundingClientRect();
 return {element:image,rect:box(rect),src:absolute(image.currentSrc||image.src),width:image.naturalWidth,height:image.naturalHeight,position:style.objectPosition||'50% 50%',zoom:Math.max(.9,imageRect.width/rect.width),radius:corners(frame)};
}
function waitAtMost(promise,ms){let timer;return Promise.race([promise,new Promise(resolve=>{timer=setTimeout(resolve,ms);})]).finally(()=>clearTimeout(timer));}
function layoutReady(){return new Promise(resolve=>{let done=false,raf;const finish=()=>{if(done)return;done=true;clearTimeout(timer);cancelAnimationFrame(raf);resolve();};const timer=setTimeout(finish,90);raf=requestAnimationFrame(()=>{raf=requestAnimationFrame(finish);});});}

export function createDetailPhotoTransition(dialog){
 let active=null,serial=0;
 function end(state,completed){
  if(!state||state.ended)return;
  state.ended=true;clearTimeout(state.timer);
  state.animations.forEach(animation=>animation.cancel());
  state.hidden.forEach((opacity,node)=>{node.style.opacity=opacity;});
  if(state.overlay){try{state.overlay.hidePopover();}catch{}state.overlay.remove();}
  if(active===state){active=null;dialog.classList.remove('pd-transitioning','pd-opening','pd-closing');dialog.removeAttribute('aria-busy');}
  state.resolve(completed);
 }
 function cancel(){serial++;end(active,false);}
 function hide(state,node){if(node?.isConnected&&!state.hidden.has(node)){state.hidden.set(node,node.style.opacity);node.style.opacity='0';}}
 function animate(state,node,frames,options){
  if(!node)return Promise.resolve();
  const animation=node.animate(frames,{fill:'both',...options});state.animations.push(animation);
  return animation.finished.catch(()=>{});
 }
 function makeFlight(state,photo,target){
  const overlay=document.createElement('div');overlay.className='pd-flight-layer';overlay.setAttribute('popover','manual');overlay.setAttribute('aria-hidden','true');document.body.append(overlay);
  if(typeof overlay.showPopover!=='function'){overlay.remove();return null;}
  try{overlay.showPopover();}catch{overlay.remove();return null;}
  const plane=document.createElement('div');plane.className='pd-flight-photo';
  const to=target.rect,ratio=photo.width/photo.height||to.width/to.height;
  const width=Math.max(to.width,to.height*ratio),height=width/ratio;
  Object.assign(plane.style,{left:to.left+'px',top:to.top+'px',width:to.width+'px',height:to.height+'px'});
  const image=document.createElement('img');image.src=photo.src;image.alt='';image.draggable=false;
  Object.assign(image.style,{width:width+'px',height:height+'px',left:(to.width-width)/2+'px',top:(to.height-height)/2+'px'});
  plane.append(image);overlay.append(plane);state.overlay=overlay;state.plane=plane;state.photo=photo;state.planeSize={width,height};state.to=to;
  function pose(at){
   const scale=Math.max(at.rect.width/width,at.rect.height/height)*(at.zoom||1);
   const insetX=(to.width-at.rect.width/scale)/2,insetY=(to.height-at.rect.height/scale)/2;
   const x=at.rect.left+at.rect.width/2-to.left-to.width/2,y=at.rect.top+at.rect.height/2-to.top-to.height/2;
   const radius=(at.radius||[10,10,10,10]).map(n=>n/scale+'px').join(' ');
   return {transform:`translate3d(${x}px,${y}px,0) scale(${scale})`,clipPath:`inset(${insetY}px ${insetX}px ${insetY}px ${insetX}px round ${radius})`};
  }
  return {plane,start:pose(photo),finish:pose(target)};
 }
 function captureCurrent(){
  const state=active;if(!state?.plane||!state.plane.isConnected)return null;
  const rect=state.plane.getBoundingClientRect(),style=getComputedStyle(state.plane);
  const scale=rect.width/state.to.width;
  const raw=(style.clipPath.match(/inset\(([^)]*)\)/)?.[1]||'0 0 0 0').split('round')[0].trim().split(/\s+/).map(px);
  const [top,right=top,bottom=top,left=right]=raw;
  const r={left:rect.left+left*scale,top:rect.top+top*scale,width:rect.width-(left+right)*scale,height:rect.height-(top+bottom)*scale};r.right=r.left+r.width;r.bottom=r.top+r.height;
  const ratio=state.photo.width/state.photo.height||1;
  const coverWidth=Math.max(r.width,r.height*ratio);
  return {...state.photo,element:null,rect:r,zoom:state.planeSize.width*scale/coverWidth,radius:[10,10,10,10]};
 }
 function run(mode,{source,target}){
  const startingOpacity=Number(getComputedStyle(dialog).opacity)||0;
  cancel();
  if(reduced.matches||document.hidden||!dialog.open)return Promise.resolve(true);
  const id=serial;
  return new Promise(resolve=>{
   const state={id,resolve,ended:false,animations:[],hidden:new Map(),overlay:null};active=state;
   dialog.classList.add('pd-transitioning',mode==='open'?'pd-opening':'pd-closing');dialog.setAttribute('aria-busy','true');
   state.timer=setTimeout(()=>end(state,true),2600);
   (async()=>{
    const targetImage=target?.element;
    const main=dialog.querySelector('.listing-photo-main img');
    const siblings=[...dialog.querySelectorAll('.listing-photo:not(.listing-photo-main)')];
    const parts=[dialog.querySelector('.listing-bar'),...siblings,dialog.querySelector('.listing-media-row'),dialog.querySelector('.listing-anchor-nav'),dialog.querySelector('.listing-body'),dialog.querySelector('.listing-mobile-action')].filter(Boolean);
    const possible=source&&target&&source.src===target.src&&visible(source.rect)&&visible(target.rect);
    // Hold the source pixels in the top layer synchronously, before the first
    // paint of showModal(). Waiting for decode/layout must not flash a blank
    // white detail sheet or make the original photograph disappear first.
    const shared=possible?makeFlight(state,source,target):null;
    if(shared)Object.assign(shared.plane.style,shared.start);
    if(possible){hide(state,source.element);hide(state,targetImage);hide(state,main);}
    if(mode==='open'){hide(state,dialog);parts.forEach(node=>hide(state,node));}
    else{state.hidden.set(dialog,dialog.style.opacity);dialog.style.opacity=String(startingOpacity);}
    if(mode==='open'&&targetImage&&(!targetImage.complete||!targetImage.naturalWidth))await waitAtMost(targetImage.decode().catch(()=>{}),650);
    await layoutReady();
    if(state.ended||id!==serial)return;
    if(!shared){[source?.element,targetImage,main].forEach(node=>{if(state.hidden.has(node)){node.style.opacity=state.hidden.get(node);state.hidden.delete(node);}});}
    const tasks=[];
    if(shared){
     tasks.push(animate(state,shared.plane,[shared.start,shared.finish],{duration:mode==='open'?820:620,easing:ease}));
    }
    if(mode==='open'){
     tasks.push(animate(state,dialog,[{opacity:0},{opacity:1}],{duration:shared?330:360,easing:'ease-out'}));
     parts.forEach((part,index)=>{
      if(state.hidden.has(part)){part.style.opacity=state.hidden.get(part);state.hidden.delete(part);}
      tasks.push(animate(state,part,[{opacity:0,transform:'translateY(9px)'},{opacity:1,transform:'translateY(0)'}],{duration:390,delay:shared?190+Math.min(index,6)*55:index*25,easing:ease}));
     });
    }else{
     tasks.push(animate(state,dialog,[{opacity:startingOpacity},{opacity:0}],{duration:shared?480:300,easing:'cubic-bezier(.4,0,.6,1)'}));
    }
    await Promise.all(tasks);end(state,true);
   })().catch(()=>end(state,true));
  });
 }
 function settleHidden(){if(document.hidden)end(active,true);}
 function settleReduced(){if(reduced.matches)end(active,true);}
 document.addEventListener('visibilitychange',settleHidden);reduced.addEventListener('change',settleReduced);
 return {open:options=>run('open',options),close:options=>run('close',options),cancel,captureCurrent,destroy(){cancel();document.removeEventListener('visibilitychange',settleHidden);reduced.removeEventListener('change',settleReduced);}};
}
