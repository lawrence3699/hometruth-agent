import {createAgentsOrb} from './agents-orb.js?v=8';
import {renderCriteriaBar} from './search-workspace.js?v=6';

// Layout and original control icons: ElevenLabs Agents. See DESIGN-SOURCES.md.
// Speech and matching stay in app.js; this module only presents their state.
export function createConversationPanel({onSubmit,onVoiceToggle,onEnd,onTyping,onViewHomes,anchor,orbElement,orbController,onEditCriteria,onRemoveCriteria}) {
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let mode='voice', state='idle', busy=false, opened=false, hasSession=false, returnFocus=null;
  let lastStatus='idle', statusOverride='';
  let orb=orbController, turns=[], lastMessage='', draft='', promptOptions=[], resultCount=0, context='', elapsed=0;
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const icon=name=>{const image=node('img','agent-icon');image.src=new URL(`./assets/icons/${({microphone:'call',expand:'collapse','end-call':'end'})[name]||name}.svg`,import.meta.url).href;image.alt='';image.width=image.height=20;return image;};
  const button=(cls,label,name,action)=>{const b=node('button',cls);b.type='button';b.setAttribute('aria-label',label);b.title=label;if(name)b.append(icon(name));if(action)b.addEventListener('click',action);return b;};
  const panel=node('section','agent-panel');panel.id='agent-panel';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Talk to HomeTruth');
  const header=node('header','agent-header');
  const modeButton=button('agent-circle','Show messages','chat',()=>setMode(mode==='voice'?'chat':'voice'));
  modeButton.setAttribute('aria-pressed','false');
  const identity=node('span','agent-identity','HomeTruth');
  const minimizeButton=button('agent-circle','Minimize conversation','collapse',()=>minimize());
  header.append(modeButton,identity,minimizeButton);
  const criteria=node('div','agent-criteria');criteria.hidden=true;
  const body=node('div','agent-body');
  const stage=node('div','agent-stage');
  const orbHost=node('div','agent-orb');orbHost.setAttribute('aria-hidden','true');
  const status=node('p','agent-status');const statusText=node('span','','Ready when you are.');status.append(statusText);
  const message=node('p','agent-message');message.hidden=true;
  const voiceAction=button('agent-voice-action','Start speaking',null,()=>onVoiceToggle());voiceAction.append(icon('microphone'),node('span','','Start speaking'));
  stage.append(orbHost,status,message,voiceAction);
  const transcript=node('div','agent-transcript');transcript.hidden=true;transcript.setAttribute('role','log');transcript.setAttribute('aria-label','Conversation');transcript.setAttribute('aria-live','off');
  const draftLine=node('p','agent-draft');draftLine.hidden=true;
  const options=node('div','agent-options');options.hidden=true;
  const resultButton=button('agent-result-link','View matching homes',null,()=>{minimize();onViewHomes();});resultButton.hidden=true;
  body.append(stage,transcript,draftLine,options,resultButton);
  const footer=node('div','agent-footer');
  const form=node('form','agent-composer');const label=node('label','sr-only','Message HomeTruth');label.htmlFor='agent-input';
  const input=node('input');input.id='agent-input';input.placeholder='Or send a message…';input.autocomplete='off';input.maxLength=280;
  const send=button('agent-send','Send message','send');send.type='submit';send.disabled=true;
  form.append(label,input,send);
  const end=button('agent-end','End conversation','end-call',()=>{onEnd();close();});
  footer.append(form,end);
  const announce=node('span','sr-only');announce.setAttribute('role','status');announce.setAttribute('aria-live','polite');
  panel.append(header,criteria,body,footer,announce);
  const launcher=button('agent-launcher','Talk to HomeTruth',null,()=>open({focus:false}));launcher.hidden=true;launcher.setAttribute('aria-controls','agent-panel');launcher.setAttribute('aria-expanded','false');
  launcher.append(node('span','agent-launcher-label','Ask HomeTruth'),icon('expand'));if(!orbElement)launcher.prepend(icon('chat'));
  document.body.append(panel,launcher);
  let anchorVisible=true;
  const anchorObserver=new IntersectionObserver(entries=>{anchorVisible=entries[0]?.isIntersecting??true;updateLauncher();},{threshold:0.15});
  if(anchor)anchorObserver.observe(anchor);

  function updateLauncher(){launcher.hidden=opened||anchorVisible;launcher.setAttribute('aria-expanded',String(opened));launcher.querySelector('.agent-launcher-label').textContent=state==='listening'?'Listening…':state==='speaking'?'Speaking…':state==='thinking'?'Checking…':'Ask HomeTruth';launcher.dataset.state=state;if(orbElement){const host=opened?orbHost:anchorVisible?anchor:launcher;if(host&&orbElement.parentNode!==host)host.prepend(orbElement);}}
  function ensureOrb(){if(orbElement){updateLauncher();return;}if(orb)return;orb=createAgentsOrb(orbHost);orb.setState(state);orbHost.addEventListener('agents-orb-error',()=>{panel.dataset.orbFallback='original-image';});}
  function update(){
    panel.dataset.state=state;panel.dataset.mode=mode;
    form.setAttribute('aria-busy',String(busy));send.disabled=busy||!input.value.trim();
    const clock=elapsed?` ${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,'0')}`:'';
    const statusLabel=state==='listening'?`Listening…${clock}`:state==='thinking'?(statusOverride||'Checking…'):state==='speaking'?'Speaking…':state==='error'?'Voice unavailable.':promptOptions.length?lastMessage:lastMessage?'Anything else?':'Ready when you are.';
    statusText.textContent=statusLabel;if(lastStatus!==state&&opened&&!reduced.matches){statusText.animate([{opacity:0,transform:'translateY(100%)'},{opacity:1,transform:'translateY(0)'}],{duration:240,easing:'cubic-bezier(.16,1,.3,1)'});}lastStatus=state;
    const label=state==='listening'?'Stop listening':state==='speaking'?'Interrupt & speak':lastMessage?'Keep talking':'Start speaking';
    voiceAction.setAttribute('aria-label',label);voiceAction.title=label;voiceAction.querySelector('span').textContent=label;voiceAction.disabled=busy;
    message.textContent=lastMessage;message.hidden=!lastMessage||['listening','thinking'].includes(state)||promptOptions.length>0;
    draftLine.textContent=state==='thinking'?(statusOverride||'Checking…'):state==='speaking'?'Speaking…':draft;draftLine.hidden=mode!=='chat'||(!draft&&!['thinking','speaking'].includes(state));
    options.hidden=!promptOptions.length||busy;resultButton.hidden=!resultCount||busy;
    resultButton.replaceChildren(document.createTextNode(`View ${resultCount} ${resultCount===1?'home':'homes'}`),icon('send'));
    identity.textContent=context||'HomeTruth';
    updateLauncher();
  }
  function paintTranscript(){
    transcript.replaceChildren();
    if(!turns.length)transcript.append(node('p','agent-empty','What are you after?'));
    for(const turn of turns){const row=node('div',`agent-turn agent-turn-${turn.role}`);row.append(node('span','sr-only',turn.role==='user'?'You: ':'HomeTruth: '),node('p','',turn.text));transcript.append(row);}
    transcript.scrollTop=transcript.scrollHeight;
  }
  function setMode(next){mode=next;stage.hidden=mode!=='voice';transcript.hidden=mode!=='chat';modeButton.replaceChildren(icon(mode==='voice'?'chat':'microphone'));modeButton.setAttribute('aria-label',mode==='voice'?'Show messages':'Show voice');modeButton.title=mode==='voice'?'Show messages':'Show voice';modeButton.setAttribute('aria-pressed',String(mode==='chat'));if(mode==='chat'){paintTranscript();if(opened)input.focus({preventScroll:true});}update();}
  function open({focus=false,view}={}){
    if(document.querySelector('dialog[open]'))return;
    if(!opened){returnFocus=document.activeElement;opened=true;hasSession=true;panel.hidden=false;document.body.classList.add('agent-panel-open');anchor?.setAttribute('aria-expanded','true');const mainLive=document.querySelector('#conversation');mainLive?.setAttribute('aria-live','off');ensureOrb();if(!reduced.matches)panel.animate([{opacity:0,transform:'translateY(18px) scale(.96)'},{opacity:1,transform:'translateY(0) scale(1)'}],{duration:420,easing:'cubic-bezier(.16,1,.3,1)'});}
    if(view)setMode(view);else update();
    if(focus)input.focus({preventScroll:true});else modeButton.focus({preventScroll:true});
  }
  function hide(restore=true){opened=false;panel.hidden=true;document.body.classList.remove('agent-panel-open');anchor?.setAttribute('aria-expanded','false');document.querySelector('#conversation')?.setAttribute('aria-live','polite');updateLauncher();if(restore){const visible=n=>n?.isConnected&&!n.hidden&&n.getBoundingClientRect().width>0&&n.getBoundingClientRect().bottom>0&&n.getBoundingClientRect().top<innerHeight;const target=[returnFocus,anchor,launcher].find(visible);target?.focus({preventScroll:true});}}
  function minimize({restore=true}={}){hide(restore);}
  function close(){draft='';input.value='';hasSession=false;hide();update();}
  form.addEventListener('submit',event=>{event.preventDefault();const text=input.value.trim();if(!text||busy)return;input.value='';draft='';setMode('chat');send.disabled=true;onSubmit(text);});
  input.addEventListener('input',()=>{onTyping?.();send.disabled=busy||!input.value.trim();});
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();minimize();}});
  function syncViewport(){const v=window.visualViewport;const height=v?.height||innerHeight;const offset=v?Math.max(0,innerHeight-v.height-v.offsetTop):0;panel.style.setProperty('--agent-visible-height',height+'px');panel.style.setProperty('--agent-keyboard-offset',offset+'px');launcher.style.setProperty('--agent-keyboard-offset',offset+'px');}
  window.visualViewport?.addEventListener('resize',syncViewport);window.visualViewport?.addEventListener('scroll',syncViewport);
  syncViewport();update();
  return {
    open,minimize,close,focusEntry(){const r=anchor?.getBoundingClientRect();anchorVisible=!!r&&r.bottom>0&&r.top<innerHeight;updateLauncher();(anchorVisible?anchor:launcher)?.focus({preventScroll:true});},setHost(host){(host||document.body).append(panel,launcher);},setCriteria(tokens){renderCriteriaBar(criteria,tokens,{onEdit:onEditCriteria,onRemove:onRemoveCriteria,limit:3});},isOpen:()=>opened,focus:()=>{if(!opened)open({focus:true});else input.focus({preventScroll:true});},
    setStatusText(text){statusOverride=text||'';update();},
    setState(next){state=next;if(!orbController)orb?.setState(next);if(next!=='listening'){draft='';elapsed=0;}update();},
    setBusy(value){if(value&&opened&&options.contains(document.activeElement))input.focus({preventScroll:true});busy=value;update();},
    setElapsed(value){elapsed=value;update();},
    setDraft(value){draft=value;input.value=value;update();},
    setContext(home){context=home?.area?.split(',')[0]||'';update();},
    appendTurn(role,text,merge=false){if(!text.trim())return;const last=turns[turns.length-1];if(merge&&last&&last.role===role)last.text+=' '+text;else turns.push({role,text});if(turns.length>40)turns=turns.slice(-40);if(role==='assistant'){lastMessage=text;if(opened)announce.textContent=text;}if(mode==='chat')paintTranscript();update();},
    setPrompt(text,choices=[]){const refocus=opened&&options.contains(document.activeElement);lastMessage=text;promptOptions=choices;options.replaceChildren();for(const option of choices)options.append(button('agent-option',option.label,null,option.action));Array.from(options.children).forEach((b,i)=>b.textContent=choices[i].label);update();if(refocus)(options.firstElementChild||input).focus({preventScroll:true});},
    setResults(count){resultCount=count;promptOptions=[];options.replaceChildren();update();},
    reset(){turns=[];lastMessage='';draft='';promptOptions=[];resultCount=0;context='';input.value='';options.replaceChildren();paintTranscript();update();},
    suspend(){if(opened)hide(false);},
    destroy(){window.visualViewport?.removeEventListener('resize',syncViewport);window.visualViewport?.removeEventListener('scroll',syncViewport);anchorObserver.disconnect();if(orbElement)anchor?.prepend(orbElement);else orb?.destroy();panel.remove();launcher.remove();document.body.classList.remove('agent-panel-open');}
  };
}
