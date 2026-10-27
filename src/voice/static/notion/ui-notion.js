/* HomeTruth · Notion-style renderer (fork preview, 2026-10-27). Same interface as ui.js / qi/ui-qi.js (window.HTUI.create() → state /
   phase / needs / source / card / cardUpdate / highlight / evidence / change / caption / transcript …), so the shared controller
   /static/app.js (SSE from /api/turn, TTS, Web Speech, barge-in) drives it unchanged.
   Layout and type learned from notion.com as a whole (home, product pages, pricing, templates, customers, blog, help, releases): a
   centred hero with a rotating word in a coloured pill and the Notion AI prompt box; the product window under it is the live workspace
   (sidebar: needs, sources, shortlist; page: properties, a callout with what it says, database views); grey bento cards, bordered cards,
   a scroll-filled sentence, a template-style gallery, a Q&A accordion, a grey CTA band and the column footer. A place opens as a Notion
   side peek. Motion: notion-fx.js (Lucian UX/UI Prompt ports). Every word on a card still comes from the server's events and
   /api/listings; the photos of the five synthetic places are illustrative design photos, the nine real places carry their own. */
import * as fx from './notion-fx.js?v=3';
import { LOGO, HOUSE, CLIPBOARD, KEY, ASK, PEEK } from './ink.js?v=3';
import { createAgentsOrb } from '../qi/agents-orb.js?v=8';
import { createConversationPanel } from '../qi/conversation-panel.js?v=8';  // the floating panel of the previous design, kept (superliang 10-27): its own Orb, status, transcript, composer  // the same Orb as the current design's Start talking pill

