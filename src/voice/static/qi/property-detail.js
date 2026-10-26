// HomeTruth 2026-10-26: qi.home v6 property-detail.js with eight small data edits (gallery / facts / specs / wordmark / heading /
// bond / source lines / footnote) so a listing can bring its own facts; the page, gallery and viewing plan are qi's. See README.md.
// Two more on 10-26: the source lines are grouped per need (home.sourceGroups) and a single portrait photo is shown whole on a
// blurred copy of itself (the frame keeps the photo's ratio, so the card-to-detail flight lands on it exactly).
// 10-27 a.m., "numbers and statuses first, every explanation folded": "Checked" became one line per need (label · status pill ·
// fact of ≤ 8 words · next step) that opens to the evidence (source chip, table · row, read by, photo, grouped by stage), with a
// Style match line when window.HT_STYLE exists; the sun figure got two lines of numbers (sun-figure.js).
// 10-27 p.m., laid out like realestate.com.au / Domain (the renter said the page was badly designed): the photo mosaic (1 big +
// 2 × 2, "+N photos"), a media tab row under it (Photos (n) · Floor plan · 3D plan · Sun | Share · Save), the price in large type,
// the address, an icon spec row, "Available … · Bond …", then the sections in Domain's style (24 px headings, a 1 px rule between):
// Checked (ours, first), Features (three columns, "View all features"), Property description ("Read more"), a grey "HomeTruth says"
// box (rent vs the suburb median, the commute table, the sun hours: only the numbers we have), Sun, and a sticky "Ask the agent"
// card on the right (the three open ask-the-agent lines, the green button, Save). No map, inspections, schools, street or
// neighbourhood blocks: no data behind them. The gallery viewer, the card→detail flight, Save, Share, history and the
// reduced-motion paths are untouched. The Floor plan tab shows the plan in the photo slot; the 3D plan tab appears only when
// window.HT_DOLLHOUSE.available(home) says so (mount(container, home) → handle.destroy() when the tab is left).
// Tolerant of fields that are still on their way from the server: group.short / group.value / group.next, item.stage,
// item.request_id, home.features, listing.commute (read straight from /api/listings, which ui-qi.js does not pass on).
import {FEATURE_GROUPS} from './rental-filters.js?v=6';
import {createDetailPhotoTransition,captureDetailPhoto} from './detail-transition.js?v=6';
import {sunSection} from './sun-figure.js?v=2';  // HomeTruth 10-26: sun and aspect (src/sun/solar.py)
let altSuffix=' — illustrative design photography';  // real listings (home.source) drop the suffix
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const currency=n=>'$'+Number(n).toLocaleString('en-AU');
const typeNames={apartment:'Apartment',house:'House',townhouse:'Townhouse',villa:'Villa'};
const labels=Object.fromEntries(FEATURE_GROUPS.flatMap(g=>g.items));
// the four statuses, in the renter's words (unknown = "to confirm", as on the cards' must-have lines)
const STATUS_WORD={supported:'Supported',inferred:'Inferred',conflict:'Conflict',unknown:'To confirm'};
const STATUS_WORDS=new Set(['yes','likely','clash','?']);  // card shorts that only repeat the status
const STAGE_TITLE={listing:'From the listing',public:'Public data',agent:'From the agent',viewing:'At the viewing',signing:'At signing',other:'Other sources'};
const NEXT_TEXT={ask_agent:'Ask the agent',see_at_viewing:'See at the viewing',check_at_signing:'Check at signing'};
const AREA_NAMES={central:'Central',unsw:'UNSW',cbd:'CBD'};
const HELP_TEXT='One line per thing checked. Each fact is a row in a source table, not the agent’s word for it; open a line for the table and the row.';
const FEATURES_SHOWN=9;   // Domain folds the feature grid after three rows of three
const DESCRIPTION_WORDS=36;  // the "Read more" fold: about three lines of the description
const timberPhotos=[
 ['assets/gallery/home-1-01.jpg','Timber living room and window seat'],
 ['assets/gallery/home-1-02.jpg','Lounge and fireplace'],
 ['assets/gallery/home-1-03.jpg','Coastal window seat'],
 ['assets/gallery/home-1-04.jpg','Living room, wide view'],
];
const barkerPhotos=[
 ['assets/room-2.jpg','Kitchen and dining'],
 ['assets/gallery/home-2-01.jpg','Open-plan living'],
 ['assets/gallery/home-2-02.jpg','Kitchen island'],
 ['assets/gallery/home-2-03.jpg','Covered deck'],
 ['assets/gallery/home-2-04.jpg','Glazed entrance'],
 ['assets/gallery/home-2-05.jpg','Exterior and landscape'],
];
export function galleryFor(home){
 const entries=Array.isArray(home.gallery)&&home.gallery.length?home.gallery:home.id==='home-1'?timberPhotos:home.id==='home-2'?barkerPhotos:home.id==='home-6'?[timberPhotos[2],timberPhotos[3],timberPhotos[1],timberPhotos[0]]:[[home.image,home.title]];
 // These pairs share the exact source photograph in source-manifest.json.
 // Use the card's URL first without adding the same photograph as a new view.
 const identities={'assets/gallery/home-1-01.jpg':'assets/room-1.jpg','assets/gallery/home-1-03.jpg':'assets/room-6.jpg'};
 const identity=src=>identities[src]||src;
 const lead=entries.find(([src])=>identity(src)===identity(home.image));
 const seen=new Set([identity(home.image)]);
 return [{src:home.image,caption:lead?.[1]||home.title},...entries.filter(([src])=>{const key=identity(src);if(seen.has(key))return false;seen.add(key);return true;}).map(([src,caption])=>({src,caption}))];
}
const todaySydney=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Australia/Sydney',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
// "Available 14 Nov" (the year only when it is not this year), "Available now", "Available on request"
function availText(value){if(!value)return 'Available on request';if(value<=todaySydney())return 'Available now';const d=new Date(value+'T12:00:00Z');if(isNaN(d))return `Available ${value}`;const opts={day:'numeric',month:'short',timeZone:'UTC'};if(d.getUTCFullYear()!==Number(todaySydney().slice(0,4)))opts.year='numeric';return 'Available '+new Intl.DateTimeFormat('en-AU',opts).format(d);}
function shortDate(iso){if(!iso)return '';const d=new Date(iso);if(isNaN(d))return String(iso).slice(0,10);return new Intl.DateTimeFormat('en-AU',{day:'numeric',month:'short',timeZone:'Australia/Sydney'}).format(d);}
const cap=s=>{s=String(s||'');return s?s[0].toUpperCase()+s.slice(1):s;};
const sameUrl=(a,b)=>{try{return new URL(a,document.baseURI).href===new URL(b,document.baseURI).href;}catch{return a===b;}};
// the longest clause (cut at , ; : . — before a space) that fits in max words; a hard cut with an ellipsis when even the first clause is longer
function clip(text,max){
 const t=String(text||'').trim().replace(/\s+/g,' ');if(!t)return '';
 const ws=t.split(' ');if(ws.length<=max)return t.replace(/[.;,:]$/,'');
 let best=null;const re=/[,;:.!?—–]\s/g;let m;
 while((m=re.exec(t))){const prefix=t.slice(0,m.index);const n=prefix.split(' ').length;if(n>max)break;if(n>=2)best=prefix;}
 return (best||ws.slice(0,max).join(' '))+'…';
}
// the first whole sentences that fit in max words (the "Read more" fold); a clause cut when the first sentence alone is longer
function lead(text,max){
 const t=String(text||'').trim().replace(/\s+/g,' ');if(!t)return '';
 if(t.split(' ').length<=max)return t;
 let out='';const re=/[^.!?]+[.!?]+(?=\s|$)/g;let m;
 while((m=re.exec(t))){const next=(out+' '+m[0].trim()).trim();if(next.split(' ').length>max)break;out=next;}
 return out||clip(t,max);
}
// the ≤ 8-word fact on a Checked line: group.short, else group.value, else the first evidence sentence clipped; never a word that only repeats the status
function factOf(g){
 let t=[g.short,g.value].map(v=>v==null?'':String(v).trim()).find(v=>v&&!STATUS_WORDS.has(v.toLowerCase()))||'';
 if(!t){const it=(g.items||[]).find(i=>i&&i.text);t=it?String(it.text):'';}
 t=t.replace(/\s+/g,' ').trim();
 const label=String(g.label||'').trim();if(label&&t.toLowerCase().startsWith(label.toLowerCase()+' '))t=t.slice(label.length+1);  // "Rent $850 per week" under the label Rent → "$850 per week"
 t=clip(t,8).replace(/\.$/,'');
 return cap(t);
}
const statusKey=g=>{const k=String(g.key||g.status||'').toLowerCase();return STATUS_WORD[k]?k:'';};
function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function control(cls,text,action){const n=node('button',cls,text);n.type='button';if(action)n.addEventListener('click',action);return n;}
function icon(name){const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('aria-hidden','true');const use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href','#i-'+name);n.append(use);return n;}
// small line icons of our own (the page sprite has bed / bath / heart / close / arrow; it has no car, plan, cube, sun, share or chevron)
const OWN_ICONS={
 car:'M3 13l1.6-4.2A2 2 0 0 1 6.5 7.5h11a2 2 0 0 1 1.9 1.3L21 13M4 13h16v5H4zM6.5 18v2M17.5 18v2M7 15.5h.01M17 15.5h.01',
 photos:'M4 6h16v12H4zM8 14l2.5-3 2 2.5 2-1.5 3 3M15.5 9.5h.01',
 plan:'M4 4h16v16H4zM4 11h7M11 4v7M11 15h9M15 11v9',
 cube:'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
 sun:'M12 4v2M12 18v2M4 12h2M18 12h2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z',
 share:'M12 4v11M8.5 7.5L12 4l3.5 3.5M5 12v7h14v-7',
 chevron:'M6 9l6 6 6-6',
};
function ownIcon(name){const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('viewBox','0 0 24 24');n.setAttribute('aria-hidden','true');n.setAttribute('class','ht-ico');const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',OWN_ICONS[name]);p.setAttribute('fill','none');p.setAttribute('stroke','currentColor');p.setAttribute('stroke-width','1.6');p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');n.append(p);return n;}
function picture(photo,cls,eager=false){const n=node('img',cls);n.src=photo.src;n.alt=photo.caption+altSuffix;n.loading=eager?'eager':'lazy';n.decoding='async';return n;}
function section(title,id,cls){const n=node('section','listing-section'+(cls?' '+cls:''));n.id=id;n.append(node('h2','',title));return n;}
function sep(){return node('span','sep','·');}
// the status pill, the same chip as on the cards (hometruth.css .chip, the sprite's #s-<status>)
function pill(key){const s=node('span','chip '+key);const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','sico');svg.setAttribute('aria-hidden','true');const use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href','#s-'+key);svg.append(use);s.append(svg,document.createTextNode(STATUS_WORD[key]));return s;}
// "1 supported · 6 inferred · 1 conflict · 6 to confirm" over home.sourceGroups (a kind with 0 is left out); null when nothing has a status
function statusBar(groups){
 const n={supported:0,inferred:0,conflict:0,unknown:0};groups.forEach(g=>{const k=statusKey(g);if(k)n[k]++;});
 if(!n.supported&&!n.inferred&&!n.conflict&&!n.unknown)return null;
 const p=node('p','ht-statusbar');let first=true;
 for(const [k,word] of [['supported','supported'],['inferred','inferred'],['conflict','conflict'],['unknown','to confirm']]){if(!n[k])continue;if(!first)p.append(sep());first=false;p.append(node('b','t-'+k,String(n[k])),document.createTextNode(k==='conflict'&&n[k]>1?'conflicts':word));}
 return p;
}
function evidenceItem(it){
 const li=node('li','ht-ev-item');
 li.append(node('p','ht-ev-text',String(it.text||'')));
 const meta=node('p','ht-ev-meta');
 if(it.source)meta.append(node('span','ht-src',it.source));
 if(it.table||it.row)meta.append(node('span','',[it.table,it.row].filter(Boolean).join(' · ')));
 if(it.read_by)meta.append(node('span','',`read by ${it.read_by}`));
 if(it.request_id){const c=node('code','',String(it.request_id));c.title='request_id';meta.append(c);}
 if(it.mock)meta.append(node('span','mock','mock'));
 if(meta.children.length)li.append(meta);
 if(it.image){const a=node('a','ev-photo');a.href=it.image;a.target='_blank';a.rel='noopener';a.title='The photo the model read';const im=node('img');im.src=it.image;im.alt='The listing photo the model read';im.loading='lazy';im.decoding='async';a.append(im);li.append(a);}
 return li;
}
// the folded layer of a Checked line: the evidence rows, under a small stage heading when the server marks stages (listing / public / agent / viewing / signing)
function evidenceList(items){
 const ul=node('ul','ht-row-ev');
 if(!items.length){ul.append(node('li','ht-ev-none','No rows on file for this line yet.'));return ul;}
 const staged=items.some(it=>it&&it.stage&&STAGE_TITLE[it.stage]);
 if(!staged){items.forEach(it=>ul.append(evidenceItem(it)));return ul;}
 for(const stage of ['listing','public','agent','viewing','signing','other']){
  const own=items.filter(it=>(STAGE_TITLE[it.stage]?it.stage:'other')===stage);if(!own.length)continue;
  ul.append(node('li','ht-row-stage',STAGE_TITLE[stage]));own.forEach(it=>ul.append(evidenceItem(it)));
 }
 return ul;
}
// one Checked line: label · status pill · fact (≤ 8 words) · next step (grey, hint on hover); opens to its evidence
function checkRow(g){
 const key=statusKey(g);const d=node('details','ht-row');if(key)d.dataset.status=key;if(g.dim)d.dataset.dim=g.dim;
 const s=node('summary','ht-row-sum');s.append(node('span','ht-row-label',String(g.label||g.dim||'—')));
 if(key)s.append(pill(key));
 const fact=factOf(g);if(fact){const f=node('span','ht-row-fact',fact);f.title=fact;s.append(f);}
 const nx=g.next&&typeof g.next==='object'?g.next:null;
 if(nx&&(nx.text||NEXT_TEXT[nx.kind])){const n=node('span','ht-row-next',String(nx.text||NEXT_TEXT[nx.kind]));if(nx.hint)n.title=String(nx.hint);if(nx.kind)n.dataset.kind=String(nx.kind);s.append(n);}
 const ev=evidenceList(Array.isArray(g.items)?g.items.filter(Boolean):[]);
 if(nx&&(nx.text||NEXT_TEXT[nx.kind]))ev.append(node('li','ht-row-nextline',`Next: ${nx.text||NEXT_TEXT[nx.kind]}${nx.hint?' — '+nx.hint:''}`));  // the hint again, readable without hover (phones)
 d.append(s,ev);
 return d;
}
function helpButton(text){
 const b=control('ht-help','?');b.title=text;b.setAttribute('aria-label','How to read this list');b.setAttribute('aria-expanded','false');
 const pop=node('p','ht-help-pop',text);pop.hidden=true;
 b.addEventListener('click',()=>{pop.hidden=!pop.hidden;b.setAttribute('aria-expanded',String(!pop.hidden));});
 return [b,pop];
}
// the bond, from the rent line of the matrix ("bond $3,400" or "bond 4 weeks"): "Bond $3,400 (4 weeks' rent)"; null when the listing does not say
function bondText(groups,rent){
 const text=(groups.find(g=>g.dim==='A1')||{items:[]}).items.map(i=>i&&i.text||'').join(' ');
 let amount=null,weeks=null;const m1=/bond\s*\$([\d,]+)/i.exec(text),m2=/bond\s+(\d+)\s*weeks?/i.exec(text);
 if(m1)amount=Number(m1[1].replace(/,/g,''));else if(m2)weeks=Number(m2[1]);
 if(amount==null&&weeks==null)return null;
 if(amount==null)amount=weeks*Number(rent);
 if(weeks==null&&rent&&Math.abs(amount/Number(rent)-Math.round(amount/Number(rent)))<0.02)weeks=Math.round(amount/Number(rent));
 return `Bond ${currency(amount)}`+(weeks?` (${weeks} week${weeks===1?'':'s'}' rent)`:'');
}
// rent against the suburb median, from the public_rent row under Rent ("…median asking rent for 2-bedroom places in Kingsford is $830 a week…")
function medianLine(groups,home){
 const it=(groups.find(g=>g.dim==='A1')||{items:[]}).items.find(i=>i&&i.table==='public_rent'&&/median/i.test(i.text||''));if(!it)return null;
 const m=/median[^$]*\$([\d,]+)\s*(?:a|per)\s*week/i.exec(it.text);if(!m)return null;
 const median=Number(m[1].replace(/,/g,'')),rent=Number(home.price);if(!median||!rent)return null;
 const sub=/places in ([A-Za-z' ]+?) is/i.exec(it.text);const suburb=(sub&&sub[1].trim())||home.suburb||'the suburb';
 const beds=home.beds===0?'studio':`${home.beds}-bed`;
 const diff=rent-median;
 return (diff===0?`At the ${suburb} ${beds} median`:`${currency(Math.abs(diff))} ${diff>0?'above':'below'} the ${suburb} ${beds} median`)+` of ${currency(median)} a week`;
}
// the commute table (/api/listings listing.commute: {central:{min, mode, estimate}, …}): "Central 28 min · UNSW 11 min · CBD 33 min by light rail (estimated)"
function commuteLine(commute){
 const rows=commute&&typeof commute==='object'?Object.entries(commute).filter(([,v])=>v&&v.min!=null):[];if(!rows.length)return null;
 const modes=new Set(rows.map(([,v])=>v.mode).filter(Boolean));const one=modes.size===1?[...modes][0]:null;
 const parts=rows.map(([k,v])=>`${AREA_NAMES[k]||cap(k)} ${v.min} min${!one&&v.mode?' by '+v.mode:''}`);
 return parts.join(' · ')+(one?` by ${one}`:'')+(rows.some(([,v])=>v.estimate)?' (estimated)':'');
}
function sunLine(sun){
 const d=sun&&sun.direct||{};const w=d.winter&&d.winter.hours!=null?`21 June: ~${d.winter.hours} h direct sun`:null,s=d.summer&&d.summer.hours!=null?`21 December: ~${d.summer.hours} h`:null;
 return w||s?[w,s].filter(Boolean).join(' · '):null;
}

export function createPropertyDetail({dialog,homes,isSaved,toggleSave,onAsk,onOpen,notify}){
 let current=null,photos=[],viewerPhotos=[],returnFocus=null,ownsHistory=false,viewerIndex=0,viewerMode='focus',touchStart=0;
 let epoch=0,askSerial=0,closePromise=null,expectedCloseEvents=0,historyPending=null,pendingOpen=null,buildSerial=0,alt3d=null;
 let returnScroll={x:0,y:0},returnUrl=location.pathname+location.search,scrollRestoration=null;
 const transition=createDetailPhotoTransition(dialog);
 const viewer=node('dialog','listing-gallery');viewer.setAttribute('aria-label','Property photographs');viewer.tabIndex=-1;document.body.append(viewer);
 dialog.classList.add('listing-dialog');dialog.setAttribute('aria-label','Property details');
 // the listings as the server sends them (features, commute): ui-qi.js's home objects do not carry those two, so they are read here once
 const rawById=new Map();let rawLoaded=false;
 const rawReady=fetch('/api/listings').then(r=>r.ok?r.json():null).then(d=>{((d&&d.listings)||[]).forEach(L=>{if(L&&L.id)rawById.set(L.id,L);});}).catch(()=>{}).finally(()=>{rawLoaded=true;});
 function saveControl(cls='listing-save'){
  const b=control(cls,'',()=>{toggleSave(current.id);refreshSaved();});b.dataset.detailSave=current.id;
  const update=()=>{const saved=isSaved(current.id);b.replaceChildren(icon('heart'),node('span','',saved?'Saved':'Save'));b.setAttribute('aria-pressed',String(saved));b.setAttribute('aria-label',(saved?'Remove saved ':'Save ')+current.area);};b._update=update;update();return b;
 }
 function refreshSaved(){dialog.querySelectorAll('[data-detail-save]').forEach(b=>b._update?.());}
 function share(){const url=new URL(location.href);url.hash='property='+current.id;if(navigator.clipboard?.writeText)navigator.clipboard.writeText(url.href).then(()=>notify('Link copied')).catch(()=>showShare(url.href));else showShare(url.href);}
 function showShare(url){const input=dialog.querySelector('.listing-share-link');input.hidden=false;input.value=url;input.focus();input.select();notify('Copy this link');}
 function matchingImage(element,home=current){
  if(!element?.isConnected||!home)return null;
  const candidates=element.matches?.('img')?[element]:[...element.querySelectorAll('img')];
  const expected=new URL(home.image,document.baseURI).href;
  return candidates.find(image=>(image.currentSrc||image.src)===expected)||null;
 }
 function findReturnPhoto(home=current){
  const direct=matchingImage(returnFocus,home)||matchingImage(returnFocus?.closest?.('[data-home-id]'),home);
  if(captureDetailPhoto(direct))return direct;
  const candidates=[...document.querySelectorAll('[data-home-id]')].filter(card=>card.dataset.homeId===home?.id&&!dialog.contains(card));
  for(const card of candidates){const image=matchingImage(card,home);if(captureDetailPhoto(image))return image;}
  return null;
 }
 function restorePage({focus=true}={}){
  document.body.classList.remove('listing-open');document.querySelector('#orbit')?.removeAttribute('data-detail-open');
  window.scrollTo({left:returnScroll.x,top:returnScroll.y,behavior:'instant'});
  if(focus){const fallback=findReturnPhoto()?.closest('button');const target=returnFocus?.isConnected?returnFocus:fallback;target?.focus?.({preventScroll:true});}
 }
 function restoreScrollMode(){if(scrollRestoration!==null){history.scrollRestoration=scrollRestoration;scrollRestoration=null;}}
 function afterHistoryLayout(){return new Promise(resolve=>{let raf,done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timer);cancelAnimationFrame(raf);resolve();};const timer=setTimeout(finish,90);raf=requestAnimationFrame(()=>{raf=requestAnimationFrame(finish);});});}
 function finishClose(){
  destroy3d();
  if(viewer.open)viewer.close();
  if(dialog.open){expectedCloseEvents++;dialog.close();}
  restorePage();
 }
 function backFromOwnedEntry(){
  let resolve;
  const promise=new Promise(done=>{resolve=done;});
  const pending={promise,resolve,timer:0};historyPending=pending;
  const done=()=>{if(historyPending!==pending)return;historyPending=null;clearTimeout(pending.timer);resolve();};
  pending.done=done;
  pending.timer=setTimeout(()=>{if(location.hash.startsWith('#property='))history.replaceState(history.state,'',returnUrl);done();},350);
  history.back();return promise;
 }
 function close(options={}){
  if(closePromise)return closePromise;
  if(!dialog.open)return Promise.resolve(true);
  if(viewer.open)viewer.close();
  const token=++epoch,fromHistory=options?.fromHistory===true;
  const source=transition.captureCurrent()||captureDetailPhoto(dialog.querySelector('.listing-photo-main img'));
  // The page stays at its original scroll position underneath the modal.
  window.scrollTo({left:returnScroll.x,top:returnScroll.y,behavior:'instant'});
  const target=captureDetailPhoto(findReturnPhoto());
  const leave=transition.close({source,target});
  const task=(async()=>{
   const completed=await leave;
   if(!completed||token!==epoch)return false;
   const goBack=ownsHistory&&!fromHistory;ownsHistory=false;
   finishClose();
   if(goBack)await backFromOwnedEntry();
   else if(!fromHistory)history.replaceState(history.state,'',returnUrl);
   // History traversal may restore its own active element after popstate.
   // Restore our original card only after that browser step has settled.
   await afterHistoryLayout();
   if(token!==epoch)return false;
   restorePage();restoreScrollMode();
   return true;
  })();
  closePromise=task;
  task.finally(()=>{if(closePromise===task)closePromise=null;});
  return task;
 }
 async function ask(question){
  const home=current,request=++askSerial;
  const closing=close(),token=epoch;
  const completed=await closing;
  if(completed&&request===askSerial&&token===epoch&&!dialog.open)await onAsk(home,question);
 }
 // the Style match line (style-match.js, a soft preference): window.HT_STYLE.get(id) → {score, reasons, misses, status, basis}; null when there is no provider or no verdict
 function styleRow(){
  const api=window.HT_STYLE;if(!api||typeof api.get!=='function'||!current)return null;
  let s=null;try{s=api.get(current.id);}catch{return null;}
  if(!s||typeof s!=='object'||typeof s.then==='function')return null;  // no verdict yet (or a promise: not this contract)
  const key=STATUS_WORD[String(s.status||'').toLowerCase()]?String(s.status).toLowerCase():'inferred';
  const score=Number(s.score);const pct=s.score==null||isNaN(score)?null:Math.round(score<=1&&!Number.isInteger(score)?score*100:score);  // 0.78 or 78 → 78%
  const reasons=(Array.isArray(s.reasons)?s.reasons:[]).filter(Boolean).map(String),misses=(Array.isArray(s.misses)?s.misses:[]).filter(Boolean).map(String);
  if(pct==null&&!reasons.length&&!misses.length)return null;
  const d=node('details','ht-row ht-row-style');d.dataset.status=key;
  const sum=node('summary','ht-row-sum');sum.append(node('span','ht-row-label','Style match'),pill(key));
  const fact=[pct==null?null:`${pct}%`,reasons.slice(0,2).join(', ')||null].filter(Boolean).join(' · ');if(fact){const f=node('span','ht-row-fact',fact);f.title=fact;sum.append(f);}
  const soft=node('span','ht-row-next','Soft preference');soft.title='A soft preference: it never rules a place out';sum.append(soft);
  const ul=node('ul','ht-row-ev');
  if(reasons.length)ul.append(node('li','ht-ev-item',`Matches: ${reasons.join(', ')}`));
  if(misses.length)ul.append(node('li','ht-ev-item',`Misses: ${misses.join(', ')}`));
  if(s.basis)ul.append(node('li','ht-ev-item',`Basis: ${String(s.basis)}`));
  if(!ul.children.length)ul.append(node('li','ht-ev-none','No reasons given.'));
  d.append(sum,ul);return d;
 }
 function refreshStyle(){
  if(!dialog.open||!current)return;const list=dialog.querySelector('.ht-rows');if(!list)return;
  const old=list.querySelector('.ht-row-style'),fresh=styleRow();
  if(old&&fresh){fresh.open=old.open;old.replaceWith(fresh);}else if(old)old.remove();else if(fresh)list.append(fresh);
  list.querySelector('.ht-rows-empty')?.remove();
 }
 document.addEventListener('ht-style-change',refreshStyle);
 /* ---- the media slot: the photo mosaic, or the floor plan / the 3D plan in its place (media tabs) ---- */
 function destroy3d(){const h=alt3d;alt3d=null;if(!h)return;try{if(h&&typeof h.destroy==='function')h.destroy();}catch{}}
 function mosaic(){
  const n=photos.length;const hero=node('div','listing-media '+(n===1?'single-photo':n===2?'two-photos':n<5?'three-photos':'five-photos'));
  const shown=n===1?1:n===2?2:n<5?3:5;
  photos.slice(0,shown).forEach((photo,index)=>{const b=control('listing-photo '+(index===0?'listing-photo-main':''),'',()=>openGallery(index,'focus'));b.setAttribute('aria-label',`Open photo ${index+1}: ${photo.caption}`);b.append(picture(photo,'',index<3));hero.append(b);});
  if(n>shown){const more=control('listing-photo-count',`+${n-shown} photo${n-shown===1?'':'s'}`,()=>openGallery(0,'grid'));more.setAttribute('aria-label',`All ${n} photos`);hero.append(more);}
  if(n===1){hero.style.setProperty('--ht-photo-bg',`url("${photos[0].src}")`);const lead=hero.querySelector('.listing-photo-main img');const fit=()=>{if(lead.naturalWidth&&lead.naturalHeight)hero.style.setProperty('--ht-photo-ratio',`${lead.naturalWidth}/${lead.naturalHeight}`);};if(lead.complete&&lead.naturalWidth)fit();else lead.addEventListener('load',fit,{once:true});}
  return hero;
 }
 function mediaTabs(plan){
  const row=node('div','listing-media-row');const tabs=node('div','listing-media-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Media');
  const tab=(name,text,iconName,action)=>{const b=control('listing-media-tab','',action);b.dataset.view=name;b.setAttribute('aria-pressed','false');b.append(ownIcon(iconName),node('span','',text));return b;};
  tabs.append(tab('photos',`Photos (${photos.length})`,'photos',()=>{if(activeView()==='photos')openGallery(0,'grid');else showView('photos');}));
  if(plan)tabs.append(tab('plan','Floor plan','plan',()=>showView('plan')));
  if(current.sun)tabs.append(tab('sun','Sun','sun',()=>scrollTo('listing-sun')));
  const tools=node('div','listing-media-tools');const sh=control('listing-share','',share);sh.append(ownIcon('share'),node('span','','Share'));tools.append(sh,saveControl());
  row.append(tabs,tools);return row;
 }
 function activeView(){return dialog.querySelector('.listing-media-tab[aria-pressed=true]')?.dataset.view||'photos';}
 function showView(name){
  const hero=dialog.querySelector('.listing-media'),alt=dialog.querySelector('.listing-media-alt');if(!hero||!alt)return;
  if(name!=='threed')destroy3d();
  dialog.querySelectorAll('.listing-media-tab').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===name)));
  alt.replaceChildren();alt.dataset.view=name;
  if(name==='photos'){hero.hidden=false;alt.hidden=true;return;}
  hero.hidden=true;alt.hidden=false;
  if(name==='plan'){
   const plan=current.floorplan&&current.floorplan.url?{src:current.floorplan.url,caption:'Floor plan'}:null;if(!plan)return showView('photos');
   const b=control('listing-plan-open','',()=>openGallery(0,'focus',[plan]));b.setAttribute('aria-label','Open the floor plan');const im=node('img');im.src=plan.src;im.alt='Floor plan';im.decoding='async';b.append(im);alt.append(b);
  }else if(name==='threed'){
   const api=window.HT_DOLLHOUSE;if(!api||typeof api.mount!=='function')return showView('photos');
   const host=node('div','listing-threed');alt.append(host);
   let h=null;try{h=api.mount(host,current);}catch{h=null;}
   alt3d=h;if(h&&typeof h.then==='function'){const token=buildSerial;h.then(real=>{if(token===buildSerial&&alt3d===h)alt3d=real;else{try{real&&typeof real.destroy==='function'&&real.destroy();}catch{}}},()=>{});}
  }
 }
 // the 3D plan tab: only once window.HT_DOLLHOUSE.available(home) has said yes (the module may not be on the page at all)
 async function offerThreed(){
  const api=window.HT_DOLLHOUSE;if(!api||typeof api.available!=='function'||typeof api.mount!=='function')return;
  const token=buildSerial;let ok=false;try{ok=await api.available(current);}catch{ok=false;}
  if(!ok||token!==buildSerial||!dialog.open)return;
  const tabs=dialog.querySelector('.listing-media-tabs');if(!tabs||tabs.querySelector('[data-view=threed]'))return;
  const b=control('listing-media-tab','',()=>showView('threed'));b.dataset.view='threed';b.setAttribute('aria-pressed','false');b.append(ownIcon('cube'),node('span','','3D plan'));
  const after=tabs.querySelector('[data-view=plan]')||tabs.querySelector('[data-view=photos]');after.after(b);
 }
 function scrollTo(id){dialog.querySelector('#'+id)?.scrollIntoView({behavior:reduced.matches?'instant':'smooth',block:'start'});}
 /* ---- the sections ---- */
 function header(groups){
  const head=node('header','listing-head');head.id='listing-overview';  // ui-qi.js's addCheckSection inserts "Checked against what you need" after this id
  const price=node('p','ht-price');price.append(node('b','',currency(current.price)),document.createTextNode(' per week'));head.append(price);
  const addr=[current.title||current.area?.split(',')[0]||'',current.addressLine||(current.postcode?`Sydney NSW ${current.postcode}`:'')].filter(Boolean).join(', ');
  head.append(node('h1','ht-addr',addr));
  const specs=node('ul','ht-specs');
  const spec=(iconNode,value,label)=>{const li=node('li');li.setAttribute('aria-label',`${value} ${label}`);li.title=`${value} ${label}`;li.append(iconNode,node('span','',String(value)));specs.append(li);};
  if(current.beds===0){const li=node('li');li.append(icon('q-bed'),node('span','','Studio'));specs.append(li);}else if(current.beds!=null)spec(icon('q-bed'),current.beds,current.beds===1?'bedroom':'bedrooms');
  if(current.baths!=null)spec(icon('q-bath'),current.baths,current.baths===1?'bathroom':'bathrooms');
  if(current.cars)spec(ownIcon('car'),current.cars,current.cars===1?'car space':'car spaces');
  if(current.type&&typeNames[current.type])specs.append(node('li','ht-type',typeNames[current.type]));
  if(specs.children.length)head.append(specs);
  const terms=[availText(current.available),bondText(groups,current.price)].filter(Boolean);
  const t=node('p','ht-terms');terms.forEach((x,i)=>{if(i)t.append(sep());t.append(node('span','',x));});head.append(t);
  if(current.source){const src=current.source;const site=src.site==='domain.com.au'?'Domain':(src.site||'Listing');const parts=[`${site} listing${src.listing_id?' '+src.listing_id:''}`];const fetched=shortDate(src.fetched_at);if(fetched)parts.push(`fetched ${fetched}`);head.append(node('p','ht-provenance',parts.join(' · ')));}
  return head;
 }
 function checkedSection(groups){
  const checked=section('Checked','listing-features','listing-checked');  // id kept from "What the sources say." so scripts/ui_screenshots.py still finds it
  const [help,helpPop]=helpButton(HELP_TEXT);checked.querySelector('h2').append(help);checked.append(helpPop);
  const bar=statusBar(groups);if(bar)checked.append(bar);
  const rows=node('div','ht-rows');groups.forEach(g=>rows.append(checkRow(g)));const st=styleRow();if(st)rows.append(st);
  if(!rows.children.length)rows.append(node('p','listing-muted ht-rows-empty','Nothing on file for this place yet.'));
  checked.append(rows);return checked;
 }
 // "Everything we checked" when ui-qi.js has put the renter's own checked lines above (otherwise plain "Checked"); runs after open(), once that section is in
 function retitle(){const h=dialog.querySelector('#listing-features>h2');if(!h)return;const own=dialog.querySelector('#listing-check .listing-rows');h.firstChild.nodeValue=own?'Everything we checked':'Checked';}
 function featuresSection(feats){
  if(!feats.length)return null;
  const sec=section('Features','listing-amenities');const grid=node('ul','ht-features');
  feats.forEach((f,i)=>{const li=node('li','',labels[f]||cap(String(f)));if(i>=FEATURES_SHOWN)li.hidden=true;grid.append(li);});sec.append(grid);
  if(feats.length>FEATURES_SHOWN){const b=control('listing-text-link ht-more','',null);const t=node('span','','View all features');b.append(t,ownIcon('chevron'));b.setAttribute('aria-expanded','false');
   b.addEventListener('click',()=>{const open=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',String(open));t.textContent=open?'Show fewer':'View all features';grid.querySelectorAll('li').forEach((li,i)=>{li.hidden=!open&&i>=FEATURES_SHOWN;});});sec.append(b);}
  return sec;
 }
 function descriptionSection(){
  const text=String(current.description||'').replace(/\s+/g,' ').trim();if(!text)return null;
  const real=!!current.source;const sec=section(real?'Property description':'Of note','listing-description');
  const p=node('p','ht-description');const short=real?lead(text,DESCRIPTION_WORDS):text;p.textContent=short;sec.append(p);
  if(short!==text){const b=control('listing-text-link ht-more','',null);const t=node('span','','Read more');b.append(t,ownIcon('chevron'));b.setAttribute('aria-expanded','false');
   b.addEventListener('click',()=>{const open=b.getAttribute('aria-expanded')!=='true';b.setAttribute('aria-expanded',String(open));t.textContent=open?'Read less':'Read more';p.textContent=open?text:short;});sec.append(b);}
  return sec;
 }
 function saysBox(groups,raw){
  const lines=[['Rent',medianLine(groups,current)],['Commute',commuteLine(raw&&raw.commute)],['Sun',sunLine(current.sun)]].filter(([,v])=>v);
  if(!lines.length)return null;
  const box=node('aside','ht-says');box.setAttribute('aria-label','HomeTruth says');box.append(node('p','ht-says-label','HomeTruth says'));
  const dl=node('dl');lines.forEach(([k,v])=>{const row=node('div');row.append(node('dt','',k),node('dd','',v));dl.append(row);});box.append(dl);
  return box;
 }
 function agentCard(groups){
  const card=node('div','ht-agent-card');card.append(node('h2','','Ask the agent'));
  const open=groups.filter(g=>g.next&&typeof g.next==='object'&&g.next.kind==='ask_agent').slice(0,3);
  if(open.length){const ul=node('ul','ht-ask-list');open.forEach(g=>{const li=node('li');li.append(node('b','',String(g.label||g.dim||'')),document.createTextNode(' '),node('span','',String(g.next.hint||g.next.text||NEXT_TEXT.ask_agent)));ul.append(li);});card.append(ul);}
  else card.append(node('p','listing-muted','Nothing left to ask the agent.'));
  card.append(control('primary-button listing-ask','Ask about this home',()=>ask('Tell me more about this home')));
  const tools=node('div','ht-card-tools');tools.append(saveControl('listing-save ht-card-save'));card.append(tools);
  return card;
 }
 function anchorNav(ids){
  const nav=node('nav','listing-anchor-nav');nav.setAttribute('aria-label','Property sections');
  ids.forEach(([id,text])=>{if(dialog.querySelector('#'+id))nav.append(control('',text,()=>scrollTo(id)));});
  return nav;
 }
 function build(){
  const token=++buildSerial;destroy3d();
  const all=galleryFor(current);const planUrl=current.floorplan&&current.floorplan.url?current.floorplan.url:null;
  photos=planUrl?all.filter(p=>!sameUrl(p.src,planUrl)):all;if(!photos.length)photos=all;  // the plan has its own tab; it is not a photo
  altSuffix=current.source?'':' — illustrative design photography';dialog.replaceChildren();
  const bar=node('div','listing-bar');const back=control('listing-back','',close);back.append(icon('close'),node('span','','Back'));const brand=node('span','listing-wordmark','HomeTruth');const barTools=node('div','listing-bar-actions');const barShare=control('listing-share','',share);barShare.setAttribute('aria-label','Share');barShare.title='Share';barShare.append(ownIcon('share'));barTools.append(barShare,saveControl('listing-save listing-bar-save'));bar.append(back,brand,barTools);  // phones: Share / Save as icons in the top bar (the media row's pair is hidden there)
  const shareInput=node('input','listing-share-link');shareInput.readOnly=true;shareInput.hidden=true;shareInput.setAttribute('aria-label','Property share link');
  const scroll=node('div','listing-scroll');
  const hero=mosaic();const alt=node('div','listing-media-alt');alt.hidden=true;
  const mediaRow=mediaTabs(!!planUrl);
  const sourceGroups=Array.isArray(current.sourceGroups)?current.sourceGroups.filter(Boolean):Array.isArray(current.sourceLines)?current.sourceLines.map(l=>({label:l.label,items:[{text:l.text,table:l.table,row:l.row}]})):[];
  const raw=rawById.get(current.id)||null;
  const body=node('div','listing-body');const main=node('div','listing-main');
  main.append(header(sourceGroups),checkedSection(sourceGroups));
  const place=(raw)=>{  // the two blocks that need the server's own listing row (features, commute); placed now, or when /api/listings arrives
   const feats=(Array.isArray(current.features)&&current.features.length?current.features:(raw&&Array.isArray(raw.features)?raw.features:[])).filter(Boolean);
   main.querySelector('#listing-amenities')?.remove();main.querySelector('.ht-says')?.remove();
   const f=featuresSection(feats);if(f)main.querySelector('#listing-features').after(f);
   const d=main.querySelector('#listing-description');const s=saysBox(sourceGroups,raw);if(s)(d||f||main.querySelector('#listing-features')).after(s);
   const nav=anchorNav([['listing-features','Checked'],['listing-amenities','Features'],['listing-description',current.source?'Description':'Of note'],['listing-sun','Sun']]);
   const old=scroll.querySelector('.listing-anchor-nav');if(old)old.replaceWith(nav);else mediaRow.after(nav);
  };
  const desc=descriptionSection();if(desc)main.append(desc);
  if(current.sun)main.append(sunSection(current));  // HomeTruth 10-26: the sun figure (sun-figure.js)
  const aside=node('aside','listing-aside');aside.append(agentCard(sourceGroups));
  body.append(main,aside);
  const foot=node('div','listing-footnote');
  if(current.source){const src=current.source;const site=src.site==='domain.com.au'?'Domain':(src.site||'Listing');const parts=[`${site} listing${src.listing_id?' '+src.listing_id:''}`];const fetched=shortDate(src.fetched_at);if(fetched)parts.push(`fetched ${fetched}`);parts.push(`photos © ${src.agency||'the agency'}`);foot.append(node('span','',parts.join(' · ')));}
  else foot.append(node('span','','Synthetic listing · illustrative photo'));
  const mobile=node('div','listing-mobile-action');mobile.append(control('primary-button','Ask about this home',()=>ask('Tell me more about this home')));
  scroll.append(hero,alt,mediaRow,body,foot);dialog.append(bar,shareInput,scroll,mobile);
  place(raw);showView('photos');
  if(!rawLoaded)rawReady.then(()=>{if(token===buildSerial&&dialog.open)place(rawById.get(current.id)||null);});
  offerThreed();
  queueMicrotask(retitle);
 }
 function open(home,trigger,fromHistory=false){
  if(!home)return;
  if(historyPending&&!fromHistory){
   const request={home,trigger,token:++epoch};pendingOpen=request;askSerial++;
   historyPending.promise.then(()=>{if(pendingOpen===request&&epoch===request.token){pendingOpen=null;open(home,trigger,false);}});
   return;
  }
  const wasOpen=dialog.open;
  const token=++epoch;askSerial++;closePromise=null;pendingOpen=null;
  const initiator=trigger||(!wasOpen?document.activeElement:null);
  let source=captureDetailPhoto(matchingImage(initiator,home)||matchingImage(initiator?.closest?.('[data-home-id]'),home));
  if(!source&&!wasOpen){
   const candidate=[...document.querySelectorAll('[data-home-id]')].find(card=>card.dataset.homeId===home.id&&captureDetailPhoto(matchingImage(card,home)));
   source=captureDetailPhoto(matchingImage(candidate,home));
  }
  transition.cancel();onOpen?.(home);
  if(viewer.open)viewer.close();
  if(!wasOpen){
   returnScroll={x:window.scrollX,y:window.scrollY};
   returnUrl=location.hash.startsWith('#property=')?location.pathname+location.search:location.pathname+location.search+location.hash;
   returnFocus=trigger||document.activeElement;
   if(scrollRestoration===null)scrollRestoration=history.scrollRestoration;
   history.scrollRestoration='manual';
  }else if(trigger)returnFocus=trigger;
  current=home;build();
  document.body.classList.add('listing-open');document.querySelector('#orbit')?.setAttribute('data-detail-open','true');
  if(!dialog.open)dialog.showModal();dialog.querySelector('.listing-scroll').scrollTop=0;
  if(!fromHistory){
   const method=wasOpen?'replaceState':'pushState';history[method]({...history.state,qiProperty:home.id},'',`#property=${home.id}`);ownsHistory=true;
  }
  const target=captureDetailPhoto(dialog.querySelector('.listing-photo-main img'));
  if(target)target.zoom=1;
  transition.open({source,target}).then(()=>{if(token===epoch&&dialog.open)dialog.removeAttribute('aria-busy');});
 }
 function renderGallery(){
  const set=viewerPhotos;
  viewer.replaceChildren();viewer.classList.toggle('gallery-grid-mode',viewerMode==='grid');
  const head=node('div','gallery-bar');const back=control('gallery-back','',()=>{if(viewerMode==='focus'&&set.length>1){viewerMode='grid';renderGallery();}else viewer.close();});back.append(icon('close'),node('span','',viewerMode==='focus'&&set.length>1?'All photos':'Back to property'));head.append(back,node('span','gallery-counter',viewerMode==='focus'?`${viewerIndex+1} / ${set.length}`:`${set.length} photos`),control('gallery-close','Close',()=>viewer.close()));viewer.append(head);
  if(viewerMode==='grid'){
   const grid=node('div','gallery-contact-sheet');set.forEach((photo,index)=>{const b=control('','',()=>{viewerIndex=index;viewerMode='focus';renderGallery();});b.setAttribute('aria-label',`View photo ${index+1}: ${photo.caption}`);b.append(picture(photo,'',true),node('span','',photo.caption));grid.append(b);});viewer.append(grid);
  }else{
   const stage=node('div','gallery-stage');const image=picture(set[viewerIndex],'gallery-focus-image',true);stage.append(image);
   if(set.length>1){const prev=control('gallery-step previous','',()=>step(-1));prev.setAttribute('aria-label','Previous photo');prev.append(icon('close'));const next=control('gallery-step next','',()=>step(1));next.setAttribute('aria-label','Next photo');next.append(icon('arrow'));stage.append(prev,next);}
   stage.addEventListener('pointerdown',e=>{touchStart=e.clientX;});stage.addEventListener('pointerup',e=>{if(Math.abs(e.clientX-touchStart)>45)step(e.clientX<touchStart?1:-1);});
   const strip=node('div','gallery-thumbs');set.forEach((photo,index)=>{const b=control(index===viewerIndex?'active':'','',()=>{viewerIndex=index;renderGallery();});b.setAttribute('aria-label',`Photo ${index+1}`);b.setAttribute('aria-pressed',String(index===viewerIndex));b.append(picture(photo,'',true));strip.append(b);});viewer.append(stage,node('p','gallery-caption',set[viewerIndex].caption),strip);
   if(!reduced.matches)image.animate([{opacity:.5,transform:'scale(1.012)'},{opacity:1,transform:'scale(1)'}],{duration:300,easing:'ease-out'});
  }
  if(viewer.open)viewer.focus({preventScroll:true});
 }
 function step(direction){viewerIndex=(viewerIndex+direction+viewerPhotos.length)%viewerPhotos.length;renderGallery();}
 function openGallery(index,mode,set=photos){viewerPhotos=set;viewerIndex=Math.min(index,set.length-1);viewerMode=set.length>1?mode:'focus';renderGallery();viewer.showModal();}
 dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
 dialog.addEventListener('close',()=>{
  if(expectedCloseEvents){expectedCloseEvents--;return;}
  epoch++;askSerial++;transition.cancel();closePromise=null;destroy3d();
  restorePage();restoreScrollMode();
  if(ownsHistory){ownsHistory=false;history.replaceState(history.state,'',returnUrl);}
 });
 dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();});
 viewer.addEventListener('keydown',event=>{if(viewerMode==='focus'&&(event.key==='ArrowRight'||event.key==='ArrowLeft')){event.preventDefault();step(event.key==='ArrowRight'?1:-1);}});
 window.addEventListener('popstate',()=>{
  if(historyPending){historyPending.done();return;}
  const id=new URLSearchParams(location.hash.slice(1)).get('property');const home=homes.find(h=>h.id===id);
  if(home){ownsHistory=!!history.state?.qiProperty;open(home,null,true);}
  else{ownsHistory=false;if(dialog.open)close({fromHistory:true});else restoreScrollMode();}
 });
 const initialId=new URLSearchParams(location.hash.slice(1)).get('property');const initialHome=homes.find(h=>h.id===initialId);if(initialHome){ownsHistory=!!history.state?.qiProperty;queueMicrotask(()=>open(initialHome,null,true));}
 return {open,close,refreshSaved,refreshStyle};
}
