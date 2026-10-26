// One viewport for matching, refining and inspecting. The browsing page keeps its scroll position.
export function createSearchWorkspace({stage,dock,onClose,onSaved,onOpen}) {
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const stageHome=document.createComment('result-stage-home'),dockHome=document.createComment('composer-home');
  stage.before(stageHome);dock.before(dockHome);
  const root=make('section','search-workspace');root.hidden=true;root.setAttribute('role','dialog');root.setAttribute('aria-modal','true');root.setAttribute('aria-label','Your matching homes');
  const header=make('header','workspace-header');const back=make('button','workspace-back','Back to browsing');back.type='button';back.addEventListener('click',()=>onClose());
  const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');const use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href','#i-close');arrow.append(use);arrow.setAttribute('aria-hidden','true');back.prepend(arrow);
  const identity=make('span','workspace-identity','Your search');const actions=make('div','workspace-actions');const compareSlot=make('div','workspace-compare');const saved=make('button','workspace-saved','Saved');saved.type='button';saved.addEventListener('click',onSaved);actions.append(compareSlot,saved);header.append(back,identity,actions);
  const criteria=make('div','workspace-criteria');criteria.setAttribute('aria-label','Your search criteria');
  const note=make('p','workspace-note');note.hidden=true;
  const scroll=make('div','workspace-scroll');
  const footer=make('div','workspace-footer');const floatingSlot=make('div','workspace-floating');
  root.append(header,criteria,note,scroll,footer,floatingSlot);document.body.append(root);
  let opened=false,restoreFocus=null,savedScroll={x:0,y:0},priorInert=[];
  function open(){
    if(opened)return;
    opened=true;restoreFocus=document.activeElement;savedScroll={x:scrollX,y:scrollY};
    priorInert=[document.querySelector('.topbar'),document.querySelector('main'),document.querySelector('body>footer')].filter(Boolean).map(element=>({element,inert:element.inert}));
    scroll.append(stage);footer.append(dock);root.hidden=false;document.body.classList.add('search-workspace-open');
    priorInert.forEach(({element})=>{element.inert=true;});scroll.scrollTop=0;onOpen?.(floatingSlot,compareSlot);
    if(!reduced.matches)root.animate([{opacity:0},{opacity:1}],{duration:260,easing:'cubic-bezier(.16,1,.3,1)'});
  }
  function close({restore=true}={}){
    if(!opened)return;opened=false;
    stageHome.after(stage);dockHome.after(dock);root.hidden=true;document.body.classList.remove('search-workspace-open');
    priorInert.forEach(({element,inert})=>{element.inert=inert;});priorInert=[];
    window.scrollTo({left:savedScroll.x,top:savedScroll.y,behavior:'instant'});
    if(restore&&restoreFocus?.isConnected&&!restoreFocus.closest('[hidden]'))restoreFocus.focus({preventScroll:true});
  }
  root.addEventListener('keydown',event=>{
    if(document.querySelector('dialog[open]'))return;
    if(event.key==='Escape'){event.preventDefault();onClose();return;}
    if(event.key!=='Tab')return;
    const nodes=[...root.querySelectorAll('button:not([disabled]),input:not([disabled]),a[href],select,[tabindex="0"]')].filter(n=>!n.closest('[hidden]')&&n.getBoundingClientRect().width>0&&getComputedStyle(n).visibility!=='hidden');
    const first=nodes[0],last=nodes.at(-1);
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===root)){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
  });
  const syncViewport=()=>{const v=window.visualViewport;root.style.setProperty('--workspace-keyboard-offset',(v?Math.max(0,innerHeight-v.height-v.offsetTop):0)+'px');};
  window.visualViewport?.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('scroll',syncViewport);syncViewport();
  return {root,criteria,compareSlot,floatingSlot,open,close,isOpen:()=>opened,
    setBusy(value){root.classList.toggle('workspace-updating',value);root.setAttribute('aria-busy',String(value));},
    setNote(value){note.textContent=value;note.hidden=!value;},
    focus(){const target=stage.querySelector('h2')||back;if(target.tagName==='H2')target.tabIndex=-1;target.focus({preventScroll:true});},
    resetPosition(){scroll.scrollTop=0;},
    destroy(){window.visualViewport?.removeEventListener('resize',syncViewport);window.visualViewport?.removeEventListener('scroll',syncViewport);close();root.remove();stageHome.remove();dockHome.remove();}
  };
}

export function renderCriteriaBar(host,tokens,{onEdit,onRemove,limit=4}) {
  if(!host)return;host.replaceChildren();host.hidden=!tokens.length;
  for(const token of tokens.slice(0,limit)){
    const chip=document.createElement('span');chip.className='criterion-chip';
    const edit=document.createElement('button');edit.type='button';edit.className='criterion-edit';edit.textContent=token.label;edit.setAttribute('aria-label','Edit '+token.label);edit.addEventListener('click',()=>onEdit(token));
    const remove=document.createElement('button');remove.type='button';remove.className='criterion-remove';remove.textContent='×';remove.setAttribute('aria-label','Remove '+token.label);remove.addEventListener('click',()=>onRemove(token));chip.append(edit,remove);host.append(chip);
  }
  if(tokens.length>limit){const more=document.createElement('button');more.type='button';more.className='criterion-more';more.textContent=`+${tokens.length-limit}`;more.setAttribute('aria-label',`Edit all ${tokens.length} criteria`);more.addEventListener('click',()=>onEdit(null));host.append(more);}
}