window.HTUI = (() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const cssEsc = (s) => (window.CSS && CSS.escape ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, '\\$&'));
  const fmtDate = (iso) => { if (!iso) return ''; const d = new Date(iso + 'T00:00:00'); return isNaN(d) ? String(iso) : d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' }); };
  const fmtMs = (ms) => (ms == null ? '' : ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms');
  // where an evidence item came from (src/voice/zetaris_live.py): the Zetaris query that returned it, an agent reply, or the local copy
  const prov = (e) => (e.via === 'zetaris' ? ` · Zetaris query ${String(e.request_id || '').slice(0, 8)}` : e.via === 'agent_reply' ? ' · agent reply' : e.via === 'local' ? ' · local copy' : e.request_id ? ' · ' + e.request_id : '') + (e.mock ? ' · simulated' : '');
  const provTitle = (e) => (e.via === 'zetaris' ? `Zetaris query ${e.request_id}${e.queried_at ? ' at ' + e.queried_at : ''}\n${e.sql || ''}` : '');
  const fmtWhen = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso || '') : d.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
  const sentence = (s) => { s = String(s || ''); return s ? s[0].toUpperCase() + s.slice(1) : s; };
  const money = (n) => '$' + Number(n).toLocaleString('en-AU');
  const STATUS = { supported: 'Supported', inferred: 'Inferred', conflict: 'Conflict', unknown: 'Unknown' };
  const STATUS_WORDS = new Set(['yes', 'likely', 'clash', '?']);  // card_payload's short values that only repeat the status
  const NEXT_TEXT = { ask_agent: 'Ask the agent', see_at_viewing: 'See at the viewing', check_at_signing: 'Check at signing' };
  const SOURCE_NAMES = { agent_reply: 'Agent reply', inbox: 'Agent reply · while you were away', inbox_live: 'Agent reply · just in' };
  // the materials in the order a NSW renter can get them (policy.STAGES, docs/01): the first three are evidence, the last two only ever next steps
  const STAGES = [['listing', 'From the listing'], ['public', 'Public data'], ['agent', 'From the agent'], ['viewing', 'Your viewing'], ['signing', 'At signing']];
  const STAGE_EMPTY = { viewing: 'nothing yet; we’ll say what to look for', signing: 'not used for ranking' };
  const STAGE_OF_TABLE = { listings: 'listing', photo_facts: 'listing', floorplan_facts: 'listing', public_rent: 'public', public_transit: 'public', sun_geometry: 'public', geo_estimate: 'public', documents: 'agent' };
  const stageOf = (e) => (e && e.stage) || STAGE_OF_TABLE[e && e.table] || 'public';
  const TABLE_NAMES = { listings: 'Listing', documents: 'Document', photo_facts: 'Photo', public_rent: 'Rent data', public_transit: 'Transit table', sun_geometry: 'Sun geometry', geo_estimate: 'Distance estimate', floorplan_facts: 'Floor plan' };
  const sourceName = (e) => { const row = String(e.row || '') + ' ' + String(e.material_id || ''); if (e.table === 'documents') return /bylaws/i.test(row) ? 'By-laws' : /repl/i.test(row) ? 'Agent reply' : /plan/i.test(row) ? 'Floor plan' : 'Document'; return TABLE_NAMES[e.table] || sentence(String(e.table || 'source').replace(/_/g, ' ')); };
  const plainLine = (text, e) => { let t = String(text || '').trim().replace(/^features:\s*/i, 'Listing features: ').replace(/^By-laws excerpt:\s*/i, 'By-laws: '); if (e.table === 'photo_facts') t = t.replace(/;\s*/g, ', '); t = sentence(t); return /[.!?]$/.test(t) ? t : t + '.'; };
  const modelName = (m) => (/nemotron.*vl|vl.*nemotron|nemotron-3\.5-super/i.test(String(m)) ? 'Nemotron VL' : /nemotron/i.test(String(m)) ? 'Nemotron' : String(m));
  const splitTitle = (L) => { const t = String(L.title || L.id || ''); const i = t.lastIndexOf(', '); return i > 0 ? [t.slice(0, i), L.suburb || t.slice(i + 2)] : [t, L.suburb || '']; };
  const isReal = (L) => !!(L && L.source && L.source.listing_id);
  const photoTag = (L) => (isReal(L) ? `${L.source.site === 'domain.com.au' ? 'Domain' : L.source.site} listing ${L.source.listing_id}${L.source.agency ? ' · ' + L.source.agency : ''}` : 'Illustrative photo, not this place');
  const EXAMPLE = 'Two bedrooms near Central, under 900 a week, I have a cat, moving mid November';
  const EXAMPLES = [EXAMPLE, 'A one-bedroom near UNSW under 700, moving early December', 'Two bedrooms in Kensington with a dog, under 950 a week'];
  const FIELD_OF = { A1: 'budget', B1: 'bedrooms', G1: 'anchor', A4: 'move_in', J1: 'pets' };
  // the five must-haves (policy.REQUIRED): property name, icon, the value in words, the pill while we ask, the pill when assumed (phraser.ASSUME)
  const NEEDS = [
    ['A1', 'Budget', 'coin', (p) => (p.budget != null ? `Under $${p.budget}/wk` : null), 'Asking…', 'Any budget (assumed)'],
    ['B1', 'Bedrooms', 'bed', (p) => (p.bedrooms != null ? (p.bedrooms === 0 ? 'Studio' : `${p.bedrooms} bedroom${p.bedrooms === 1 ? '' : 's'}`) : null), 'Asking…', 'Any size (assumed)'],
    ['G1', 'Near', 'pin', (p) => (p.anchor ? p.anchor : null), 'Asking…', 'Central Station (assumed)'],
    ['A4', 'Move in', 'cal', (p) => (p.move_in ? sentence(p.move_in) : null), 'Asking…', 'Any date (assumed)'],
    ['J1', 'Pets', 'paw', (p) => (p.pets ? (/^no\b/i.test(p.pets) ? sentence(p.pets) : `With ${p.pets}`) : null), 'Asking…', 'No pets (assumed)'],
  ];
  const icon = (n, cls = 'ico') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const sIcon = (st) => `<svg aria-hidden="true"><use href="#s-${esc(st)}"/></svg>`;
  const tag = (cls, text) => `<span class="tag ${cls}">${esc(text)}</span>`;
  const pill = (st) => `<span class="tag status dot ${esc(st)}">${esc(STATUS[st] || st)}</span>`;
  const nextTag = (n) => (NEXT_TEXT[n] ? tag(n, NEXT_TEXT[n]) : '');
  const TICK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.4 8.3 2.4 2.4 4.8-5.1"/></svg>';
  // one row of icons instead of labelled fields, like a listing site's bed / bath / car line; the words stay for screen readers and tooltips
  const specRow = (L, { rent = true, date = true, cls = '' } = {}) => `<span class="nt-specs${cls ? ' ' + cls : ''}" role="list">${[
    rent ? ['coin', `${money(L.rent)}/wk`, 'Rent per week'] : null,
    ['bed', L.bedrooms === 0 ? 'Studio' : L.bedrooms, 'Bedrooms'],
    ['bath', L.bathrooms, 'Bathrooms'],
    L.parking != null ? ['car', L.parking, 'Car spaces'] : null,
    date && L.available_from ? ['cal', fmtDate(L.available_from), 'Available from'] : null,
  ].filter(Boolean).map(([ic, v, t]) => `<span role="listitem" title="${t}">${icon(ic)}<span class="sr-only">${t}: </span>${esc(v)}</span>`).join('')}</span>`;
  const SRC_ICON = { Listing: 'doc', Photo: 'photo', 'Floor plan': 'plan', 'By-laws': 'doc', 'Agent reply': 'chat', Document: 'doc', 'Rent data': 'chart', 'Transit table': 'train', 'Sun geometry': 'sparkle', 'Distance estimate': 'pin' };
  const srcIcons = (names) => names.map((n) => `<span class="si" title="${esc(n)}">${icon(SRC_ICON[n] || 'doc')}<span class="sr-only">${esc(n)}</span></span>`).join('');

  const SPRITE = `<svg class="icon-library" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<symbol id="i-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v9M14.6 9.6c-.3-.9-1.3-1.5-2.6-1.5-1.5 0-2.6.8-2.6 1.8 0 2.4 5.2 1.1 5.2 3.6 0 1-1.1 1.9-2.6 1.9-1.4 0-2.4-.7-2.7-1.6"/></symbol>
<symbol id="i-bed" viewBox="0 0 24 24"><path d="M3 18v-8M3 14h18v4M21 14v-3a2 2 0 0 0-2-2h-7v5"/><circle cx="7" cy="9.5" r="1.8"/></symbol>
<symbol id="i-bath" viewBox="0 0 24 24"><path d="M4 12h16v2a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM6 12V6a2 2 0 0 1 3.6-1.2M7 19l-1 2M17 19l1 2"/></symbol>
<symbol id="i-car" viewBox="0 0 24 24"><path d="M5 16V11l2-5h10l2 5v5M5 16h14M5 16v2M19 16v2M5 11h14"/><circle cx="8" cy="13.6" r=".6"/><circle cx="16" cy="13.6" r=".6"/></symbol>
<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z"/><circle cx="12" cy="10" r="2.2"/></symbol>
<symbol id="i-cal" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></symbol>
<symbol id="i-paw" viewBox="0 0 24 24"><circle cx="7" cy="9" r="1.7"/><circle cx="11" cy="6.2" r="1.7"/><circle cx="15.8" cy="6.8" r="1.7"/><circle cx="19" cy="10.8" r="1.7"/><path d="M8.2 17.2c0-2.6 2.1-4.7 4.6-4.7s4.6 2.1 4.6 4.7c0 1.5-1.1 2.4-2.4 2.4-1 0-1.5-.5-2.2-.5s-1.2.5-2.2.5c-1.3 0-2.4-.9-2.4-2.4z"/></symbol>
<symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></symbol>
<symbol id="i-up" viewBox="0 0 16 16"><path d="M8 13V3M3.8 7.2 8 3l4.2 4.2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="i-arrow" viewBox="0 0 16 16"><path d="M3 8h10M9 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="i-close" viewBox="0 0 24 24"><path d="m6 12 6-6m-6 6 6 6M12 12l6-6m-6 6 6 6"/></symbol>
<symbol id="i-tri" viewBox="0 0 16 16"><path d="M6 4.5 10 8l-4 3.5z" fill="currentColor" stroke="none"/></symbol>
<symbol id="i-walk" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M9 10v9"/></symbol>
<symbol id="i-table" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M4 14.5h16M10 5v14"/></symbol>
<symbol id="i-steps" viewBox="0 0 24 24"><path d="M9 7h11M9 12h11M9 17h11"/><path d="m3.6 7 1.3 1.3L7.2 6M3.6 12l1.3 1.3 2.3-2.3"/><circle cx="5.2" cy="17" r="1.3"/></symbol>
<symbol id="i-history" viewBox="0 0 24 24"><path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v3.2h3.2M12 8v4.3l2.8 1.8"/></symbol>
<symbol id="i-doc" viewBox="0 0 24 24"><path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20z"/><path d="M14 3.5V8h4M9.5 12h6M9.5 15.5h6"/></symbol>
<symbol id="i-chart" viewBox="0 0 24 24"><path d="M4 20h16M7 16v-5M12 16V6M17 16v-8"/></symbol>
<symbol id="i-chat" viewBox="0 0 24 24"><path d="M4 5.5h16v10.5H10l-6 4z"/></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></symbol>
<symbol id="i-pen" viewBox="0 0 24 24"><path d="M4 20l1-4.5L15.5 5a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L8.5 19z"/><path d="M13.5 7l3.5 3.5"/></symbol>
<symbol id="i-ext" viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></symbol>
<symbol id="i-train" viewBox="0 0 24 24"><rect x="6" y="3.5" width="12" height="13" rx="3"/><path d="M6 10h12M9 20l-1.5 1.5M15 20l1.5 1.5"/><circle cx="9" cy="13.4" r=".7"/><circle cx="15" cy="13.4" r=".7"/></symbol>
<symbol id="i-photo" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m4 17 5-4.5 4 3.5 3-2.5 4 3.5"/></symbol>
<symbol id="i-plan" viewBox="0 0 24 24"><path d="M4 4h16v16H4zM4 11h7V4M11 15v5M15 11h5M15 11v4"/></symbol>
<symbol id="i-sparkle" viewBox="0 0 24 24"><path d="M12 3.5 13.8 10l6.7 2-6.7 2L12 20.5 10.2 14l-6.7-2 6.7-2z"/></symbol>
<symbol id="i-user" viewBox="0 0 24 24"><circle cx="12" cy="8.5" r="3.5"/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5"/></symbol>
<symbol id="s-supported" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m4.9 8.2 2.1 2.1 4.2-4.5" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="s-inferred" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1.8a6.2 6.2 0 0 0 0 12.4z" fill="currentColor"/></symbol>
<symbol id="s-conflict" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="s-unknown" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.3 1.9"/><path d="M6.5 6.4a1.6 1.6 0 1 1 2.3 1.5c-.5.25-.8.6-.8 1.1v.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".85" fill="currentColor"/></symbol>
</svg>`;

  // how it checks: one grey bento card per kind of material (stage, icon, eyebrow, title, a slice of product UI); the first two are wide
  const HOW = [
    ['listing', 'doc', 'From the listing', 'Read line by line.',
      `<div class="fx-scene"><div class="sc-h">${icon('doc')}Listing page</div><div class="ln" style="--w:.92"></div><div class="ln" style="--w:.7"></div><div class="ln" style="--w:.84"></div><div class="rowx"><span>Rent $890 per week</span>${pill('supported')}</div><div class="rowx"><span>Photo stamped “virtually staged”</span>${pill('inferred')}</div></div>`],
    ['public', 'chart', 'Public data', 'What a listing won’t say.',
      `<div class="fx-scene"><div class="sc-h">${icon('chart')}Rent against the suburb</div><div class="bars"><i style="--h:52%"></i><i style="--h:64%"></i><i class="me" style="--h:71%"></i><i style="--h:58%"></i><i style="--h:80%"></i></div><p class="cap">Median rent nearby · the dark bar is this place</p></div>`],
    ['agent', 'chat', 'From the agent', 'Unknowns become questions.',
      `<div class="fx-scene"><div class="sc-h">${icon('chat')}Agent</div><div class="bub me">Are pets allowed, in writing?</div><div class="bub">Yes, with written consent.</div><div class="rowx"><span>Pets</span><span>${pill('inferred')} → ${pill('supported')}</span></div></div>`],
    ['viewing', 'eye', 'Your viewing', 'Some things need a visit.',
      `<div class="fx-scene"><div class="sc-h">${icon('eye')}At the viewing</div><div class="rowx"><span>Double glazing?</span>${tag('see_at_viewing', 'See at the viewing')}</div><div class="rowx"><span>Which furniture stays?</span>${tag('ask_agent', 'Ask the agent')}</div></div>`],
    ['signing', 'pen', 'At signing', 'Paperwork comes last.',
      `<div class="fx-scene"><div class="sc-h">${icon('pen')}Lease and condition report</div><div class="ln" style="--w:.95"></div><div class="ln" style="--w:.8"></div><div class="rowx"><span>Bond lodged</span>${tag('check_at_signing', 'Check at signing')}</div></div>`],
  ];
  const LABELS = [['supported', 'A source says so.'], ['inferred', 'Likely, not confirmed.'], ['conflict', 'Goes against you.'], ['unknown', 'Nothing on file yet.']];
  const FAQ = [
    ['What do the four labels mean?', 'Supported: a source says so. Inferred: likely, not confirmed. Conflict: goes against what you need. Unknown: nothing on file. An unknown must-have is “To confirm”, never a yes.'],
    ['Where do the places come from?', 'Nine real Sydney rentals from Domain (26 Oct 2026), credited to their agencies. Five synthetic ones on fictional streets, with illustrative photos.'],
    ['Who reads the photos and floor plans?', 'NVIDIA Nemotron’s vision model. It describes what is in the picture; it never decides the ranking.'],
    ['Is the 3D plan a scan?', 'No. It is raised from the listing’s floor plan, with its photos placed in the rooms. Sizes are indicative.'],
    ['What does it never look at?', 'Who lives nearby. No ethnicity, nationality, age group or student share, ever.'],
    ['What does it remember about me?', 'Your last needs, under an id kept in this browser. “Forget me” deletes them.'],
    ['Can I interrupt it?', 'Yes. Talk or type while it speaks. Esc stops it; “next one” skips ahead.'],
  ];
  // a place's checks, grouped like the departments on notion.com/careers: by the first letter of the dimension (docs/02)
  const GROUPS = [['A', 'Rent and terms'], ['B', 'Space and layout'], ['G', 'Location'], ['C', 'Fittings and furniture'], ['D', 'Condition'], ['E', 'Light and noise'], ['F', 'Building'], ['J', 'Pets'], ['H', 'What the agent must disclose'], ['I', 'Applying'], ['K', 'Feng shui (optional)']];
  const STAGE_SHORT = { listing: 'Listing', public: 'Public data', agent: 'Agent' };
  const DEST = { central: 'Central', unsw: 'UNSW', cbd: 'CBD' };

  const SKELETON = () => `${SPRITE}
<header class="nt-nav" id="nav" data-enter="0">
  <a class="nt-brand" href="#top" aria-label="HomeTruth home">${LOGO}<span>HomeTruth</span></a>
  <nav class="nt-menu" aria-label="Main"><a href="#workspace">Find a place</a><a href="#how">How it checks</a><a href="#explore">Explore</a><a href="#faq">Questions</a></nav>
  <div class="nt-right"><a class="nt-btn nt-btn-quiet nt-btn-sm" href="/qi" title="The previous HomeTruth design (qi shell)">Previous design</a><button type="button" class="nt-btn nt-btn-primary nt-btn-sm" data-talk>Start talking</button></div>
  <i class="nt-nav-progress" id="nav-progress" aria-hidden="true"></i>
</header>
<main id="top">
<section class="nt-hero" id="hero" aria-label="Find a place through conversation">
  <div class="nt-wrap-wide">
    <h1 class="nt-display" data-enter="120">Tell me what you need.<br>I check every <span class="nt-pill" id="hero-pill" data-tone="green"><i></i><span class="nt-pill-mask"><span class="nt-pill-word">listing</span></span></span></h1>
    <p class="nt-lead" id="hero-lede" data-enter="300">Rent, rooms, commute, move-in, pets. Every line says what backs it.</p>
    <div class="nt-welcome" id="welcome-slot" hidden></div>
    <div class="nt-composer-home" id="composer-home" data-enter="420">
      <form class="nt-composer" id="composer" autocomplete="off">
        <label class="sr-only" for="text">Describe the place you need</label>
        <input id="text" type="text" maxlength="280" placeholder="Or type what you need…">
        <span class="fx-ph" id="ph" aria-hidden="true"></span>
        <button type="button" id="mic" class="nt-mic" aria-pressed="false" title="Talk instead of typing (Chrome)"><span class="nt-orb" id="mic-orb" aria-hidden="true"></span><span id="mic-label">Start talking</span></button>
        <button type="submit" id="send" class="nt-send" aria-label="Send">${icon('up', '')}</button>
      </form>
    </div>
    <div class="nt-suggest" id="suggestions" data-enter="520"><span>Try</span><button type="button" data-prompt="${esc(EXAMPLE)}">${esc(EXAMPLE)} ↗</button></div>
    <div class="nt-strip" data-enter="620">
      <ul class="nt-strip-row" aria-label="Sources it checks"><li>${icon('doc')}Listing pages</li><li>${icon('photo')}Photo facts</li><li>${icon('plan')}Floor plans</li><li>${icon('chat')}Agent replies</li><li>${icon('doc')}By-laws</li><li>${icon('chart')}Rent medians</li><li>${icon('train')}Transit times</li><li>${icon('sparkle')}Sun geometry</li></ul></div>
  </div>
</section>

<section class="nt-ws nt-wrap-wide" id="workspace" aria-label="Your search">
  <div class="nt-peeker" data-enter="1100" aria-hidden="true">${PEEK}</div>
  <div class="nt-window fx-tilt" id="window" data-enter="760">
    <div class="nt-win-bar">
      <span class="nt-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      <span class="nt-crumbs"><span>HomeTruth</span><span>/</span><b id="crumb">Your search</b></span>
      <span class="nt-win-right"><span class="nt-phase"><i class="nt-phase-dot"></i><span id="phase">Ready</span></span>
        <button type="button" id="panel-open" class="nt-btn nt-btn-quiet nt-btn-xs" title="Open the conversation panel">${icon('chat')}<span>Chat</span></button>
        <button type="button" id="stop" class="nt-btn nt-btn-quiet nt-btn-xs" title="Stop speaking (Esc)">Stop</button>
        <button type="button" id="reset" class="nt-btn nt-btn-quiet nt-btn-xs">New search</button></span>
    </div>
    <div class="nt-win-body">
      <aside class="nt-side" aria-label="Search sidebar">
        <div class="nt-side-ws">${LOGO}<span>Your search</span></div>
        <div><p class="nt-side-h">Needs</p><ul class="nt-side-list" id="side-needs"><li class="muted">Nothing yet</li></ul></div>
        <div><p class="nt-side-h">Sources <span id="sources-count"></span></p><div class="fx-qbar" id="qbar" hidden><i class="seg a"></i><i class="seg b"></i><i class="fill"></i></div><ul class="nt-src" id="sources"><li class="stg">Checked once you’ve said what you need</li></ul></div>
        <div><p class="nt-side-h">Shortlist</p><ul class="nt-side-list" id="side-short"><li class="muted">Empty</li></ul></div>
        <div class="nt-side-foot">
          <label class="nt-opt" title="With headphones on there is no echo, so it reacts to your voice sooner"><input type="checkbox" id="headphones">Headphones</label>
          <label class="nt-opt" title="After a question, put the cursor back in the box"><input type="checkbox" id="autolisten" checked>Auto-listen</label>
          <span class="nt-meter" id="meter" title="Mic level · red mark = interrupt threshold" hidden><i></i><b></b></span>
          <span class="nt-note" id="note"></span>
          <span class="nt-meta" id="meta"></span>
        </div>
      </aside>
      <div class="nt-page" id="page">
        <div class="nt-page-icon" aria-hidden="true">${HOUSE}</div>
        <h2 class="nt-page-title placeholder" id="page-title">Untitled search</h2>
        <div class="nt-props" id="props"></div>
        <div class="nt-callout" id="conversation">
          <span class="nt-callout-ic" aria-hidden="true">${LOGO}</span>
          <div class="nt-callout-body"><p class="nt-say-phase" id="say-phase"></p><p class="nt-say hint" id="caption" aria-live="polite">Tell me what you need. I’ll only ask for what’s missing.</p><p class="nt-you" id="transcript"></p></div>
        </div>
        <div class="nt-views" id="views" role="tablist" aria-label="Views">
          <button type="button" role="tab" data-view="walk" class="is-on" aria-selected="true">${icon('walk')}Walkthrough</button>
          <button type="button" role="tab" data-view="table" aria-selected="false">${icon('table')}Table</button>
          <button type="button" role="tab" data-view="steps" aria-selected="false">${icon('steps')}Next steps</button>
          <button type="button" role="tab" data-view="changes" aria-selected="false">${icon('history')}Changes <span class="cnt" id="changes-count">0</span></button>
          <i class="fx-knob" aria-hidden="true"></i>
        </div>
        <div class="nt-view" id="view-walk" data-view="walk"><div class="nt-empty">${CLIPBOARD}<div><p class="nt-sub">Your shortlist appears here.</p><p class="nt-small">One line per need, each with what backs it.</p></div></div></div>
        <div class="nt-view" id="view-table" data-view="table" hidden></div>
        <div class="nt-view" id="view-steps" data-view="steps" hidden></div>
        <div class="nt-view" id="view-changes" data-view="changes" hidden></div>
      </div>
    </div>
  </div>
</section>

<section class="nt-sec nt-wrap" id="how" aria-labelledby="how-title">
  <div class="nt-sec-head"><h2 class="nt-h3 fx-head" id="how-title">Five sources.<br>One honest answer.</h2><div class="ink" aria-hidden="true">${CLIPBOARD}</div></div>
  <div class="nt-bento2">${HOW.map(([k, ic, name, title, scene], i) => `<article class="nt-bcard fx-card${i < 2 ? ' big' : ''}" data-k="${k}"><p class="nt-eyebrow">${icon(ic)}${esc(name)}</p><h3>${esc(title)}</h3>${scene}</article>`).join('')}</div>
  <p class="nt-eyebrow nt-labels-h">Four labels, on every line</p>
  <div class="nt-cards4">${LABELS.map(([st, d]) => `<div class="nt-card fx-card st-${st}"><span class="ic">${sIcon(st)}</span><h3>${STATUS[st]}</h3><p>${d}</p></div>`).join('')}</div>
</section>

<section class="nt-sec nt-wrap" id="explore" aria-labelledby="explore-title">
  <div class="nt-sec-head"><div><h2 class="nt-h3 fx-head" id="explore-title">Every place I can check.</h2><p class="nt-lead" id="explore-lede">Real Sydney rentals and synthetic ones.</p></div><div class="ink" aria-hidden="true">${HOUSE}</div></div>
  <div class="nt-ex-ctrl" id="explore-controls">
    <div class="fx-seg" id="ex-filter" role="tablist" aria-label="Which places"><button type="button" data-f="all" class="is-on">All<em id="n-all"></em></button><button type="button" data-f="real">Real listings<em id="n-real"></em></button><button type="button" data-f="synthetic">Synthetic<em id="n-syn"></em></button><i class="fx-knob" aria-hidden="true"></i></div>
    <div class="fx-seg" id="ex-unit" role="tablist" aria-label="Show rent"><button type="button" data-u="week" class="is-on">Per week</button><button type="button" data-u="month">Per month</button><i class="fx-knob" aria-hidden="true"></i></div>
  </div>
  <div class="nt-gallery" id="gallery"><p class="nt-small">Loading places…</p></div>
  <button type="button" class="nt-more" data-mag-host data-refine>Refine with a conversation <span class="nt-arrow-btn">${icon('arrow', '')}</span></button>
</section>

<section class="nt-sec nt-wrap" id="faq" aria-labelledby="faq-title">
  <div class="nt-faq"><div><h2 class="nt-h3 fx-head" id="faq-title">Questions</h2></div>
  <div class="nt-acc" id="acc">${FAQ.map(([q, a], i) => `<div class="fx-acc"><button type="button" class="fx-acc-q" aria-expanded="false" aria-controls="faq-a${i}">${esc(q)}<span class="fx-acc-pm" aria-hidden="true"></span></button><div class="fx-acc-body" id="faq-a${i}"><div class="fx-acc-a"><p>${esc(a)}</p></div></div></div>`).join('')}</div></div>
</section>

<section class="nt-cta" aria-labelledby="cta-title">
  <div class="ink" aria-hidden="true">${KEY}</div>
  <h2 class="nt-h3 fx-head" id="cta-title">Know what’s true<br>before you apply.</h2>
  <div class="acts"><button type="button" class="nt-btn nt-btn-primary" data-talk>Start talking</button><a class="nt-btn nt-btn-secondary" href="#explore">Browse every place</a></div>
</section>
</main>
<footer class="nt-foot nt-wrap">
  <div class="nt-foot-grid">
    <div><a class="brand" href="#top">${LOGO}HomeTruth</a><blockquote>Every line says what backs it.</blockquote></div>
    <div><h6>Product</h6><ul><li><a href="#workspace">Find a place</a></li><li><a href="#how">How it checks</a></li><li><a href="#explore">Explore</a></li><li><a href="#faq">Questions</a></li></ul></div>
    <div><h6>Materials</h6><ul><li>Listing pages</li><li>Floor plans and photos</li><li>Agent replies and by-laws</li><li>Rent medians and transit times</li></ul></div>
    <div><h6>Prototype</h6><ul><li><a href="/">Current design</a></li><li><a href="/classic">Classic page</a></li><li>Open Agent Hackathon 2026</li></ul></div>
    <div><h6>Built with</h6><ul><li>Zetaris</li><li>Meterless</li><li>NVIDIA Nemotron</li><li>Cursor</li></ul></div>
  </div>
  <div class="nt-foot-bottom"><span>© 2026 HomeTruth prototype · Open Agent Hackathon</span><span>Real listing photos © their agencies · illustrative photos from resident.co.nz</span><span>Layout after notion.com · motion after Lucian UX/UI Prompt (MIT)</span></div>
</footer>
<div class="nt-dock" id="dock"></div>
<div class="fx-toasts" id="toasts" aria-live="polite"></div>
<dialog class="nt-peek" id="peek" aria-label="Place"></dialog>
<div class="fx-lightbox" id="lightbox" hidden><button type="button" class="fx-lb-nav p" data-lb-prev aria-label="Previous photo">‹</button><img alt=""><p class="fx-lb-cap"></p><button type="button" class="fx-lb-nav n" data-lb-next aria-label="Next photo">›</button></div>`;

  function create() {
    const html = document.documentElement;
    const app = $('#app'); app.innerHTML = SKELETON();
    const el = {
      app, nav: $('#nav'), text: $('#text'), composer: $('#composer'), composerHome: $('#composer-home'), dock: $('#dock'), ph: $('#ph'),
      phase: $('#phase'), sayPhase: $('#say-phase'), caption: $('#caption'), transcript: $('#transcript'), conversation: $('#conversation'),
      crumb: $('#crumb'), title: $('#page-title'), props: $('#props'), sideNeeds: $('#side-needs'), sources: $('#sources'), sourcesCount: $('#sources-count'), qbar: $('#qbar'),
      sideShort: $('#side-short'), views: $('#views'), walk: $('#view-walk'), table: $('#view-table'), steps: $('#view-steps'), changes: $('#view-changes'), changesCount: $('#changes-count'),
      gallery: $('#gallery'), suggestions: $('#suggestions'), welcome: $('#welcome-slot'), heroLede: $('#hero-lede'), note: $('#note'), metaBox: $('#meta'),
      meterBar: $('#meter i'), meterThr: $('#meter b'), peek: $('#peek'), lightbox: $('#lightbox'), toasts: $('#toasts'), micBtn: $('#mic'),
    };
    let stage = 'home', view = 'walk', userPickedView = false, phaseNow = 'idle';
    const cards = new Map();        // listing id → { L, rank, ask:Set, see:Set, was:Map, flash:Set|null, qtext }
    let mainId = null, litKey = null;
    const evCache = new Map();      // "id|dim" → evidence event
    const openRows = new Set();     // rows whose evidence the renter opened by hand
    const sources = new Map();      // name → source event
    const changes = [];             // change events, newest first
    const metaMap = new Map();
    const catalog = new Map();      // /api/listings, by id
    let profile = null, filter = 'all', unit = 'week';
    let lastScrollByUser = 0;
    ['wheel', 'touchmove', 'keydown'].forEach((e) => addEventListener(e, () => { lastScrollByUser = performance.now(); }, { passive: true }));

    /* ---------- motion that only needs the page ---------- */
    fx.heroEntrance(document.body);
    fx.hideOnScroll(el.nav, $('#nav-progress'));
    fx.rotateWord($('#hero-pill'), [{ text: 'listing', tone: 'green' }, { text: 'floor plan', tone: 'blue' }, { text: 'photo', tone: 'orange' }, { text: 'reply', tone: 'purple' }, { text: 'bus time', tone: 'yellow' }]);
    const typing = fx.typingPlaceholder(el.text, el.ph, EXAMPLES, () => (stage === 'home' ? 'Or type what you need…' : 'Reply, ask about a place, or tell me what the agent said…'), () => stage === 'home');
    fx.maskHeadings($$('.fx-head'));
    fx.reveal($$('.fx-card, .nt-bento'));
    fx.playInView($$('.nt-bcard'));
    fx.accordion($('#acc'));
    fx.magnetic($$('.nt-arrow-btn'));
    const toast = fx.toaster(el.toasts);
    // the Orb in the Start talking pill: it shows what the voice is doing (listening / thinking / speaking) and follows the mic level
    let orb = null, orbState = 'idle';
    try { orb = createAgentsOrb($('#mic-orb')); } catch (e) { $('#mic-orb').hidden = true; }
    const setOrb = (st) => { if (orb && st !== orbState) { orbState = st; orb.setState(st); } };
    const lb = fx.lightbox(el.lightbox);
    const placeView = fx.slider(el.views, $('.fx-knob', el.views));
    requestAnimationFrame(() => placeView($('.is-on', el.views), false));

    /* ---------- controls ---------- */
    const submit = (t) => { el.text.value = t; typing.sync(); el.composer.requestSubmit(); };
    /* ---------- the floating conversation panel (qi/conversation-panel.js): the same component as the previous design. It owns a second
       Orb at 160 px; it opens on the first turn (voice view when the mic is on), the Chat button in the window bar reopens it, and
       its launcher shows bottom-right once the hero is scrolled away ---------- */
    const micOn = () => el.micBtn.classList.contains('on');
    const panel = createConversationPanel({
      anchor: $('#hero'), onSubmit: submit, onVoiceToggle: () => el.micBtn.click(),
      onEnd: () => { const s = $('#stop'); if (s && !s.disabled) s.click(); },
      onTyping: () => {}, onViewHomes: () => $('#workspace').scrollIntoView({ block: 'start', behavior: fx.reduced() ? 'auto' : 'smooth' }),
      onEditCriteria: () => { el.text.placeholder = 'Say what to change, e.g. “make it under 800”'; el.text.focus(); }, onRemoveCriteria: () => {},
    });
    $('#panel-open').addEventListener('click', () => { if (panel.isOpen()) panel.minimize(); else panel.open({ view: micOn() ? 'voice' : 'chat', focus: !micOn() }); });
    el.suggestions.addEventListener('click', (e) => { const b = e.target.closest('[data-prompt]'); if (b) submit(b.dataset.prompt); });
    $$('[data-talk]').forEach((b) => b.addEventListener('click', () => {
      if (stage === 'home') { scrollTo({ top: 0, behavior: fx.reduced() ? 'auto' : 'smooth' }); }
      el.micBtn.click();
    }));
    $('[data-refine]').addEventListener('click', () => {
      if (stage === 'home') scrollTo({ top: 0, behavior: fx.reduced() ? 'auto' : 'smooth' });
      setTimeout(() => el.text.focus({ preventScroll: true }), stage === 'home' ? 450 : 0);
    });
    el.views.addEventListener('click', (e) => {
      const b = e.target.closest('[data-view]'); if (!b) return;
      userPickedView = true; setView(b.dataset.view);
      if (el.views.getBoundingClientRect().top < 60) el.views.scrollIntoView({ block: 'start', behavior: fx.reduced() ? 'auto' : 'smooth' });
    });
    // Escape closes the lightbox, then the peek, and must not also reach app.js (where it means "stop talking")
    addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (lb.isOpen()) { e.preventDefault(); e.stopPropagation(); lb.close(); }
      else if (el.peek.open) { e.stopPropagation(); }
    }, true);

    function setView(v) {
      view = v;
      $$('[data-view]', el.views).forEach((b) => { const on = b.dataset.view === v; b.classList.toggle('is-on', on); b.setAttribute('aria-selected', String(on)); });
      placeView($('.is-on', el.views));
      [el.walk, el.table, el.steps, el.changes].forEach((p) => { p.hidden = p.dataset.view !== v; });
      if (v === 'table') renderTable(); if (v === 'steps') renderSteps(); if (v === 'changes') renderChanges();
    }
    function setStage(s) {
      if (stage === s) return; const from = stage; stage = s; html.dataset.stage = s;
      if (s === 'home') { el.composerHome.append(el.composer); }
      else if (from === 'home') { el.dock.append(el.composer); scrollTo({ top: 0 }); }
      typing.sync();
    }
    html.dataset.stage = 'home'; html.dataset.phase = 'idle';

    /* ---------- the needs (page properties + sidebar) ---------- */
    function renderNeeds(chips) {
      const byDim = new Map(chips.map((c) => [c.dim, c]));
      el.props.innerHTML = NEEDS.map(([dim, name, ic]) => {
        const c = byDim.get(dim);
        const v = c ? `<span class="tag need ${c.cls}${c.fresh ? ' fx-new' : ''}" style="--d:${c.i * 50}ms"${c.cls.includes('remembered') ? ' title="From last time"' : ''}>${c.cls.includes('set') ? `<span class="tk">${TICK}</span>` : ''}${esc(c.text)}</span>` : 'Empty';
        return `<div class="nt-prop"><span class="k">${icon(ic)}${name}</span><span class="v${c ? '' : ' empty'}">${v}</span></div>`;
      }).join('') + chips.filter((c) => c.dim.startsWith('extra')).map((c) => `<div class="nt-prop"><span class="k">${icon('sparkle')}Also</span><span class="v"><span class="tag need set">${esc(c.text)}</span></span></div>`).join('');
      el.sideNeeds.innerHTML = chips.length ? chips.map((c) => `<li class="need-${c.cls.split(' ')[0]}">${icon(c.ic)}<span>${esc(c.text)}</span></li>`).join('') : '<li class="muted">Nothing yet</li>';
    }
    let lastChipKeys = new Set();

    /* ---------- sources (sidebar checklist) ---------- */
    function renderSources() {
      const list = [...sources.values()];
      if (!list.length) { el.sources.innerHTML = '<li class="stg">Checked once you’ve said what you need</li>'; el.sourcesCount.textContent = ''; fx.queueBar(el.qbar, 0, 0); return; }
      const done = list.filter((s) => s.status === 'done' || s.status === 'failed').length;
      el.sourcesCount.textContent = `${done}/${list.length}${list.some((s) => s.via === 'zetaris') ? ' · via Zetaris' : ''}`;
      fx.queueBar(el.qbar, done, list.length);
      const out = [];
      STAGES.forEach(([st, name]) => {
        const here = list.filter((s) => s.stageKey === st);
        if (!here.length && !STAGE_EMPTY[st]) return;
        out.push(`<li class="stg">${esc(name)}${!here.length ? `<small>${esc(STAGE_EMPTY[st])}</small>` : ''}</li>`);
        here.forEach((s) => { const st = s.status === 'done' || s.status === 'failed' ? s.status : 'running';
          const tip = s.via === 'zetaris' ? `Zetaris${s.request_id ? ' query ' + s.request_id : ''}${s.cached ? ' (earlier query)' : ''}\n${s.sql || ''}${s.error ? '\n' + s.error : ''}` : (s.table || '') + ' · ' + (s.request_id || '') + (s.mock ? ' · simulated' : '');
          out.push(`<li class="src ${st}" data-name="${esc(s.name)}" title="${esc(tip)}"><span class="ck">${TICK}</span><span class="nm">${esc((s.label || s.name).replace(/-/g, '‑'))}</span><span class="n">${st === 'done' ? `${Number(s.rows || 0).toLocaleString('en-AU')} rows · ${fmtMs(s.ms)}${s.cached ? ' · earlier' : ''}` : st === 'failed' ? 'no answer' : 'checking…'}</span></li>`); });
      });
      // rows inserted already done stay still; a row that was "checking…" a moment ago draws its tick (#014)
      const wasRunning = new Set($$('li.src.running', el.sources).map((li) => li.dataset.name));
      el.sources.innerHTML = out.join('');
      $$('li.src.done', el.sources).forEach((li) => { if (wasRunning.has(li.dataset.name) && !fx.reduced()) { li.classList.replace('done', 'running'); void li.offsetWidth; li.classList.replace('running', 'done'); } });
    }

    /* ---------- the shortlist ---------- */
    const ordered = () => [...cards.values()].sort((a, b) => a.rank - b.rank);
    const placeOf = (id) => catalog.get(id) || (cards.get(id) && cards.get(id).L) || null;
    const coverOf = (L) => { const C = catalog.get(L.id) || {}; return L.image || C.image || (C.images && C.images[0] && C.images[0].url) || ''; };
    const counts = (cells) => { const n = { supported: 0, inferred: 0, conflict: 0, unknown: 0 }; (cells || []).forEach((c) => { if (n[c.status] != null) n[c.status]++; }); return n; };
    function renderSideShort() {
      panel.setResults(cards.size);  // the panel's "View N homes" button
      const list = ordered();
      el.sideShort.innerHTML = list.length ? list.map((r) => `<li class="${r.L.id === mainId ? 'on' : ''}"><button type="button" data-show="${esc(r.L.id)}"><span class="rk">${r.rank}</span><span>${esc(splitTitle(r.L)[0])}</span></button></li>`).join('') : '<li class="muted">Empty</li>';
    }
    el.sideShort.addEventListener('click', (e) => { const b = e.target.closest('[data-show]'); if (b) { userPickedView = false; setView('walk'); showMain(b.dataset.show); } });

    function rowHTML(rec, c, flashSet) {
      const key = rec.L.id + '|' + c.dim; const lit = key === litKey;
      const short = c.short && !STATUS_WORDS.has(String(c.short).toLowerCase()) ? c.short : '';
      const was = rec.was.has(c.dim) && rec.was.get(c.dim) !== c.status ? `<span class="was">was ${esc(STATUS[rec.was.get(c.dim)] || rec.was.get(c.dim))}</span>` : '';
      const tags = pill(c.status) + (c.hard && c.status === 'unknown' ? tag('confirm', 'To confirm') : '') + (rec.see && rec.see.has(c.dim) ? tag('see_at_viewing', 'See at the viewing') : nextTag(c.status !== 'supported' ? c.next : null))
        + (c.photo ? tag('photo', 'photo') : '') + (c.plan ? tag('photo', 'plan' + (c.confidence ? ' · ' + c.confidence : '')) : '') + (c.estimate ? tag('plain', 'estimate') : '') + (rec.ask.has(c.dim) && c.status !== 'supported' ? tag('ask_agent', 'Best question') : '');
      const ev = evCache.get(key); const open = ev && (lit || openRows.has(key));
      return `<div class="nt-row ${esc(c.status)}${lit ? ' lit' : ''}${flashSet && flashSet.includes(c.dim) ? ' flash' : ''}" data-dim="${esc(c.dim)}" role="listitem" tabindex="0" aria-expanded="${open ? 'true' : 'false'}">
        <span class="ic">${sIcon(c.status)}</span><span class="lb">${esc(c.label)}${c.hard ? '' : '<small>nice to have</small>'}</span><span class="vl">${esc(short)} ${was}</span><span class="tg">${tags}</span></div>${open ? evHTML(ev) : ''}`;
    }
    function evHTML(ev) {
      const items = ev.items || [];
      return `<div class="nt-ev" data-for="${esc(ev.dim)}"><div class="nt-ev-h">${icon('doc')}Evidence for ${esc(ev.label || ev.dim)} · ${items.length} item${items.length === 1 ? '' : 's'}</div>${items.map((e) => `<div class="nt-ev-item"><p><span class="tag plain">${esc(sourceName(e))}</span> ${esc(plainLine(e.text, e))}</p>${e.image ? `<img src="${esc(e.image)}" alt="" loading="lazy">` : ''}<div class="nt-ev-meta" title="${esc(provTitle(e))}">${esc(e.table || '')}${e.row ? ' · row ' + esc(e.row) : ''}${esc(prov(e))}${e.read_by ? ' · read by ' + esc(modelName(e.read_by)) : ''}</div></div>`).join('')}</div>`;
    }
    function renderMain(rec, flash) {
      if (!rec) return;
      const L = rec.L; const C = catalog.get(L.id) || {};
      const [street, suburb] = splitTitle(L); const n = counts(L.cells);
      const special = C.special ? `<div class="nt-special"><b>What stands out</b>${esc(sentence(C.special))}</div>` : '';
      const countsHTML = ['supported', 'inferred', 'conflict', 'unknown'].filter((s) => n[s]).map((s) => `<span class="tag status dot ${s}">${n[s]} ${STATUS[s]}</span>`).join('');
      const rowsHTML = (L.cells || []).map((c) => rowHTML(rec, c, flash)).join('');
      const titleHTML = `${esc(street)}${rec.moved ? `<span class="nt-moved">${esc(rec.moved)}</span>` : ''}`;
      const cur = $('#main-slot > .nt-place', el.walk);
      if (cur && cur.dataset.id === L.id) {  // same place: patch the parts that change, so the cover photo does not reload on every line
        $('.nt-place-icon', cur).textContent = '#' + rec.rank; $('.nt-place-title', cur).innerHTML = titleHTML;
        $('.nt-counts', cur).innerHTML = countsHTML; $('.nt-checks', cur).innerHTML = rowsHTML;
        const sp = $('.nt-special', cur); if (sp && !special) sp.remove(); else if (!sp && special) $('.nt-checks', cur).insertAdjacentHTML('afterend', special);
        renderOthers(); followLit(cur); return;
      }
      const html_ = `<article class="nt-place" data-id="${esc(L.id)}">
        <div class="nt-cover">${coverOf(L) ? `<img src="${esc(coverOf(L))}" alt="">` : ''}<span class="nt-credit">${esc(photoTag(C.id ? C : L))}</span></div>
        <div class="nt-place-in">
          <div class="nt-place-icon">#${rec.rank}</div>
          <h3 class="nt-place-title">${titleHTML}</h3><p class="nt-place-sub">${esc(suburb)}${C.postcode ? ' ' + esc(C.postcode) : ''}</p>
          <div class="nt-place-specs">${specRow({ ...L, parking: L.parking != null ? L.parking : C.parking })}${isReal(C) ? tag('real', 'Real listing') : tag('synthetic', 'Synthetic place')}</div>
          <div class="nt-checks-h"><h4>Checks</h4><div class="nt-counts">${countsHTML}</div></div>
          <div class="nt-checks" role="list">${rowsHTML}</div>
          ${special}
          <div class="nt-place-acts"><button type="button" class="nt-btn nt-btn-secondary nt-btn-sm" data-open="${esc(L.id)}">Open page</button></div>
        </div></article>`;
      let host = $('.nt-walk', el.walk);
      if (!host) { el.walk.innerHTML = '<div class="nt-walk"><div id="main-slot"></div><aside class="nt-others" id="others"></aside></div>'; host = $('.nt-walk', el.walk); }
      const slot = $('#main-slot', host); const isNew = !slot.firstElementChild || slot.firstElementChild.dataset.id !== L.id;
      slot.innerHTML = html_;
      if (isNew && !fx.reduced()) slot.firstElementChild.animate([{ opacity: 0, transform: 'translateX(-14px)' }, { opacity: 1, transform: 'none' }], { duration: 420, easing: 'cubic-bezier(.2,.8,.2,1)' });
      renderOthers(); followLit(slot);
    }
    function followLit(root) {  // keep the line being discussed on screen, unless the renter has just scrolled somewhere themselves
      const lit = $('.nt-row.lit', root);
      if (!lit || stage === 'home' || performance.now() - lastScrollByUser < 4000 || el.peek.open) return;
      const r = lit.getBoundingClientRect(); if (r.top < 70 || r.bottom > innerHeight - 110) lit.scrollIntoView({ block: 'center', behavior: fx.reduced() ? 'auto' : 'smooth' });
    }
    function renderOthers() {
      const box = $('#others', el.walk); if (!box) return;
      const list = ordered().filter((r) => r.L.id !== mainId);
      box.innerHTML = list.length ? `<p class="nt-side-h">Also on the shortlist</p>${list.map((r) => { const [st, sb] = splitTitle(r.L); return `<button type="button" class="nt-mini" data-show="${esc(r.L.id)}">${coverOf(r.L) ? `<img src="${esc(coverOf(r.L))}" alt="" loading="lazy">` : ''}<span class="in"><b>#${r.rank} ${esc(st)}</b><span>${esc(sb)} · ${money(r.L.rent)}/wk</span><span class="dots">${(r.L.cells || []).map((c) => `<i class="${esc(c.status)}" title="${esc(c.label + ': ' + (STATUS[c.status] || c.status))}"></i>`).join('')}</span></span></button>`; }).join('')}` : '';
    }
    el.walk.addEventListener('click', (e) => {
      const show = e.target.closest('[data-show]'); if (show) { showMain(show.dataset.show); return; }
      const open = e.target.closest('[data-open]'); if (open) { openPeek(open.dataset.open); return; }
      const row = e.target.closest('.nt-row'); if (row) toggleRow(row);
    });
    el.walk.addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('nt-row')) { e.preventDefault(); toggleRow(e.target); } });
    function toggleRow(row) {
      const key = mainId + '|' + row.dataset.dim;
      if (!evCache.has(key)) { toast(`Evidence for <b>${esc(row.querySelector('.lb').firstChild.textContent)}</b> opens when the line comes up.`, 3600); return; }
      if (openRows.has(key) || key === litKey) { openRows.delete(key); if (key === litKey) litKey = null; } else openRows.add(key);
      renderMain(cards.get(mainId));
    }
    function showMain(id) { if (!cards.has(id)) return; mainId = id; renderMain(cards.get(id)); renderSideShort(); }
    function rankChanged(rec, from, to) { rec.moved = to < from ? `↑ now #${to}` : `↓ now #${to}`; setTimeout(() => { rec.moved = null; if (rec.L.id === mainId) renderMain(rec); }, 6000); }

    /* ---------- table view (#217) ---------- */
    function renderTable() {
      const list = ordered();
      if (!list.length) { el.table.innerHTML = '<p class="nt-small">The table fills in with the shortlist.</p>'; return; }
      const dims = []; const label = new Map();
      list.forEach((r) => (r.L.cells || []).forEach((c) => { if (!label.has(c.dim)) { label.set(c.dim, c.label); dims.push(c.dim); } }));
      const cell = (r, d) => (r.L.cells || []).find((c) => c.dim === d);
      el.table.innerHTML = `<div class="nt-tbl-top"><span>${list.length} places · ${dims.length} needs</span><button type="button" class="fx-switch" role="switch" aria-checked="false" id="diff-only"><i></i>Differences only</button></div>
        <div class="nt-tbl-scroll"><div class="nt-tbl" id="tbl" role="table" style="--cols:${list.length}">
        <div class="nt-tbl-hd" role="row"><span class="c0">Need</span>${list.map((r, i) => { const [st, sb] = splitTitle(r.L); return `<span class="c" data-col="${i}" role="columnheader">#${r.rank} ${esc(st)}<small>${esc(sb)} · ${money(r.L.rent)}/wk</small></span>`; }).join('')}</div>
        ${dims.map((d) => { const sts = list.map((r) => (cell(r, d) || {}).status || ''); const same = sts.every((s) => s === sts[0]);
          return `<div class="nt-tbl-rw${same ? ' same' : ''}" role="row"><div class="in"><span class="c0" role="rowheader">${esc(label.get(d))}</span>${list.map((r, i) => { const c = cell(r, d); return `<span class="c" data-col="${i}" role="cell">${c ? pill(c.status) : '<span class="nt-small">–</span>'}${c && c.short && !STATUS_WORDS.has(String(c.short).toLowerCase()) ? `<span class="nt-small">${esc(c.short)}</span>` : ''}</span>`; }).join('')}</div></div>`; }).join('')}
        </div></div>`;
      fx.compareTable($('#tbl', el.table), $('#diff-only', el.table));
    }

    /* ---------- next steps view ---------- */
    function renderSteps() {
      const list = ordered();
      if (!list.length) { el.steps.innerHTML = '<p class="nt-small">Next steps appear with the shortlist.</p>'; return; }
      el.steps.innerHTML = `<div class="nt-steps">${list.map((r) => {
        const [st] = splitTitle(r.L); const cells = r.L.cells || [];
        const group = (n) => cells.filter((c) => c.status !== 'supported' && (n === 'see_at_viewing' ? (c.next === n || (r.see && r.see.has(c.dim))) : c.next === n));
        const li = (c) => `<li><span>${esc(c.label)}</span><span class="t">${pill(c.status)}${c.hard && c.status === 'unknown' ? tag('confirm', 'To confirm') : ''}</span></li>`;
        const blocks = [['ask_agent', 'Ask the agent'], ['see_at_viewing', 'See at the viewing'], ['check_at_signing', 'Check at signing']].map(([k, t]) => { const g = group(k); return g.length ? `<p class="sub" style="margin-top:12px">${tag(k, t)}</p><ul>${g.map(li).join('')}</ul>` : ''; }).join('');
        return `<div class="nt-step-card"><h5>#${r.rank} ${esc(st)}</h5><p class="sub">${esc(splitTitle(r.L)[1])} · ${money(r.L.rent)}/wk</p>${r.qtext ? `<div class="best">${esc(sentence(r.qtext))}</div>` : ''}${blocks || '<p class="nt-small">Nothing open: every line is backed.</p>'}</div>`;
      }).join('')}</div>`;
    }

    /* ---------- changes view (#271) ---------- */
    function renderChanges() {
      el.changesCount.textContent = String(changes.length);
      if (!changes.length) { el.changes.innerHTML = `<div class="nt-empty">${ASK}<div><p class="nt-sub">Nothing has changed yet.</p><p class="nt-small">Tell me what the agent said, like “the agent said pets are fine”.</p></div></div>`; return; }
      const hasEarlier = changes.some((c) => c.earlier);
      el.changes.innerHTML = `${hasEarlier ? `<div class="fx-cl-chips" id="cl-chips"><button type="button" class="fx-cl-chip is-on" data-filter="all">All</button><button type="button" class="fx-cl-chip" data-filter="now">This visit</button><button type="button" class="fx-cl-chip" data-filter="earlier">Earlier</button><i class="fx-knob" aria-hidden="true"></i></div>` : ''}
        <ol class="nt-cl">${changes.map((ev, i) => {
          const addr = (() => { const r = cards.get(ev.listing_id); const C = catalog.get(ev.listing_id); return r ? splitTitle(r.L)[0] : C ? splitTitle(C)[0] : ev.street || ev.listing_id; })();
          const src = SOURCE_NAMES[ev.source] || sentence(String(ev.source || '').replace(/_/g, ' '));
          const when = ev.ts ? (ev.earlier ? fmtWhen(ev.ts) : String(ev.ts).slice(11, 16)) : '';
          return `<li class="fx-cl-en${i === 0 && !ev.earlier ? ' new' : ''}" data-kind="${ev.earlier ? 'earlier' : 'now'}"><div class="in"><time>${esc(when)}</time><span class="fx-cl-dot"></span><div class="fx-cl-body"><h6>${esc(addr)}</h6>
            <div class="ln"><span>${esc(ev.label)}</span>${pill(ev.from)}<span aria-label="to">→</span>${pill(ev.to)}</div>
            <div class="meta">${esc(src)}${ev.version ? ` · <span class="ver">v${esc(ev.from_version)} → v${esc(ev.version)}</span>` : ''}${ev.reader === 'llm' ? ' · read by ' + esc(modelName(ev.model || 'Nemotron')) : ''}${ev.reranked ? ' · ' + esc(ev.reranked) : ''}</div></div></div></li>`;
        }).join('')}</ol>`;
      const chips = $('#cl-chips', el.changes);
      if (chips) { const place = fx.slider(chips, $('.fx-knob', chips)); requestAnimationFrame(() => place($('.is-on', chips), false)); fx.changelog(el.changes, place); }
    }

    /* ---------- explore: the gallery ---------- */
    const priceText = (L) => (unit === 'week' ? `${money(L.rent)} / wk` : `${money(Math.round((L.rent * 52) / 12))} / mo`);
    function renderGallery() {
      const all = [...catalog.values()];
      const list = all.filter((L) => (filter === 'all' ? true : filter === 'real' ? isReal(L) : !isReal(L)));
      $('#n-all').textContent = all.length; $('#n-real').textContent = all.filter(isReal).length; $('#n-syn').textContent = all.filter((L) => !isReal(L)).length;
      el.gallery.innerHTML = list.map((L) => {
        const [st, sb] = splitTitle(L);
        return `<button type="button" class="nt-gcard fx-card" data-open="${esc(L.id)}">
          <span class="cv">${coverOf(L) ? `<img src="${esc(coverOf(L))}" alt="" loading="lazy">` : ''}<span class="tags">${isReal(L) ? tag('real', 'Real listing') : tag('synthetic', 'Synthetic')}${L.floorplan ? tag('plain', '3D plan') : ''}</span></span>
          <span class="meta"><span class="av" aria-hidden="true">${isReal(L) ? 'D' : 'S'}</span><span><span class="t">${esc(st)}</span><span class="s">${esc(sb)}</span>${specRow(L, { rent: false, date: false, cls: 'sm' })}</span><span class="price" data-price="${esc(L.id)}">${priceText(L)}</span></span></button>`;
      }).join('');
      $$('[data-price]', el.gallery).forEach((n) => { n.dataset.val = n.textContent; });
      fx.reveal($$('.nt-gcard', el.gallery));
    }
    el.gallery.addEventListener('click', (e) => { const b = e.target.closest('[data-open]'); if (b) openPeek(b.dataset.open); });
    const exF = $('#ex-filter'), exU = $('#ex-unit');
    const placeF = fx.slider(exF, $('.fx-knob', exF)), placeU = fx.slider(exU, $('.fx-knob', exU));
    requestAnimationFrame(() => { placeF($('.is-on', exF), false); placeU($('.is-on', exU), false); });
    exF.addEventListener('click', (e) => { const b = e.target.closest('[data-f]'); if (!b) return; $$('[data-f]', exF).forEach((o) => o.classList.toggle('is-on', o === b)); placeF(b); filter = b.dataset.f; renderGallery(); });
    exU.addEventListener('click', (e) => { const b = e.target.closest('[data-u]'); if (!b) return; $$('[data-u]', exU).forEach((o) => o.classList.toggle('is-on', o === b)); placeU(b); unit = b.dataset.u; $$('[data-price]', el.gallery).forEach((n) => fx.roll(n, priceText(catalog.get(n.dataset.price)))); });
    fetch('/api/listings').then((r) => r.json()).then((d) => {
      (d.listings || []).forEach((L) => catalog.set(L.id, L));
      const all = [...catalog.values()]; const real = all.filter(isReal).length;
      $('#explore-lede').textContent = `${real} real Sydney rentals, ${all.length - real} synthetic.`;
      renderGallery(); if (mainId) renderMain(cards.get(mainId));
    }).catch(() => { el.gallery.innerHTML = '<p class="nt-small">The list of places did not load. Is the server running?</p>'; });

    /* ---------- a place, opened as a page: Notion's centre peek, laid out like notion.com/careers. A short hero (address, five
       numbers, the cover), then every check as a small bordered card (bold name, one grey line, its label), grouped by topic the way
       careers groups open positions by department, with a "Filter by" row; photos, the 3D plan and features below ---------- */
    let dollhouse = null;
    const groupOf = (dim) => String(dim || '').charAt(0);
    function placeChecks(L, rec) {
      const byDim = new Map();
      (L.facts || []).forEach((f) => byDim.set(f.dim, { dim: f.dim, label: f.label, ev: f.evidence || [] }));
      ((rec && rec.L.cells) || []).forEach((c) => { const x = byDim.get(c.dim) || { dim: c.dim, label: c.label, ev: [] }; x.cell = c; x.label = c.label || x.label; byDim.set(c.dim, x); });
      byDim.forEach((x) => { const lv = evCache.get(L.id + '|' + x.dim); if (lv && (lv.items || []).length) x.ev = lv.items; });
      return [...byDim.values()];
    }
    // on a card, a photo reading keeps only the part about this line: "Living room: finishes look good (…)" (the whole reading opens below)
    const PHOTO_PICK = { C2: /^(stamped|furniture in view)/i, C3: /cooktop|burner|stove|oven|induction/i, D1: /^finishes/i };
    function cardLine(e, dim) {
      if (e.table === 'photo_facts' && PHOTO_PICK[dim]) {
        const parts = String(e.text || '').split(/;\s*/); const room = (/^(.+?) photo$/i.exec(parts[0]) || [])[1];
        const hit = parts.find((p) => PHOTO_PICK[dim].test(p));
        if (hit) return sentence(`${room ? room + ': ' : ''}${hit.replace(/\.$/, '')}`) + '.';
      }
      return plainLine(e.text, e);
    }
    function checkCard(x) {
      const c = x.cell; const e0 = x.ev[0];
      const short = c && c.short && !STATUS_WORDS.has(String(c.short).toLowerCase()) ? sentence(String(c.short)) : '';
      const line = short || (e0 ? cardLine(e0, x.dim) : 'Nothing on file.');
      const srcs = srcIcons([...new Set(x.ev.map(sourceName))].slice(0, 4));
      const stages = [...new Set(x.ev.map(stageOf))].join(' ');
      const tags = c ? pill(c.status) + (c.hard && c.status === 'unknown' ? tag('confirm', 'To confirm') : '') + (c.status !== 'supported' ? nextTag(c.next) : '') : '';
      return `<article class="pp-card${c ? ' ' + esc(c.status) : ''}" data-dim="${esc(x.dim)}" data-status="${c ? esc(c.status) : ''}" data-stages="${esc(stages)}" role="listitem">
        <button type="button" class="pp-card-btn" aria-expanded="false"${x.ev.length ? '' : ' disabled'}><span class="t">${esc(x.label)}</span><span class="v">${esc(line)}</span><span class="f">${tags}${srcs ? `<span class="src">${srcs}</span>` : ''}</span></button>
        <div class="pp-ev" hidden>${x.ev.map((e) => `<div class="pp-ev-item"><span class="tag plain">${esc(sourceName(e))}</span><p>${esc(plainLine(e.text, e))}</p>${e.image ? `<img src="${esc(e.image)}" alt="" loading="lazy">` : ''}<span class="m" title="${esc(provTitle(e))}">${esc(e.table || '')}${e.row ? ' · row ' + esc(e.row) : ''}${e.via || e.request_id ? esc(prov(e)) : e.material_id ? ' · ' + esc(e.material_id) : ''}${e.read_by ? ' · read by ' + esc(modelName(e.read_by)) : ''}</span></div>`).join('')}</div></article>`;
    }
    function openPeek(id) {
      const L = catalog.get(id) || (cards.get(id) && cards.get(id).L); if (!L) return;
      const rec = cards.get(id); panel.suspend();
      const [street, suburb] = splitTitle(L);
      const photos = [...(L.images || []).map((im) => ({ src: im.url, caption: im.caption || 'Photo', condition: im.condition })), ...(!L.images && L.image ? [{ src: L.image, caption: L.photo_caption || 'Photo' }] : [])];
      const checks = placeChecks(L, rec);
      const commute = L.commute ? Object.entries(L.commute).map(([k, v]) => `<article class="pp-card" data-status="" data-stages="public" role="listitem"><div class="pp-card-btn static"><span class="t">${esc(DEST[k] || sentence(k))}</span><span class="v ic">${icon('train')}${esc(v.min)} min · ${esc(v.mode || 'transit')}</span><span class="f">${v.estimate ? tag('plain', 'estimate') : ''}<span class="src">${srcIcons([v.estimate ? 'Distance estimate' : 'Transit table'])}</span></span></div></article>`) : [];
      const groups = GROUPS.map(([g, name]) => {
        const here = checks.filter((x) => groupOf(x.dim) === g).map(checkCard);
        if (g === 'G') here.push(...commute);
        return here.length ? `<section class="pp-group" data-group="${g}"><h3>${esc(name)}</h3><div class="pp-grid" role="list">${here.join('')}</div></section>` : '';
      }).join('');
      const nChecks = checks.length + commute.length;
      const n = rec ? counts(rec.L.cells) : null;
      const stagesHere = [...new Set(checks.flatMap((x) => x.ev.map(stageOf)))].filter((s) => STAGE_SHORT[s]);
      const tiles = photos.slice(0, photos.length >= 5 ? 5 : photos.length >= 3 ? 3 : photos.length);
      const nav = [['pp-checks', 'Checks', nChecks], photos.length ? ['pp-photos', 'Photos', photos.length] : null, L.floorplan ? ['pp-plan', '3D plan', ''] : null, (L.features || []).length ? ['pp-features', 'Features', L.features.length] : null, ['pp-text', isReal(L) ? 'Listing text' : 'What stands out', '']].filter(Boolean);
      const words = Array.isArray(L.description) && L.description.length
        ? `${L.headline ? `<p class="pp-hl">${esc(sentence(String(L.headline).toLowerCase().replace(/\s+/g, ' ')))}</p>` : ''}<div class="nt-acc pp-acc"><div class="fx-acc"><button type="button" class="fx-acc-q" aria-expanded="false">Full description<span class="fx-acc-pm" aria-hidden="true"></span></button><div class="fx-acc-body"><div class="fx-acc-a">${L.description.map((p) => `<p>${esc(p)}</p>`).join('')}</div></div></div></div><p class="pp-credit">From the listing on Domain${L.source.agency ? ', ' + esc(L.source.agency) : ''}.</p>`
        : `<p class="pp-quote">${esc(sentence(L.special || 'A synthetic place for testing the checks.'))}</p><p class="pp-credit">A synthetic place on a fictional street.</p>`;
      el.peek.innerHTML = `<div class="nt-peek-bar"><button type="button" class="nt-btn nt-btn-quiet nt-btn-xs" data-close aria-label="Close">${icon('close')}</button><span class="nt-crumbs"><span>${rec ? 'Your shortlist' : 'Explore'}</span><span>/</span><b>${esc(street)}</b></span></div>
        <div class="nt-peek-scroll" id="peek-scroll"><div class="pp">
          ${tiles.length ? `<div class="pp-mosaic"><p class="pp-brand">${isReal(L) ? esc(L.source.agency || 'Domain') : 'Synthetic place · illustrative photo'}</p>
            <div class="pp-tiles n${tiles.length}">${tiles.map((p, i) => `<button type="button" class="pp-tile" data-lb="${i}"><img src="${esc(p.src)}" alt="${esc(p.caption)}"${i ? ' loading="lazy"' : ''}></button>`).join('')}
              <div class="pp-tile-acts">${L.floorplan ? `<a class="pp-chip" href="#pp-plan" data-to="pp-plan">${icon('plan')}3D plan</a>` : ''}${photos.length > 1 ? `<a class="pp-chip" href="#pp-photos" data-to="pp-photos" title="All photos">${icon('photo')}${photos.length}</a>` : ''}</div></div></div>
            <p class="pp-credit pp-credit-r">${esc(photoTag(L))}</p>` : ''}
          <header class="pp-head">
            <div>
              <p class="pp-kicker">${isReal(L) ? tag('real', 'Real listing') : tag('synthetic', 'Synthetic place')}${rec ? `<span class="pp-rank">#${rec.rank} on your shortlist</span>` : ''}</p>
              <h1 class="pp-h1">${esc(street)}</h1>
              <p class="pp-sub">${esc(suburb)} ${esc(L.postcode || '')}</p>
              ${specRow(L, { cls: 'lg' })}
            </div>
            <div class="pp-acts">${isReal(L) && L.source.url ? `<a class="nt-btn nt-btn-primary" href="${esc(L.source.url)}" target="_blank" rel="noopener">Listing on Domain ${icon('ext')}</a>` : ''}<a class="nt-btn nt-btn-secondary" href="#pp-checks" data-to="pp-checks">See the checks</a></div>
          </header>
          ${n ? `<div class="pp-verdict">${['supported', 'inferred', 'conflict', 'unknown'].map((s) => `<button type="button" class="pp-vcard ${s}${n[s] ? '' : ' zero'}" data-status="${s}"><b>${n[s]}</b><span class="tag status dot ${s}">${STATUS[s]}</span></button>`).join('')}</div>
            ${rec.qtext ? `<div class="pp-ask">${ASK}<div><p class="nt-eyebrow">Best question for the agent</p><p class="q">${esc(sentence(rec.qtext))}</p></div></div>` : ''}` : ''}
          <nav class="pp-nav" aria-label="On this page">${nav.map(([sid, t, k], i) => `<a href="#${sid}" data-to="${sid}"${i ? '' : ' class="is-on"'}>${esc(t)}${k !== '' ? ` <em>${k}</em>` : ''}</a>`).join('')}<i class="fx-knob" aria-hidden="true"></i></nav>
          <section class="pp-sec" id="pp-checks"><h2 class="pp-h2">Checks</h2>
            <div class="pp-filter"><span>Filter by</span>
              ${n ? `<label class="pp-sel"><span class="sr-only">Label</span><select data-f="status"><option value="">All labels</option>${['supported', 'inferred', 'conflict', 'unknown'].filter((s) => n[s]).map((s) => `<option value="${s}">${STATUS[s]} (${n[s]})</option>`).join('')}</select></label>` : ''}
              <label class="pp-sel"><span class="sr-only">Source</span><select data-f="stage"><option value="">All sources</option>${stagesHere.map((s) => `<option value="${s}">${STAGE_SHORT[s]}</option>`).join('')}</select></label>
              <span class="pp-count" id="pp-count">${nChecks} checks${n ? '' : ' · not run against your needs yet'}</span></div>
            ${groups}<p class="pp-none" hidden>Nothing matches this filter.</p></section>
          ${photos.length ? `<section class="pp-sec" id="pp-photos"><h2 class="pp-h2">Photos</h2><div class="pp-photos">${photos.map((p, i) => `<figure><button type="button" data-lb="${i}"><img src="${esc(p.src)}" alt="${esc(p.caption)}" loading="lazy"></button><figcaption><b>${esc(p.caption)}</b>${p.condition ? `<span>${esc(sentence(p.condition))}</span>` : ''}</figcaption></figure>`).join('')}</div><p class="pp-credit">${esc(photoTag(L))}</p></section>` : ''}
          ${L.floorplan ? `<section class="pp-sec" id="pp-plan"><h2 class="pp-h2">3D plan</h2><div class="nt-dh-slot" id="dh-slot"><div class="nt-dh-load">${icon('plan')}Raising the floor plan…</div></div><figure class="pp-plan"><button type="button" data-plan><img src="${esc(L.floorplan.url)}" alt="Floor plan" loading="lazy"></button><figcaption>The floor plan from the listing</figcaption></figure></section>` : ''}
          ${(L.features || []).length ? `<section class="pp-sec" id="pp-features"><h2 class="pp-h2">Features</h2><div class="pp-feats">${L.features.map((f) => `<div class="pp-feat"><span class="ck">${TICK}</span>${esc(f)}</div>`).join('')}</div></section>` : ''}
          <section class="pp-sec" id="pp-text"><h2 class="pp-h2">${isReal(L) ? 'In the listing’s words' : 'What stands out'}</h2>${words}</section>
        </div></div>`;
      const scroller = $('#peek-scroll', el.peek);
      el.peek.querySelector('[data-close]').onclick = () => el.peek.close();
      const go = (sid) => { const s = $('#' + cssEsc(sid), el.peek); if (s) scroller.scrollTo({ top: s.offsetTop - 56, behavior: fx.reduced() ? 'auto' : 'smooth' }); };
      const sel = (k) => $(`select[data-f="${k}"]`, el.peek);
      const applyFilter = () => {
        const st = sel('status') ? sel('status').value : '', sg = sel('stage').value; let shown = 0;
        $$('.pp-card', el.peek).forEach((c) => { const ok = (!st || c.dataset.status === st) && (!sg || c.dataset.stages.split(' ').includes(sg)); c.hidden = !ok; if (ok) shown++; });
        $$('.pp-group', el.peek).forEach((g) => { g.hidden = !$$('.pp-card:not([hidden])', g).length; });
        $('.pp-none', el.peek).hidden = shown > 0;
        $('#pp-count', el.peek).textContent = st || sg ? `${shown} of ${nChecks}` : `${nChecks} checks${n ? '' : ' · not run against your needs yet'}`;
      };
      $$('select[data-f]', el.peek).forEach((s) => s.addEventListener('change', applyFilter));
      el.peek.onclick = (e) => {
        const lbBtn = e.target.closest('[data-lb]'); if (lbBtn) { lb.open(photos.map((p) => ({ src: p.src, caption: p.caption, alt: p.caption })), Number(lbBtn.dataset.lb), lbBtn.querySelector('img')); return; }
        const plan = e.target.closest('[data-plan]'); if (plan) { lb.open([{ src: L.floorplan.url, caption: 'Floor plan', alt: 'Floor plan' }], 0, plan.querySelector('img')); return; }
        const v = e.target.closest('.pp-vcard'); if (v) { if (sel('status')) { sel('status').value = sel('status').value === v.dataset.status ? '' : v.dataset.status; applyFilter(); } go('pp-checks'); return; }
        const card = e.target.closest('.pp-card-btn:not(.static)'); if (card) {  // a card opens across the whole row to show what backs it
          const box = card.parentElement; const open = box.classList.toggle('open'); card.setAttribute('aria-expanded', String(open)); $('.pp-ev', box).hidden = !open;
          if (open && !fx.reduced()) box.animate([{ opacity: .6, transform: 'scale(.99)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: 'cubic-bezier(.2,.8,.2,1)' });
          return;
        }
        if (e.target === el.peek) el.peek.close();
      };
      el.peek.append(el.lightbox);  // a modal dialog sits in the top layer: the lightbox has to live inside it to show above it
      if (!el.peek.open) el.peek.showModal();
      scroller.scrollTop = 0;
      const navEl = $('.pp-nav', el.peek); const placeNav = fx.slider(navEl, $('.fx-knob', navEl));
      fx.toc(scroller, navEl, { place: placeNav, offset: 120, gap: 56 });
      $$('[data-to]', el.peek).forEach((a) => { if (!navEl.contains(a)) a.addEventListener('click', (e) => { e.preventDefault(); go(a.dataset.to); }); });
      fx.accordion(el.peek);
      fx.reveal($$('.pp-card, .pp-vcard, .pp-photos figure', el.peek));
      if (L.floorplan) mountDollhouse(L, $('#dh-slot', el.peek), scroller);
    }
    el.peek.addEventListener('close', () => { if (dollhouse) { try { dollhouse.destroy(); } catch (e) {} dollhouse = null; } });
    function mountDollhouse(L, slot, scroller) {
      const go = async () => {
        try {
          if (!document.querySelector('link[data-dollhouse]')) { const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/static/qi/dollhouse.css?v=1'; l.dataset.dollhouse = '1'; document.head.append(l); }
          if (!window.HT_DOLLHOUSE) await import('/static/qi/dollhouse.js?v=1');  // three.js is heavy: only fetched once a plan is on screen
          const D = window.HT_DOLLHOUSE;
          if (!D || !(await D.available(L))) { slot.innerHTML = '<p class="nt-small">No room layout has been read from this floor plan yet.</p>'; return; }
          if (!slot.isConnected) return;
          slot.innerHTML = ''; dollhouse = await D.mount(slot, L);
        } catch (e) { slot.innerHTML = `<p class="nt-small">The 3D plan could not load (${esc(e.message || e)}).</p>`; }
      };
      if (!('IntersectionObserver' in window)) { go(); return; }
      const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { io.disconnect(); go(); } }, { root: scroller, rootMargin: '200px' }); io.observe(slot);
    }

    /* ---------- searching state ---------- */
    function resetShortlist() {
      cards.clear(); mainId = null; litKey = null; evCache.clear(); openRows.clear(); sources.clear(); userPickedView = false;
      el.walk.innerHTML = `<div class="nt-empty">${CLIPBOARD}<div><p class="nt-sub">Checking the sources…</p></div></div>`;
      renderSources(); renderSideShort(); if (view !== 'walk') setView('walk');
    }
    const metaRender = () => { el.metaBox.innerHTML = [...metaMap.values()].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join(''); };
    const meta = (k, t) => { metaMap.set(k, t); metaRender(); };
    const titleUpdate = () => {
      const has = cards.size > 0;
      el.title.textContent = has ? 'Your shortlist' : profile ? 'Your search' : 'Untitled search';
      el.title.classList.toggle('placeholder', !profile && !has);
      el.crumb.textContent = has && mainId ? splitTitle(cards.get(mainId).L)[0] : 'Your search';
    };
    let joinTurn = false;

    const ui = {
      el, meta, example: EXAMPLE,
      stage: () => stage,
      state(ev, show = true) {
        if (ev.phase === 'searching') resetShortlist();
        if (show) ui.phase(ev.phase, ev.label);
      },
      phase(p, label) {
        phaseNow = p; html.dataset.phase = p;
        const st = p === 'searching' ? 'thinking' : ['listening', 'thinking', 'speaking', 'error'].includes(p) ? p : micOn() ? 'listening' : 'idle';
        setOrb(st); panel.setState(st);
        const txt = sentence(label || p);
        if (el.phase.textContent !== txt) el.phase.textContent = txt;
        const busy = p === 'thinking' || p === 'searching';
        el.sayPhase.textContent = busy ? (p === 'searching' ? 'Checking the sources…' : txt + '…') : '';
        el.sayPhase.classList.toggle('fx-sheen', busy);
        panel.setStatusText(p === 'searching' ? 'Checking the sources…' : busy ? txt + '…' : '');
        if (p === 'listening' && /your turn/i.test(txt) && panel.isOpen()) panel.focus();
      },
      level(x) { if (orb && orbState === 'listening') orb.setLevel(Math.max(0, Math.min(1, x || 0))); },
      botLevel(x) { if (orb && orbState === 'speaking') orb.setLevel(Math.max(0, Math.min(1, x || 0))); },
      interrupt() { el.caption.classList.add('dim'); },
      caption(t) {
        el.caption.classList.remove('dim', 'hint');
        if (!t) { el.caption.textContent = ''; return; }
        const m = /^best question(?: for this agent)?:\s*(.+)$/i.exec(t); if (m && mainId && cards.get(mainId)) cards.get(mainId).qtext = m[1];
        panel.appendTurn('assistant', t, joinTurn);
        fx.stream(el.caption, t); joinTurn = true;
      },
      transcript(t, interim) {
        el.transcript.innerHTML = t ? `<b>You</b>${esc(t)}` : '';
        el.transcript.classList.toggle('interim', !!interim);
        if (interim && t) panel.setDraft(t);
      },
      userSaid(t) {
        ui.transcript(t, false); panel.setDraft(''); panel.appendTurn('user', t); joinTurn = false;
        if (stage === 'home') { setStage('talk'); panel.open({ view: micOn() ? 'voice' : 'chat' }); }
      },
      error(m) { el.caption.classList.remove('hint', 'dim'); el.caption.innerHTML = `<span class="error">${esc(m)}</span>`; html.dataset.phase = 'error'; setOrb('error'); panel.setState('error'); },
      latency(a, b) { meta('latency', a == null && b == null ? '' : `First event ${a == null ? '–' : a + ' ms'} · first word ${b == null ? '–' : b + ' ms'}`); },
      events(n) { el.metaBox.title = `${n} events this session`; },
      note(t) { el.note.textContent = t || ''; },
      needs(ev) {
        const p = ev.profile || {}; profile = p;
        const ask = new Set(ev.asking || []), assumed = new Set(ev.assumed || []), rem = new Set(ev.remembered || []);
        const chips = []; let i = 0;
        NEEDS.forEach(([dim, , ic, get, askText, assumedText]) => {
          const v = get(p);
          if (v != null) chips.push({ dim, ic, text: v, cls: rem.has(FIELD_OF[dim]) ? 'set remembered' : 'set' });
          else if (ask.has(dim)) chips.push({ dim, ic, text: askText, cls: 'asking' });
          else if (assumed.has(dim)) chips.push({ dim, ic, text: assumedText, cls: 'assumed' });
        });
        (p.extras || []).forEach((x, k) => chips.push({ dim: 'extra' + k, ic: 'sparkle', text: x, cls: rem.has('extras') ? 'set remembered' : 'set' }));
        const keys = new Set(chips.map((c) => c.dim + ':' + c.text + ':' + c.cls));
        chips.forEach((c) => { c.fresh = !lastChipKeys.has(c.dim + ':' + c.text + ':' + c.cls); c.i = c.fresh ? i++ : 0; });
        lastChipKeys = keys;
        panel.setCriteria(chips.map((c) => ({ key: c.dim, label: c.text })));
        renderNeeds(chips);
        if (ev.parser) meta('parser', ev.parser === 'llm' ? `Needs read by Nemotron${ev.parse && ev.parse.provider ? ' via ' + sentence(ev.parse.provider) : ''}` : 'Needs read by rules');
        if (stage === 'home' && !ev.quiet) setStage('talk');
        titleUpdate();
      },
      remembered(mem, actions) {
        if (!mem || !mem.profile) return;
        ui.needs({ profile: mem.profile, remembered: mem.remembered || [], quiet: true });
        const away = mem.away && mem.away.unread ? mem.away : null;
        const open = (mem.open || []).filter((o) => o.street).slice(0, 2);
        const flips = mem.beliefs && mem.beliefs.flips ? mem.beliefs : null;
        const extra = [];
        if (away) extra.push(`<span><b>While you were away:</b> ${away.unread} agent repl${away.unread === 1 ? 'y' : 'ies'} · ${esc([...new Set(away.items.map((it) => it.street || it.listing_id))].join(', '))}</span>`);
        if (open.length) extra.push(`<span><b>Still open:</b> ${esc(open.map((o) => `${String(o.label || o.dim).toLowerCase()} at ${o.street}`).join(' · '))}</span>`);
        if (flips) { const r = flips.recent && flips.recent[0]; extra.push(`<span><b>On file:</b> ${flips.flips} belief flip${flips.flips === 1 ? '' : 's'}${r ? ` · latest ${esc(String(r.label || r.dim).toLowerCase())} at ${esc(r.street || r.listing_id)} v${esc(r.from_version)} → v${esc(r.version)}` : ''}</span>`); }
        el.welcome.innerHTML = `<div class="nt-welcome-box"><p><b>Welcome back.</b> Last time${mem.ago ? ` (${esc(mem.ago)})` : ''} it was ${esc(mem.summary || 'the same search')}. Same again, or has anything changed?</p>${extra.length ? `<p class="extra">${extra.join('')}</p>` : ''}
          <div class="acts"><button type="button" class="nt-btn nt-btn-primary nt-btn-sm" data-act="same">Same again</button><button type="button" class="nt-btn nt-btn-secondary nt-btn-sm" data-act="change">Something’s changed</button><button type="button" class="nt-btn nt-btn-quiet nt-btn-sm" data-act="forget">Forget me</button></div>
          <small>Kept in this browser only</small></div>`;
        el.welcome.hidden = false;
        if (flips && flips.recent) flips.recent.forEach((r) => ui.change({ ...r, type: 'change', earlier: true }));
        el.welcome.onclick = (e) => {
          const b = e.target.closest('[data-act]'); if (!b) return;
          if (b.dataset.act === 'same' && actions && actions.sameAgain) actions.sameAgain();
          else if (b.dataset.act === 'change') { el.text.focus(); el.text.placeholder = 'Tell me what’s different, e.g. “under 800 this time”'; }
          else if (b.dataset.act === 'forget' && actions && actions.forget) actions.forget();
        };
      },
      source(ev) {
        const prev = sources.get(ev.name) || {};
        sources.set(ev.name, { ...prev, ...ev, stageKey: ev.stage || prev.stageKey || STAGE_OF_TABLE[ev.table] || 'public' });
        renderSources();
      },
      card(L) {
        if (!L || !L.id) return;
        const rank = Number(L.rank) || 99;
        let rec = cards.get(L.id);
        if (rec) { rec.L = L; rec.rank = rank; }
        else { rec = { L, rank, ask: new Set(), see: new Set(), was: new Map(), flash: null, moved: null, qtext: null }; cards.set(L.id, rec); }
        if (mainId !== L.id) litKey = null;
        if (stage !== 'results') setStage('results');
        if (view !== 'walk' && !userPickedView) setView('walk');
        joinTurn = false; showMain(L.id); titleUpdate();
        if (view === 'table') renderTable(); if (view === 'steps') renderSteps();
      },
      cardUpdate(ev) {
        const L = ev.listing; const rec = L && cards.get(L.id); if (!rec) return;
        const old = new Map((rec.L.cells || []).map((c) => [c.dim, c.status]));
        const flash = (L.cells || []).filter((c) => (old.has(c.dim) && old.get(c.dim) !== c.status) || (rec.flash && rec.flash.has(c.dim))).map((c) => c.dim);
        flash.forEach((dim) => { if (!rec.was.has(dim) && old.has(dim)) rec.was.set(dim, old.get(dim)); });
        rec.flash = null;
        const rank = Number(L.rank) || rec.rank; const from = rec.rank;
        rec.L = L; rec.rank = rank;
        if (L.id === mainId) renderMain(rec, flash); else renderOthers();
        if (rank !== from) { rankChanged(rec, from, rank); renderSideShort(); renderOthers(); }
        if (view === 'table') renderTable(); if (view === 'steps') renderSteps();
      },
      highlight(ev) {
        const rec = cards.get(ev.listing_id); if (!rec) return;
        if (mainId !== ev.listing_id) { mainId = ev.listing_id; renderSideShort(); }
        litKey = ev.listing_id + '|' + ev.dim;
        if (ev.question) rec.ask.add(ev.dim);
        if (ev.viewing) rec.see.add(ev.dim);
        renderMain(rec); titleUpdate();
      },
      evidence(ev) {
        evCache.set(ev.listing_id + '|' + ev.dim, ev);
        if (mainId === ev.listing_id) renderMain(cards.get(mainId));
      },
      change(ev) {
        const rec = cards.get(ev.listing_id);
        if (rec && ev.dim && !ev.earlier) { if (ev.from && !rec.was.has(ev.dim)) rec.was.set(ev.dim, ev.from); (rec.flash = rec.flash || new Set()).add(ev.dim); }
        const before = ev.rank_before || [], after = ev.rank_after || [];
        const reranked = !ev.earlier && after.length > 0 && before.join() !== after.join();
        const addrOf = (id) => { const r = cards.get(id); return r ? splitTitle(r.L)[0] : id; };
        const entry = { ...ev, reranked: reranked ? 'new order: ' + after.map((id, i) => `#${i + 1} ${addrOf(id)}`).join(', ') : '' };
        if (ev.earlier) changes.push(entry); else changes.unshift(entry);
        el.changesCount.textContent = String(changes.length);
        if (view === 'changes') renderChanges();
        if (ev.earlier) return;
        let moved = '';
        if (reranked) {
          after.forEach((id, i) => { const r = cards.get(id); if (r && r.rank !== i + 1) { const f = r.rank; r.rank = i + 1; rankChanged(r, f, i + 1); if (id === ev.listing_id) moved = ` · now #${i + 1}`; } });
          renderSideShort(); renderOthers();
        }
        const src = SOURCE_NAMES[ev.source] || sentence(String(ev.source || '').replace(/_/g, ' '));
        toast(`<b>${esc(addrOf(ev.listing_id))}</b> · ${esc(ev.label)} <span class="tg">${pill(ev.from)} → ${pill(ev.to)}</span><br><span style="opacity:.7">${esc(src)}${esc(moved)}</span>`);
      },
      meter(db, thr) {
        const pct = (v) => Math.max(0, Math.min(100, ((v + 75) / 60) * 100));
        el.meterBar.style.width = pct(db) + '%'; el.meterThr.style.left = pct(thr) + '%';
        ui.level((db - thr + 10) / 30);
      },
      clear() {
        resetShortlist(); changes.length = 0; renderChanges(); profile = null; lastChipKeys = new Set(); renderNeeds([]);
        el.caption.classList.add('hint'); el.caption.textContent = 'Tell me what you need.'; ui.transcript('', false);
        el.welcome.hidden = true; el.welcome.innerHTML = ''; titleUpdate(); setStage('home');
        panel.reset(); panel.close(); panel.setResults(0); panel.setContext(null);
      },
    };
    renderNeeds([]); renderChanges();
    return ui;
  }
  return { create, esc, fmtDate };
})();
