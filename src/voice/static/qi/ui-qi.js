/* HomeTruth voice tour — fourth-pass renderer (2026-10-26): the qi.home v6 shell driven by the real server events.
   Same interface as ui.js (window.HTUI.create() → state / phase / needs / source / card / cardUpdate / highlight / evidence /
   change / caption / transcript …), so app.js (8630, SSE + Web Audio) and pipecat.js (8631, RTVI over WebRTC) run unchanged.
   From qi.home: the page frame and type, the orbit of photos behind the hero (orbit.js), the Orb (agents-orb.js), the
   conversation panel (conversation-panel.js) and, since the second pass (same day), the browsing grid below the hero
   (collection-motion.js), the property detail page (property-detail.js, modelled on Domain / realestate.com.au), the rental
   filters (rental-filters.js, realestate.com.au parity), the saved list and the two-place comparison (home-compare.js) —
   provenance in README.md next to this file. The filters do not filter locally: they are read out as one sentence and sent
   to the server like anything typed, so the same needs parser and the same evidence checks run.
   Ours: every word on the cards. Each line still says its status in words, the line being discussed is lit, and its evidence
   (table, row, request_id) opens right under it. The photos are illustrative design photos, not the listings' (PHOTOS). */
import { createAgentsOrb } from './agents-orb.js?v=8';
import { createConversationPanel } from './conversation-panel.js?v=8';
import { setupOrbit, liftToResult, resetOrbit, prepareResultTransition, prepareSearch } from './orbit.js?v=6';
import { createPropertyDetail } from './property-detail.js?v=10';
import { setupCollectionMotion } from './collection-motion.js?v=6';
import { createHomeCompare } from './home-compare.js?v=6';
import { mountRentalFilters, emptyRentalFilters, activeRentalFilterCount, FEATURE_GROUPS } from './rental-filters.js?v=6';

window.HTUI = (() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const EASE = 'cubic-bezier(.22,1,.36,1)';
  const RM = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  const cssEsc = (s) => (window.CSS && CSS.escape ? CSS.escape(String(s)) : String(s).replace(/["\\]/g, '\\$&'));
  const fmtDate = (iso) => { if (!iso) return ''; const d = new Date(iso + 'T00:00:00'); return isNaN(d) ? String(iso) : d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' }); };
  const fmtMs = (ms) => (ms == null ? '' : ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms');
  const sentence = (s) => { s = String(s || ''); return s ? s[0].toUpperCase() + s.slice(1) : s; };
  const STATUS = { supported: 'Supported', inferred: 'Inferred', conflict: 'Conflict', unknown: 'Unknown' };
  const STATUS_WORDS = new Set(['yes', 'likely', 'clash', '?']);  // card_payload's short values that only repeat the status
  const SOURCE_NAMES = { agent_reply: 'Agent reply', inbox: 'Agent reply · while you were away', inbox_live: 'Agent reply · just in' };  // change.source (policy.py _apply_reply)
  const fmtWhen = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso || '') : d.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); };
  const EXAMPLE = 'Two bedrooms near Central, under 900 a week, I have a cat, moving mid November';
  const PLACEHOLDER = 'Or type what you need…';
  const TITLE_HOME = 'Tell me what you need.<br>I\u2019ll check every listing.';
  const icon = (name, cls = 'ico') => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const chip = (st) => `<span class="chip ${esc(st)}"><svg class="sico" aria-hidden="true"><use href="#s-${esc(st)}"/></svg>${esc(STATUS[st] || st)}</span>`;
  const splitTitle = (L) => { const t = String(L.title || L.id || ''); const i = t.lastIndexOf(', '); return i > 0 ? [t.slice(0, i), L.suburb || t.slice(i + 2)] : [t, L.suburb || '']; };
  const bedText = (n) => (n === 0 ? 'Studio' : `${n} bed`);
  const modelName = (m) => (/nemotron.*vl|vl.*nemotron|nemotron-3\.5-super/i.test(String(m)) ? 'Nemotron VL' : /nemotron/i.test(String(m)) ? 'Nemotron' : String(m));  // what read the photo (src/photo/facts.py)
  // the detail page's "What the sources say.": one group per need, each evidence row as a sentence, the table named the way a renter would say it
  const TABLE_NAMES = { listings: 'Listing', documents: 'Document', photo_facts: 'Photo', public_rent: 'Rent data', public_transit: 'Transit table', sun_geometry: 'Sun geometry', geo_estimate: 'Distance estimate', floorplan_facts: 'Floor plan' };  // evidence table → what a renter would call it
  const sourceName = (e) => { const row = String(e.row || '') + ' ' + String(e.material_id || ''); if (e.table === 'documents') return /bylaws/i.test(row) ? 'By-laws' : /repl/i.test(row) ? 'Agent reply' : /plan/i.test(row) ? 'Floor plan' : 'Document'; return TABLE_NAMES[e.table] || sentence(String(e.table || 'source').replace(/_/g, ' ')); };
  // the materials, in the order a NSW renter can get them (policy.STAGES, same words as docs/01): the first three are evidence, the last two are only ever "next steps"
  const STAGES = [['listing', 'From the listing'], ['public', 'Public data'], ['agent', 'From the agent'], ['viewing', 'Your viewing'], ['signing', 'At signing']];
  const STAGE_EMPTY = { viewing: 'nothing yet; we’ll say what to look for', signing: 'not used for ranking' };
  const STAGE_OF_TABLE = { listings: 'listing', photo_facts: 'listing', floorplan_facts: 'listing', public_rent: 'public', public_transit: 'public', sun_geometry: 'public', geo_estimate: 'public', documents: 'agent' };  // fallback for an older server that sends no stage
  const stageOf = (e) => (e && e.stage) || STAGE_OF_TABLE[e && e.table] || 'public';
  const NEXT_TEXT = { ask_agent: 'Ask the agent', see_at_viewing: 'See at the viewing', check_at_signing: 'Check at signing' };  // cell.next (policy.next_for) → what the row says
  const plainLine = (text, e) => { let t = String(text || '').trim().replace(/^features:\s*/i, 'Listing features: ').replace(/^By-laws excerpt:\s*/i, 'By-laws: '); if (e.table === 'photo_facts') t = t.replace(/;\s*/g, ', '); t = sentence(t); return /[.!?]$/.test(t) ? t : t + '.'; };
  const asset = (p) => new URL('./assets/' + p, import.meta.url).href;
  // illustrative photos (resident.co.nz design studies, see assets/asset-sources.json), one per candidate listing in /api/listings order
  const PHOTOS = [1, 2, 3, 4, 5, 6].map((n) => asset(`room-${n}.jpg`));
  // real listings (scripts/domain_sample.py) carry their own photos and say where they came from; everything else wears the illustrative set
  const photoTag = (L) => (L && L.source && L.source.listing_id ? `${L.source.site === 'domain.com.au' ? 'Domain' : L.source.site} listing ${L.source.listing_id}` : 'Illustrative photo');
  const rowPills = (c) => (c.photo ? '<span class="row-photo" title="Read from the listing photo by Nemotron VL">photo</span>' : '')
    + (c.plan ? `<span class="row-photo" title="Read from the floor plan by Nemotron VL">plan${c.confidence ? ' · ' + esc(c.confidence) : ''}</span>` : '')
    + (c.estimate ? '<span class="row-photo row-est" title="Estimated from the straight-line distance, not a timetable">estimate</span>' : '');
  const ORB_STATE = { idle: 'idle', paused: 'idle', listening: 'listening', thinking: 'thinking', searching: 'thinking', speaking: 'speaking', error: 'error' };
  // the five must-haves (policy.REQUIRED): icon, the value in words, the chip while we ask for it, the chip when assumed (phraser.ASSUME)
  const FIELD_OF = { A1: 'budget', B1: 'bedrooms', G1: 'anchor', A4: 'move_in', J1: 'pets' };  // dimension → profile field (needs.remembered names fields)
  const NEEDS = [
    ['A1', 'coin', (p) => (p.budget != null ? `Under $${p.budget}/wk` : null), 'Weekly budget?', 'Any budget (assumed)'],
    ['B1', 'n-bed', (p) => (p.bedrooms != null ? (p.bedrooms === 0 ? 'Studio' : `${p.bedrooms} bedroom${p.bedrooms === 1 ? '' : 's'}`) : null), 'How many bedrooms?', 'Any size (assumed)'],
    ['G1', 'pin', (p) => (p.anchor ? `Near ${p.anchor}` : null), 'Close to where?', 'Commute to Central Station (assumed)'],
    ['A4', 'cal', (p) => (p.move_in ? `Move in ${p.move_in}` : null), 'Move-in date?', 'Any move-in date (assumed)'],
    ['J1', 'paw', (p) => (p.pets ? (/^no\b/i.test(p.pets) ? sentence(p.pets) : `With ${p.pets}`) : null), 'Any pets?', 'No pets (assumed)'],
  ];

  const SPRITE = `<svg class="icon-library" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<symbol id="i-logo" viewBox="0 0 24 24"><path d="M3.5 11.2 12 4l8.5 7.2"/><path d="M5.8 9.6V20h12.4V9.6"/><path d="m9.2 14.6 2 2 3.8-4.2"/></symbol>
<symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></symbol>
<symbol id="i-send" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>
<symbol id="i-stop" viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M8.5 5.8v12.4l10-6.2z" fill="currentColor" stroke="none"/></symbol>
<symbol id="i-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v9M14.6 9.6c-.3-.9-1.3-1.5-2.6-1.5-1.5 0-2.6.8-2.6 1.8 0 2.4 5.2 1.1 5.2 3.6 0 1-1.1 1.9-2.6 1.9-1.4 0-2.4-.7-2.7-1.6"/></symbol>
<symbol id="i-n-bed" viewBox="0 0 24 24"><path d="M3 18v-8M3 14h18v4M21 14v-3a2 2 0 0 0-2-2h-7v5"/><circle cx="7" cy="9.5" r="1.8"/></symbol>
<symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0C18.5 15.4 12 21 12 21z"/><circle cx="12" cy="10" r="2.2"/></symbol>
<symbol id="i-cal" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></symbol>
<symbol id="i-paw" viewBox="0 0 24 24"><circle cx="7" cy="9" r="1.7"/><circle cx="11" cy="6.2" r="1.7"/><circle cx="15.8" cy="6.8" r="1.7"/><circle cx="19" cy="10.8" r="1.7"/><path d="M8.2 17.2c0-2.6 2.1-4.7 4.6-4.7s4.6 2.1 4.6 4.7c0 1.5-1.1 2.4-2.4 2.4-1 0-1.5-.5-2.2-.5s-1.2.5-2.2.5c-1.3 0-2.4-.9-2.4-2.4z"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5.5v13M5.5 12h13"/></symbol>
<symbol id="i-ask" viewBox="0 0 24 24"><path d="M4 5.5h16v10.5H10l-6 4z"/><path d="M10.1 9.2a1.9 1.9 0 1 1 2.7 1.7c-.5.25-.8.6-.8 1.1v.2"/><path d="M12 14.1v.01"/></symbol>
<symbol id="i-arrow" viewBox="0 0 16 16"><path d="M3 8h10M9 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="i-q-bed" viewBox="0 0 24 24"><path d="M7 6.55752V8.69783C7.44647 8.82039 8.1239 8.9606 8.96149 8.96475C9.83765 8.96914 10.544 8.82303 11 8.69783V6.55752C10.5059 6.44027 9.79156 6.3179 8.9245 6.32534C8.13001 6.33218 7.47101 6.4457 7 6.55752Z"/><path d="M13 8.69783V6.55752C13.471 6.4457 14.13 6.33218 14.9245 6.32534C15.7916 6.3179 16.5059 6.44027 17 6.55752V8.69783C16.544 8.82303 15.8376 8.96914 14.9615 8.96475C14.1239 8.9606 13.4465 8.82039 13 8.69783Z"/><path fill-rule="evenodd" clip-rule="evenodd" d="M21 10.1843V2H3V10.1843C1.8385 10.5984 1 11.6981 1 13V19H3.52264L2.32263 22H4.47735L5.67736 19H18.3226L19.5226 22H21.6773L20.4773 19H23V13C23 11.6981 22.1615 10.5984 21 10.1843ZM5 4H19V10H5V4ZM21 17H3V13C3 12.4487 3.44873 12 4 12H20C20.5513 12 21 12.4487 21 13V17Z"/></symbol>
<symbol id="i-q-bath" viewBox="0 0 24 24"><path d="M16.8481 8C17.2513 8.56671 17.4937 9.25415 17.498 10H20.5454C20.4912 10.1431 20.4473 10.2915 20.415 10.4443L19.208 17.1733C19.1074 17.6523 18.6182 18 18.0444 18H5.95557C5.38184 18 4.89258 17.6523 4.79786 17.2022L3.57911 10.415C3.54932 10.2725 3.50831 10.1338 3.45802 10H11.0692C11.5861 10.0375 12 10.4554 12 10.9839V13H16V10C16 8.89539 15.1046 8 14 8H9.00002V3.28467C9.00002 2.49219 9.57668 2 10.5049 2C11.4273 2 12 2.49219 12 3.28467V3.99268H14V3.28467C14 1.38135 12.5303 0 10.5049 0C8.47414 0 7.00002 1.38135 7.00002 3.28467V8H0V10H0.45801C1.03174 10 1.521 10.3477 1.61621 10.7978L2.83496 17.5845C3.01129 18.4239 3.55823 19.1198 4.29126 19.5468L3.31262 22H5.4657L6.26355 20H17.7365L18.5343 22H20.6874L19.7082 19.5455C20.4423 19.1157 20.991 18.4128 21.1709 17.5557L22.3779 10.8271C22.479 10.3476 22.9683 9.99999 23.542 9.99999H24V7.99999H16.8481V8Z"/></symbol>
<symbol id="i-bed" viewBox="0 0 24 24"><path d="M7 6.55752V8.69783C7.44647 8.82039 8.1239 8.9606 8.96149 8.96475C9.83765 8.96914 10.544 8.82303 11 8.69783V6.55752C10.5059 6.44027 9.79156 6.3179 8.9245 6.32534C8.13001 6.33218 7.47101 6.4457 7 6.55752Z" fill="currentColor"/><path d="M13 8.69783V6.55752C13.471 6.4457 14.13 6.33218 14.9245 6.32534C15.7916 6.3179 16.5059 6.44027 17 6.55752V8.69783C16.544 8.82303 15.8376 8.96914 14.9615 8.96475C14.1239 8.9606 13.4465 8.82039 13 8.69783Z" fill="currentColor"/><path fill-rule="evenodd" clip-rule="evenodd" d="M21 10.1843V2H3V10.1843C1.8385 10.5984 1 11.6981 1 13V19H3.52264L2.32263 22H4.47735L5.67736 19H18.3226L19.5226 22H21.6773L20.4773 19H23V13C23 11.6981 22.1615 10.5984 21 10.1843ZM5 4H19V10H5V4ZM21 17H3V13C3 12.4487 3.44873 12 4 12H20C20.5513 12 21 12.4487 21 13V17Z" fill="currentColor"/></symbol>
<symbol id="i-bath" viewBox="0 0 24 24"><path d="M16.8481 8C17.2513 8.56671 17.4937 9.25415 17.498 10H20.5454C20.4912 10.1431 20.4473 10.2915 20.415 10.4443L19.208 17.1733C19.1074 17.6523 18.6182 18 18.0444 18H5.95557C5.38184 18 4.89258 17.6523 4.79786 17.2022L3.57911 10.415C3.54932 10.2725 3.50831 10.1338 3.45802 10H11.0692C11.5861 10.0375 12 10.4554 12 10.9839V13H16V10C16 8.89539 15.1046 8 14 8H9.00002V3.28467C9.00002 2.49219 9.57668 2 10.5049 2C11.4273 2 12 2.49219 12 3.28467V3.99268H14V3.28467C14 1.38135 12.5303 0 10.5049 0C8.47414 0 7.00002 1.38135 7.00002 3.28467V8H0V10H0.45801C1.03174 10 1.521 10.3477 1.61621 10.7978L2.83496 17.5845C3.01129 18.4239 3.55823 19.1198 4.29126 19.5468L3.31262 22H5.4657L6.26355 20H17.7365L18.5343 22H20.6874L19.7082 19.5455C20.4423 19.1157 20.991 18.4128 21.1709 17.5557L22.3779 10.8271C22.479 10.3476 22.9683 9.99999 23.542 9.99999H24V7.99999H16.8481V8Z" fill="currentColor"/></symbol>
<symbol id="i-heart" viewBox="0 0 24 24"><path d="M19.1768 22.8281L12.4653 19.2998C12.1743 19.1465 11.8257 19.1465 11.5347 19.2998L4.82324 22.8281L6.10498 15.355C6.16113 15.0303 6.05322 14.6992 5.81738 14.4692L0.387207 9.17725L7.8916 8.08692C8.2168 8.03956 8.49853 7.83497 8.64453 7.53956L12 0.740234L15.356 7.54003C15.5015 7.83495 15.7832 8.03954 16.1089 8.08691L23.6128 9.17725L18.1821 14.4697C17.9468 14.6992 17.8389 15.0303 17.895 15.355L19.1768 22.8281L19.1768 22.8281ZM12 17.1851C12.4795 17.1851 12.959 17.2998 13.396 17.5293L16.5205 19.1719L15.9233 15.6929C15.7568 14.7197 16.0791 13.7271 16.7861 13.0376L19.314 10.5737L15.8213 10.0664C14.8437 9.92432 13.9995 9.31055 13.5625 8.4253L12 5.25977L10.438 8.42481C10.0005 9.31055 9.15624 9.92432 8.17919 10.0664L4.68603 10.5737L7.21337 13.0371C7.92089 13.7271 8.24316 14.7197 8.07665 15.6929L7.47948 19.1719L10.604 17.5293C11.041 17.2998 11.5205 17.1851 12 17.1851H12Z" fill="currentColor"/></symbol>
<symbol id="i-close" viewBox="0 0 24 24"><path d="M15.5521 20L7.46667 12L15.5521 4L16.8 5.44589L10.1762 12L16.8 18.5541L15.5521 20Z" fill="currentColor"/></symbol>
<symbol id="i-filter" viewBox="0 0 24 24"><path d="M12.858 6C12.411 4.27954 10.8587 3 9 3C7.1413 3 5.58905 4.27954 5.14197 6H2V8H5.14197C5.58905 9.72046 7.1413 11 9 11C10.8587 11 12.411 9.72046 12.858 8H22V6H12.858ZM9 9C7.89746 9 7 8.10254 7 7C7 5.89746 7.89746 5 9 5C10.1025 5 11 5.89746 11 7C11 8.10254 10.1025 9 9 9ZM15 13C13.1413 13 11.589 14.2795 11.142 16H2V18H11.142C11.589 19.7205 13.1413 21 15 21C16.8587 21 18.4109 19.7205 18.858 18H22V16H18.858C18.4109 14.2795 16.8587 13 15 13ZM15 19C13.8975 19 13 18.1025 13 17C13 15.8975 13.8975 15 15 15C16.1025 15 17 15.8975 17 17C17 18.1025 16.1025 19 15 19Z" fill="currentColor"/></symbol>
<symbol id="i-down" viewBox="0 0 24 24"><path d="M4 9.24795L12 17.3334L20 9.24795L18.5541 8.00004L12 14.6239L5.44589 8.00004L4 9.24795Z" fill="currentColor"/></symbol>
<symbol id="s-supported" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m4.9 8.2 2.1 2.1 4.2-4.5" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="s-inferred" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 1.8a6.2 6.2 0 0 0 0 12.4z" fill="currentColor"/></symbol>
<symbol id="s-conflict" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="currentColor"/><path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="s-unknown" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.3 1.9"/><path d="M6.5 6.4a1.6 1.6 0 1 1 2.3 1.5c-.5.25-.8.6-.8 1.1v.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="11.3" r=".85" fill="currentColor"/></symbol>
</svg>`;

  const qsvgHTML = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;  // qi-styled icon: no class, the module CSS sizes it
  const LEGEND = `<div class="legend result-legend" role="note" aria-label="What the labels mean">
    <span class="lg-title">Every line is</span>
    <span title="A listing, document or public table backs it">${chip('supported')}</span>
    <span title="Likely, but nothing confirms it yet">${chip('inferred')}</span>
    <span title="The evidence goes against what you need">${chip('conflict')}</span>
    <span title="Nothing we have covers it yet">${chip('unknown')}</span>
    <span class="confirm" title="A must-have that is still unknown: ask the agent before you apply">To confirm</span>
  </div>`;
  const SKELETON = `
<header class="topbar">
  <a class="brand" href="#home" aria-label="HomeTruth">${icon('logo', 'logo')}<span>HomeTruth</span></a>
  <nav class="nav-pill" aria-label="Main navigation"><a href="#home" class="nav-find active">Find a place</a><a href="#explore" class="nav-explore">Explore</a><button type="button" id="saved-open" class="saved-button">Saved <span id="saved-count">0</span></button></nav>
  <div class="topbar-right"><span class="metrics" id="metrics"></span><div class="topbar-extra" id="topbar-extra-slot"></div></div>
</header>
<main>
<section class="hero" id="home" aria-label="Find a place through conversation">
  <div class="orbit" id="orbit" aria-hidden="true"></div>
  <div class="hero-halo" aria-hidden="true"></div>
  <div class="hero-content" id="hero-content">
    <h1 id="hero-title">${TITLE_HOME}</h1>
    <p class="hero-lede" id="hero-lede">Rent, rooms, commute, move-in date, pets: each checked against the listing, floor plan, the agent’s replies and public data, with the evidence shown and a next step for anything still open.</p>
    <div class="ht-sources-slot" id="sources-stage"></div>
  </div>
  <div class="result-stage" id="result-stage" hidden aria-label="Your shortlist">
    <div class="result-top">
      <div class="result-top-left"><h2 id="result-title">Your shortlist.</h2><div id="needs-results" class="criteria-bar needs"></div></div>
      <div class="result-top-right">
        <div id="sources-results"></div>
        <details class="ht-changes" id="changes-box" hidden><summary><b id="changes-count">0</b> changed</summary><ul id="changes"></ul></details>
      </div>
      ${LEGEND}
    </div>
    <div class="result-layout"><div id="result-main-slot"></div><div class="result-side" id="result-side"></div></div>
  </div>
  <div class="conversation-dock" id="conversation-dock"></div>
  <button type="button" id="motion-toggle" class="motion-toggle" aria-pressed="false">Pause motion</button><div class="hero-bottom"><a href="#explore" aria-label="Browse every place">${qsvgHTML('down')}</a></div>
</section>
<section class="explore" id="explore" aria-labelledby="explore-title">
  <div class="collection-top"><span id="collection-count"></span></div>
  <div class="section-heading"><h2 id="explore-title">Every place I can check.</h2><div class="collection-controls" id="collection-controls"></div></div>
  <div id="property-grid" class="property-grid"></div>
  <div id="empty-grid" class="empty-grid" hidden>No places in this group yet.</div>
  <div class="collection-bottom"><a href="#home">Refine with a conversation ${qsvgHTML('arrow')}</a></div>
</section>
</main>
<footer><a href="#home" class="brand">HomeTruth</a><button type="button" id="about-open">About this prototype</button></footer>
<dialog id="filters-dialog" class="side-dialog rental-filter-dialog" aria-labelledby="filter-title"><form id="filters-form"></form></dialog>
<dialog id="saved-dialog" class="side-dialog" aria-labelledby="saved-title"><div class="dialog-header"><h2 id="saved-title">Saved places.</h2><button type="button" class="icon-button" data-close aria-label="Close saved places">${qsvgHTML('close')}</button></div><div id="saved-list"></div></dialog>
<dialog id="detail-dialog" class="detail-dialog" aria-label="Place details"></dialog>
<dialog id="about-dialog" class="about-dialog" aria-labelledby="about-title"><button type="button" class="icon-button" data-close aria-label="Close">${qsvgHTML('close')}</button><h2 id="about-title">A prototype.</h2><p>Five synthetic listings on fictional streets, plus nine real Sydney rentals sampled from Domain on 26 Oct 2026 (their photos belong to the listing agencies). Every line on a card says where its evidence comes from (table and row); synthetic lines carry a mock label until the Zetaris tables are live. Real listings bring only real facts: the listing text, photos and floor plans read by Nemotron VL, sun geometry, Domain's suburb medians.</p><p>Photos on the synthetic listings are illustrative design photography via <a href="https://resident.co.nz/" target="_blank" rel="noreferrer">Resident</a>. Page frame from the qi.home study; typography from <a href="https://www.domain.com.au/" target="_blank" rel="noreferrer">Domain</a>.</p></dialog>
<div hidden><div class="ht-sources-wrap" id="sources-wrap"><span class="ht-sources-lbl">Sources <b id="sources-count"></b></span><ul class="ht-sources" id="sources"></ul></div></div>
<div id="toast" class="toast" role="status"></div>`;

  function create() {
    document.body.insertAdjacentHTML('afterbegin', SPRITE);
    const app = $('#app'); app.innerHTML = SKELETON;
    const dock = $('#dock'); $('#conversation-dock').appendChild(dock);
    const extra = $('#topbar-extra'); if (extra) $('#topbar-extra-slot').appendChild(extra);
    const el = {
      app, dock, hero: $('#home'), heroContent: $('#hero-content'), heroTitle: $('#hero-title'), heroLede: $('#hero-lede'),
      sourcesStage: $('#sources-stage'), sourcesResults: $('#sources-results'), sourcesWrap: $('#sources-wrap'), sources: $('#sources'), sourcesCount: $('#sources-count'),
      stage: $('#result-stage'), resultTitle: $('#result-title'), mainSlot: $('#result-main-slot'), side: $('#result-side'),
      changesBox: $('#changes-box'), changes: $('#changes'), changesCount: $('#changes-count'),
      conversation: $('#conversation'), voice: $('#voice'), orbHost: $('#voice-orb-host'),
      phase: $('#phase'), caption: $('#caption'), transcript: $('#transcript'), text: $('#text'), note: $('#note'), metrics: $('#metrics'),
      meterBar: $('#meter i'), meterThr: $('#meter b'), criteria: $('#search-criteria'), needsResults: $('#needs-results'), suggestions: $('#suggestions'), toast: $('#toast'),
      grid: $('#property-grid'), emptyGrid: $('#empty-grid'), collectionCount: $('#collection-count'), collectionControls: $('#collection-controls'),
      savedCount: $('#saved-count'), savedList: $('#saved-list'), savedDialog: $('#saved-dialog'), filtersDialog: $('#filters-dialog'), filtersForm: $('#filters-form'),
      filtersOpen: $('#filters-open'), detailDialog: $('#detail-dialog'), aboutDialog: $('#about-dialog'),
    };

    /* ---------------- the orbit behind the hero: every candidate listing, with an illustrative photo ---------------- */
    let listings = []; const photoOf = new Map();
    const photoFor = (id) => photoOf.get(id) || PHOTOS[[...String(id)].reduce((a, c) => a + c.charCodeAt(0), 0) % PHOTOS.length];
    const homesList = []; const homesById = new Map();  // qi-style "home" objects: the grid, the detail page, the filters and the comparison read these
    fetch('/api/listings', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => {
      listings = ((d && d.listings) || []).filter((L) => L && L.id);
      listings.forEach((L, i) => photoOf.set(L.id, L.image || PHOTOS[i % PHOTOS.length]));
      listings.forEach((L) => { const h = homeFor(L); homesList.push(h); homesById.set(h.id, h); filterViews.push(filterView(h, Array.isArray(L.facts) ? L.facts : [])); });
      if (listings.length) setupOrbit(listings.map((L) => ({ id: L.id, image: photoFor(L.id), area: L.suburb || splitTitle(L)[1] || '', price: L.rent })));
      buildCollections(); renderGrid(); collectionMotion = setupCollectionMotion(el.grid); mountFilters(); updateSaved();
    }).catch(() => { mountFilters(); });
    // the two coherent photo sets qi.home ships (assets/gallery/source-manifest.json), keyed by the lead photo they share; captions are qi's
    const GALLERY = {
      'room-1.jpg': [['room-1.jpg', 'Timber living room and window seat'], ['gallery/home-1-02.jpg', 'Lounge and fireplace'], ['gallery/home-1-03.jpg', 'Coastal window seat'], ['gallery/home-1-04.jpg', 'Living room, wide view']],
      'room-2.jpg': [['room-2.jpg', 'Kitchen and dining'], ['gallery/home-2-01.jpg', 'Open-plan living'], ['gallery/home-2-02.jpg', 'Kitchen island'], ['gallery/home-2-03.jpg', 'Covered deck'], ['gallery/home-2-04.jpg', 'Glazed entrance'], ['gallery/home-2-05.jpg', 'Exterior and landscape']],
      'room-6.jpg': [['room-6.jpg', 'Coastal window seat'], ['gallery/home-1-04.jpg', 'Living room, wide view'], ['gallery/home-1-02.jpg', 'Lounge and fireplace'], ['gallery/home-1-01.jpg', 'Timber living room and window seat']],
    };
    function homeFor(L) {  // what the detail page, the filters and the comparison need, from /api/listings (no cells: those come with the search)
      const [addr, sub] = splitTitle(L); const suburb = sub || L.suburb || '';
      const image = photoFor(L.id); const file = L.photo_set || image.slice(image.lastIndexOf('/') + 1);  // photo_set: the gallery set that goes with the photo the model read
      const facts = Array.isArray(L.facts) ? L.facts : [];
      const lines = [], groups = [];
      facts.forEach((f) => {
        const ev = (f.evidence || []).filter((e) => e.text && e.text !== 'Not asked yet'); if (!ev.length) return;
        const items = ev.map((e) => ({ text: plainLine(e.text, e), source: sourceName(e), table: e.table, row: e.row, stage: stageOf(e), read_by: e.read_by ? modelName(e.read_by) : null, image: e.image || null }));
        items.forEach((it) => lines.push({ label: f.label + (it.read_by ? ' · read by ' + it.read_by : ''), text: it.text, table: it.table, row: it.row }));
        // value / short / next come straight from /api/listings (policy.listing_summary): next = {kind, text, hint} for anything not supported, else null
        groups.push({ dim: f.dim, label: f.label, key: f.status || '', status: f.status ? (STATUS[f.status] || f.status) : null, value: f.value != null ? f.value : null, short: f.short != null ? f.short : null, next: f.next || null, items });
      });
      const allText = lines.map((l) => l.text).join(' ');
      const bond = /bond\s+(\d+)\s*weeks?/i.exec(allText); const cars = /(\d+)\s*cars?\b/i.exec(allText);
      const statusOf = (dim) => { const f = facts.find((x) => x.dim === dim); return f && f.status ? STATUS[f.status] || f.status : null; };
      const factRows = [['Available', fmtDate(L.available_from) || 'On request'], ['Bond', bond ? `${bond[1]} weeks' rent ($${(Number(bond[1]) * Number(L.rent)).toLocaleString('en-AU')})` : 'Ask the agent']];
      [['J1', 'Pets'], ['C1', 'Bedroom air con'], ['A6', 'Bills'], ['H1', 'Crime disclosure']].forEach(([dim, label]) => { const st = statusOf(dim); if (st) factRows.push([label, dim === 'H1' && st === 'Unknown' ? 'Not asked yet' : st]); });
      return { id: L.id, image, title: addr, area: `${suburb}, Sydney`, suburb, addressLine: `${suburb} NSW ${L.postcode || ''}`.trim(), price: L.rent, beds: L.bedrooms, baths: L.bathrooms,
        available: L.available_from || '', postcode: L.postcode || '', type: /^\d+\//.test(addr) ? 'apartment' : undefined, cars: cars ? Number(cars[1]) : null,
        bondText: bond ? `Bond ${bond[1]} weeks' rent` : 'Bond: ask the agent',
        description: Array.isArray(L.description) && L.description.length ? (L.headline ? sentence(String(L.headline).trim().replace(/[.。]?$/, '.')) + ' ' : '') + L.description.join(' ') : L.special ? sentence(String(L.special).trim().replace(/[.。]?$/, '.')) : '',
        tags: [], features: [], nearby: [], facts: factRows, sourceLines: lines, sourceGroups: groups,
        source: L.source || null, photoTag: photoTag(L), sun: L.sun || null, floorplan: L.floorplan || null,  // real listings: where it came from, the sun geometry, the floor plan
        gallery: Array.isArray(L.images) && L.images.length
          ? [...L.images.map((im) => [im.url, im.caption || 'Photo']), ...(L.floorplan && L.floorplan.url ? [[L.floorplan.url, 'Floor plan']] : [])]  // the real listing's own photos, lead first
          : (GALLERY[file] || [[file, addr]]).map(([pth, cap], i) => (i === 0 && L.image ? [image, L.photo_caption || cap] : [asset(pth), cap])) };  // the lead photo is the one the model read (stamped when staged)
    }

    /* ---------------- the Orb and the conversation panel (qi.home modules) ---------------- */
    const orb = createAgentsOrb(el.orbHost);
    el.orbHost.addEventListener('agents-orb-error', () => { el.orbHost.dataset.fallback = 'original-image'; });
    let orbState = 'idle';
    const setInput = (v) => { const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el.text, v); el.text.dispatchEvent(new Event('input', { bubbles: true })); };
    const submit = (text) => { setInput(text); const f = $('#composer'); if (f.requestSubmit) f.requestSubmit(); else f.dispatchEvent(new Event('submit', { cancelable: true })); };
    const voiceButton = () => [...el.voice.querySelectorAll('button')].find((b) => !b.hidden && !b.disabled);
    const clickVoice = () => { const b = voiceButton(); if (b) b.click(); };
    const panel = createConversationPanel({
      anchor: el.voice, orbElement: el.orbHost, orbController: orb,
      onSubmit: submit, onVoiceToggle: clickVoice,
      onEnd: () => { const s = $('#stop'); if (s && !s.disabled) s.click(); },
      onTyping: () => {}, onViewHomes: () => {},
      onEditCriteria: () => { el.text.placeholder = 'Say what to change, e.g. “make it under 800”'; el.text.focus(); },
      onRemoveCriteria: () => {},
    });
    function setOrbState(s) {
      if (s !== orbState) { orbState = s; orb.setState(s); el.voice.dataset.mode = s; el.voice.classList.toggle('is-listening', s === 'listening'); }
      panel.setState(s);
    }
    el.voice.addEventListener('click', (e) => { if (!e.target.closest('button')) clickVoice(); });
    el.sourcesWrap.querySelector('.ht-sources-lbl').addEventListener('click', () => el.sourcesWrap.classList.toggle('open'));
    el.suggestions.querySelectorAll('[data-prompt]').forEach((b) => b.addEventListener('click', () => submit(b.dataset.prompt)));
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (panel.isOpen()) panel.focus(); else el.text.focus(); }
    });

    let stage = null, phaseNow = 'idle', phaseLabel = 'Ready', asking = false, searchOpen = false, litKey = null, openEv = null, mainId = null, viewingId = null, joinTurn = false, toastT = 0;
    const cards = new Map();   // listing id → { L, rank, ask: Set(dim), was: Map(dim → old status), flash: Set(dim) | null, moved }
    const evCache = new Map(); // "id|dim" → last evidence event, so a line can be opened again later
    const metaParts = new Map();

    /* ---------------- stages: home (orbit + composer) → talk (asking / checking sources) → results (shortlist) ---------------- */
    function setStage(s) {
      if (stage === s) return;
      stage = s; app.dataset.stage = s;
      if (s !== 'home' && window.scrollY > 80) window.scrollTo({ top: 0, behavior: RM.matches ? 'instant' : 'smooth' });  // the grid below may have been in view
      el.hero.classList.toggle('is-conversing', s !== 'home');
      el.hero.classList.toggle('has-results', s === 'results');
      el.heroContent.inert = s === 'results'; el.heroContent.setAttribute('aria-hidden', String(s === 'results'));
      (s === 'results' ? el.sourcesResults : el.sourcesStage).appendChild(el.sourcesWrap);
      el.stage.hidden = s !== 'results';
      el.suggestions.hidden = s !== 'home';
      el.heroLede.hidden = s !== 'home';
      el.text.placeholder = s === 'results' ? 'Ask about a place, or change what you need…' : PLACEHOLDER;
      if (s === 'home') el.heroTitle.innerHTML = TITLE_HOME;
      heroTitle();
    }
    function heroTitle() {  // what the big line behind the panel says while we talk; hidden once there are results
      if (stage !== 'talk') return;
      const busy = phaseNow === 'thinking' || phaseNow === 'searching';
      el.heroTitle.textContent = phaseNow === 'searching' || searchOpen ? 'Checking the sources.' : asking ? 'Before I search.' : busy ? sentence(phaseLabel) + '.' : phaseNow === 'speaking' ? 'One moment.' : 'Go ahead.';
    }
    function toast(msg) {
      clearTimeout(toastT); el.toast.textContent = msg; el.toast.classList.add('visible');
      toastT = setTimeout(() => el.toast.classList.remove('visible'), 3800);
    }

    /* ---------------- cards: one place out front (the one being discussed), the rest as small cards under it ---------------- */
    function rowsHTML(rec, withNext) {  // withNext: after the status, the next step in small type (the detail page's "checked" section)
      const L = rec.L;
      return (L.cells || []).map((c, i) => {
        const val = c.short != null && !STATUS_WORDS.has(String(c.short)) ? c.short : '';
        const was = rec.was.get(c.dim);
        // under the line's name: "To confirm" (a must-have nobody has confirmed), "was …" after an update, the best question to ask, what to look at when viewing
        const sub = (c.status === 'unknown' && c.hard ? '<span class="confirm">To confirm</span>' : '')
          + (was ? `<span class="was">was ${esc(STATUS[was] || was)}</span>` : '')
          + (rec.ask.has(c.dim) ? `<span class="asknote">${icon('ask')}Best question for the agent</span>` : '')
          + (rec.see && rec.see.has(c.dim) ? `<span class="asknote seenote">${icon('ask')}Worth checking at the viewing</span>` : '');
        const next = withNext && c.next ? `<span class="next" title="What settles this line next">${esc(NEXT_TEXT[c.next] || sentence(String(c.next).replace(/_/g, ' ')))}</span>` : '';
        return `<li class="row ${esc(c.status)}${c.hard ? ' hard' : ''}${evCache.has(L.id + '|' + c.dim) ? ' has-ev' : ''}" data-dim="${esc(c.dim)}" style="--i:${i}">`
          + `<span class="dim">${esc(c.label)}${rowPills(c)}${sub}</span><span class="val">${esc(val)}</span><span class="tags">${chip(c.status)}${next}</span></li>`;
      }).join('');
    }
    function counts(L) {
      const n = { supported: 0, inferred: 0, conflict: 0, unknown: 0 }; let confirm = 0;
      (L.cells || []).forEach((c) => { if (n[c.status] != null) n[c.status]++; if (c.status === 'unknown' && c.hard) confirm++; });
      return { ...n, confirm };
    }
    function summaryHTML(L) {
      const n = counts(L); const parts = [];
      if (n.supported) parts.push(`<b class="t-supported">${n.supported}</b> supported`);
      if (n.inferred) parts.push(`<b class="t-inferred">${n.inferred}</b> inferred`);
      if (n.conflict) parts.push(`<b class="t-conflict">${n.conflict}</b> conflict${n.conflict > 1 ? 's' : ''}`);
      if (n.confirm) parts.push(`<b class="t-unknown">${n.confirm}</b> to confirm`);
      if (n.unknown - n.confirm) parts.push(`<b class="t-unknown">${n.unknown - n.confirm}</b> unknown`);
      return parts.join('<span class="sep">·</span>');
    }
    function miniStatus(L) {
      const n = counts(L); const parts = [];
      if (n.supported) parts.push(`${n.supported} supported`);
      if (n.conflict) parts.push(`${n.conflict} conflict${n.conflict > 1 ? 's' : ''}`);
      if (n.confirm) parts.push(`${n.confirm} to confirm`);
      return parts.join(' · ');
    }
    function mainHTML(rec) {
      const L = rec.L; const [addr, sub] = splitTitle(L);
      const mv = rec.moved && rec.moved.until > Date.now() ? rec.moved : null;
      const isSaved = saved.has(L.id); const cmp = homeCompare.isSelected(L.id);
      return `<div class="result-photo-wrap"><button type="button" class="result-photo-button" aria-label="View ${esc(addr)}"><img class="result-image" src="${esc(photoFor(L.id))}" alt="${esc(photoTag(L))}"></button>`
        + `<span class="rank">#${esc(rec.rank)}</span><span class="now">${viewingId === L.id ? 'Viewing' : 'Now discussing'}</span><span class="ht-photo-tag${L.source ? ' real' : ''}">${esc(photoTag(L))}</span>`
        + `<button type="button" class="save-home${isSaved ? ' is-saved' : ''}" data-save-id="${esc(L.id)}" aria-pressed="${isSaved}" aria-label="${isSaved ? 'Remove' : 'Save'} ${esc(addr)}">${qsvgHTML('heart')}</button></div>`
        + `<div class="result-info"><div class="result-title-row"><div class="ht-title"><div class="suburb">${esc(sub)}</div><h3 class="addr">${esc(addr)}</h3></div>`
        + `<p class="result-price"><b>$${esc(L.rent)}</b><span>per week</span></p></div>`
        + `<div class="result-meta specs-row"><span>${icon('q-bed', 'qico')}${esc(bedText(L.bedrooms))}</span>${L.bathrooms != null ? `<span>${icon('q-bath', 'qico')}${esc(L.bathrooms)} bath</span>` : ''}<span>${icon('cal')}${L.available_from ? `Available ${esc(fmtDate(L.available_from))}` : 'Move-in date not given'}</span></div>`
        + `<ul class="result-reasons rows">${rowsHTML(rec)}</ul>`
        + `<div class="result-actions"><span class="ht-summary">${summaryHTML(L)}</span><span class="moved${mv ? ' ' + mv.dir : ''}">${mv ? esc(mv.text) : ''}</span>`
        + `<span class="ht-actions"><button type="button" class="result-compare" data-compare-id="${esc(L.id)}" aria-pressed="${cmp}">${cmp ? 'Selected for compare' : 'Compare'}</button>`
        + `<button type="button" class="result-detail-button">View place ${qsvgHTML('arrow')}</button></span></div></div>`;
    }
    const byRank = () => [...cards.values()].sort((a, b) => a.rank - b.rank);
    const mainEl = () => el.mainSlot.querySelector('.result-main');
    function renderMain(rec, flashDims) {
      const main = mainEl(); if (!main || main.dataset.id !== rec.L.id) return;
      main.innerHTML = mainHTML(rec);
      (flashDims || []).forEach((dim) => { const row = main.querySelector(`.row[data-dim="${cssEsc(dim)}"]`); if (row) row.classList.add('changed'); });
      litRow();
    }
    function renderSide() {
      const others = byRank().filter((r) => r.L.id !== mainId);
      el.side.innerHTML = others.map((r) => {
        const [addr, sub] = splitTitle(r.L);
        return `<button type="button" class="result-mini fgcard" data-id="${esc(r.L.id)}" title="Look at ${esc(addr)}, ${esc(sub)}">`
          + `<img class="result-mini-image" src="${esc(photoFor(r.L.id))}" alt=""><span class="result-mini-copy">`
          + `<span class="result-mini-title"><b class="rank">#${esc(r.rank)}</b>${esc(addr)}</span>`
          + `<span class="result-mini-price">$${esc(r.L.rent)} /wk<span class="ht-mini-status">${esc(miniStatus(r.L))}</span></span></span></button>`;
      }).join('');
    }
    el.side.addEventListener('click', (e) => { const b = e.target.closest('.result-mini'); if (b && cards.has(b.dataset.id)) showMain(b.dataset.id, { local: true }); });
    // put one place out front: the first time its photo flies up from the orbit; afterwards a quiet change of subject
    async function showMain(id, opts = {}) {
      const rec = cards.get(id); if (!rec) return;
      const first = stage !== 'results';
      el.stage.classList.remove('refreshing');
      if (mainId === id && !first) { viewingId = opts.local ? id : null; renderMain(rec); renderSide(); return; }
      const animate = opts.animate !== false && !RM.matches;
      if (animate && !first) prepareResultTransition(id);  // before the DOM changes: it captures the photo on its way out
      mainId = id; viewingId = opts.local ? id : null;
      const main = document.createElement('article'); main.className = 'result-main fgcard active'; main.dataset.id = id; main.dataset.homeId = id;
      el.mainSlot.replaceChildren(main);
      renderMain(rec); renderSide();
      if (first) { setStage('results'); panel.minimize({ restore: false }); if (animate) prepareResultTransition(id); }
      panel.setResults(cards.size); panel.setContext({ area: splitTitle(rec.L)[0] });
      if (animate) { try { await liftToResult(id, main.querySelector('.result-image'), { fast: !first }); } catch (e) { /* the card is usable without the flight */ } }
    }
    function litRow() {  // the line being discussed: lit, with its evidence open under it
      const main = mainEl(); if (!main) return;
      main.querySelectorAll('.row.lit, .row.viewing').forEach((r) => r.classList.remove('lit', 'viewing'));
      closeEvidence();
      if (!litKey || litKey.split('|')[0] !== main.dataset.id) return;
      const row = main.querySelector(`.row[data-dim="${cssEsc(litKey.split('|')[1])}"]`); if (!row) return;
      row.classList.add('lit');
      const ev = evCache.get(litKey); if (ev) openEvidence(ev, false);
    }
    function evidenceHTML(ev) {
      const items = ev.items || [];
      return items.length ? items.map((it, i) => `<li style="--i:${i}">`
        + `<div class="ev-src"><span>Table <b>${esc(it.table)}</b></span><span>Row <b>${esc(it.row)}</b></span>${it.material_id && it.material_id !== it.row ? `<span>Material <b>${esc(it.material_id)}</b></span>` : ''}`
        + `${it.read_by ? `<span class="ev-model" title="${esc(it.read_by)}">Read by <b>${esc(modelName(it.read_by))}</b></span>` : ''}</div>`
        + `${it.image ? `<a class="ev-photo" href="${esc(it.image)}" target="_blank" rel="noopener" title="The photo the model read"><img src="${esc(it.image)}" alt="The listing photo the model read"></a>` : ''}`
        + `<blockquote>${esc(it.text)}</blockquote>`
        + `<div class="ev-id">request_id <code>${esc(it.request_id)}</code>${it.mock ? '<span class="mock">mock</span>' : ''}</div></li>`).join('')
        : '<li class="ev-none">No rows for this line yet.</li>';
    }
    function openEvidence(ev, viewing) {
      closeEvidence();
      const main = mainEl(); if (!main || ev.listing_id !== main.dataset.id) return;
      const row = main.querySelector(`.row[data-dim="${cssEsc(ev.dim)}"]`); if (!row) return;
      const li = document.createElement('li'); li.className = 'ht-ev-row';
      li.innerHTML = `<div class="ev-where">${chip(ev.status)}<span>${esc(ev.label)}</span></div><ul class="ht-ev" id="evidence">${evidenceHTML(ev)}</ul>`;
      row.after(li); openEv = ev.listing_id + '|' + ev.dim;
      if (viewing) row.classList.add('viewing');
    }
    function closeEvidence() { const e = document.getElementById('evidence'); if (e) e.closest('.ht-ev-row').remove(); openEv = null; }
    el.mainSlot.addEventListener('click', (e) => {  // click a line that has been discussed to see its evidence again (click again to fold it)
      const row = e.target.closest('.row.has-ev'); if (!row) return;
      const key = row.closest('.result-main').dataset.id + '|' + row.dataset.dim; const ev = evCache.get(key); if (!ev) return;
      if (openEv === key && !row.classList.contains('lit')) { closeEvidence(); row.classList.remove('viewing'); return; }
      mainEl().querySelectorAll('.row.viewing').forEach((r) => r.classList.remove('viewing'));
      openEvidence(ev, !row.classList.contains('lit'));
    });
    function showMoved(rec, from, to) {
      rec.moved = { text: to < from ? `Moved up to #${to}` : `Moved down to #${to}`, dir: to < from ? 'up' : 'down', until: Date.now() + 6000 };
      if (rec.L.id === mainId) { const m = mainEl().querySelector('.moved'); if (m) { m.textContent = rec.moved.text; m.className = 'moved ' + rec.moved.dir; } }
      clearTimeout(rec.movedT); rec.movedT = setTimeout(() => { if (rec.L.id === mainId) { const n = mainEl() && mainEl().querySelector('.moved'); if (n) { n.textContent = ''; n.className = 'moved'; } } }, 6000);
    }
    function rankBadges() {
      const m = mainEl(); const rec = m && cards.get(m.dataset.id); if (rec) { const b = m.querySelector('.rank'); if (b) b.textContent = '#' + rec.rank; }
      renderSide();
    }
    function resetShortlist() { cards.clear(); mainId = null; viewingId = null; litKey = null; evCache.clear(); closeEvidence(); app.classList.remove('touring'); }
    function newSearch() {
      searchOpen = true;
      el.sources.innerHTML = ''; el.sourcesCount.textContent = ''; el.sourcesWrap.classList.remove('is-mock');
      evCache.clear(); closeEvidence(); litKey = null; cards.clear();  // the old shortlist stays on screen, dimmed, until the first new card replaces it
      if (stage === 'results') el.stage.classList.add('refreshing');
      else { setStage('talk'); if (!RM.matches) prepareSearch(); }
    }
    function meta(key, value) {  // each part stays on one line; a long line wraps between parts, never inside one
      metaParts.set(key, value || '');
      if (!el.metrics) return;
      const rest = ['parser', 'latency'].map((k) => metaParts.get(k)).filter(Boolean).map((v) => `<span>${esc(v)}</span>`).join('<i>·</i>');
      el.metrics.innerHTML = (metaParts.get('voice') ? `<span class="m-line">${esc(metaParts.get('voice'))}</span>` : '') + (rest ? `<span class="m-line">${rest}</span>` : '');
    }
    function sourcesCount() {  // the server sends sources one by one with no total, so while the search runs only the done count is known
      const n = el.sources.querySelectorAll('li:not(.ht-stage)').length, done = el.sources.querySelectorAll('li.done:not(.ht-stage)').length;  // the stage headings are not sources
      el.sourcesCount.textContent = !n ? '' : searchOpen ? `${done} checked so far` : `${done} of ${n} checked`;
    }
    function stageHeadings() {  // the five group headings, in order, once per search (newSearch / clear empty the list, so they come back with the first source)
      if (el.sources.querySelector('li.ht-stage')) return;
      STAGES.forEach(([key, label]) => {
        const h = document.createElement('li'); h.className = 'ht-stage' + (STAGE_EMPTY[key] ? ' empty' : ''); h.dataset.stage = key;
        h.innerHTML = `<b>${esc(label)}</b>${STAGE_EMPTY[key] ? `<span> — ${esc(STAGE_EMPTY[key])}</span>` : ''}`;
        el.sources.appendChild(h);
      });
    }

    /* ---------------- below the hero: qi.home's browsing grid, saved list, comparison, detail page and filters, on our data ---------------- */
    const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
    const btn = (cls, text, action) => { const b = mk('button', cls, text); b.type = 'button'; if (action) b.addEventListener('click', action); return b; };
    const qsvg = (name) => { const sv = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); sv.setAttribute('aria-hidden', 'true'); const u = document.createElementNS('http://www.w3.org/2000/svg', 'use'); u.setAttribute('href', '#i-' + name); sv.append(u); return sv; };
    const imgEl = (home, cls, eager) => { const i = mk('img', cls); i.src = home.image; i.alt = home.photoTag || 'Illustrative photo'; i.loading = eager ? 'eager' : 'lazy'; i.decoding = 'async'; return i; };
    const money = (n) => '$' + Number(n).toLocaleString('en-AU');
    // saved places: this browser only (localStorage), like qi's shortlist
    let saved = new Set(); try { saved = new Set(JSON.parse(localStorage.getItem('hometruth-shortlist') || '[]')); } catch (e) { saved = new Set(); }
    function saveButton(home) {
      const b = btn('save-home' + (saved.has(home.id) ? ' is-saved' : ''), '', (e) => { e.stopPropagation(); toggleSave(home.id); });
      b.dataset.saveId = home.id; b.setAttribute('aria-pressed', String(saved.has(home.id))); b.setAttribute('aria-label', (saved.has(home.id) ? 'Remove ' : 'Save ') + home.title); b.append(qsvg('heart')); return b;
    }
    function toggleSave(id) {
      if (saved.has(id)) saved.delete(id); else saved.add(id);
      try { localStorage.setItem('hometruth-shortlist', JSON.stringify([...saved])); } catch (e) { /* private browsing */ }
      updateSaved(); propertyDetail.refreshSaved();
      if (!RM.matches) document.querySelectorAll(`[data-save-id="${cssEsc(id)}"]`).forEach((n) => n.animate([{ transform: 'scale(.88)' }, { transform: 'scale(1.06)' }, { transform: 'scale(1)' }], { duration: 320, easing: 'ease-out' }));
      toast(saved.has(id) ? 'Saved' : 'Removed');
    }
    function updateSaved() {
      el.savedCount.textContent = String(saved.size);
      document.querySelectorAll('[data-save-id]').forEach((n) => { const home = homesById.get(n.dataset.saveId); if (!home) return; const on = saved.has(home.id); n.classList.toggle('is-saved', on); n.setAttribute('aria-pressed', String(on)); n.setAttribute('aria-label', (on ? 'Remove ' : 'Save ') + home.title); });
      el.savedList.replaceChildren();
      if (!saved.size) { const empty = mk('div', 'saved-empty'); empty.append(qsvg('heart'), mk('h3', '', 'Your shortlist starts here.'), mk('p', '', 'Save a place from its card or its details.')); el.savedList.append(empty); return; }
      [...saved].forEach((id) => {
        const home = homesById.get(id); if (!home) return;
        const row = mk('article', 'saved-row'); const open = btn('saved-row-open', '', () => { el.savedDialog.close(); openDetail(home); });
        const copy = mk('span', 'saved-row-copy'); copy.append(mk('strong', '', home.title), mk('span', '', home.suburb), mk('span', '', money(home.price) + '/wk'));
        open.append(imgEl(home, 'saved-row-image'), copy);
        const remove = btn('icon-button', '', () => toggleSave(home.id)); remove.setAttribute('aria-label', 'Remove ' + home.title); remove.append(qsvg('close'));
        row.append(open, remove); el.savedList.append(row);
      });
    }
    // two places side by side (qi's table: rent, bedrooms, bathrooms, floor area = not listed, availability); "Ask about both" drafts the question for the conversation
    const homeCompare = createHomeCompare({
      homes: () => homesList, getCriteria: () => ({}), notify: toast, onSelectionChange: syncCompareButtons, onOpen: () => panel.suspend(),
      onOpenHome: (id) => openDetail(homesById.get(id)),
      onAsk: (pair) => { if (pair.length < 2) return; panel.open({ view: 'chat', focus: true }); panel.setDraft(`Compare ${pair[0].title} and ${pair[1].title}: which one fits what I need better?`); },
    });
    function compareButton(home, cls) { const b = btn(cls, homeCompare.isSelected(home.id) ? 'Selected for compare' : 'Compare', () => homeCompare.toggle(home.id)); b.dataset.compareId = home.id; b.setAttribute('aria-pressed', String(!!homeCompare.isSelected(home.id))); return b; }
    function syncCompareButtons() { document.querySelectorAll('[data-compare-id]').forEach((b) => { const on = homeCompare.isSelected(b.dataset.compareId); b.setAttribute('aria-pressed', String(!!on)); b.textContent = on ? 'Selected for compare' : 'Compare'; }); }
    // the detail page (qi's, modelled on Domain / realestate.com.au): photos, rent, specs, availability, what the sources say, viewing plan, area
    const propertyDetail = createPropertyDetail({
      dialog: el.detailDialog, homes: homesList, isSaved: (id) => saved.has(id), toggleSave, notify: toast, onOpen: () => panel.suspend(),
      onAsk: async (home, question) => {  // "Ask about this home": into the real conversation, with the place named so the server knows which one
        const text = String(question || '').replace(/this home/i, home.title).replace(/the area/i, 'the area around ' + home.title);
        if (cards.has(home.id)) submit(text);                                   // in the shortlist: the server answers from the evidence matrix
        else { panel.open({ view: 'chat', focus: true }); panel.setDraft(text); }   // not checked yet: the question waits in the box until the needs are known
      },
    });
    function openDetail(home, trigger) {
      if (!home) return;
      panel.suspend();
      const main = mainEl();
      const origin = trigger || (main && main.dataset.id === home.id ? main.querySelector('.result-photo-button') : null) || document.querySelector(`.property-card[data-home-id="${cssEsc(home.id)}"] .property-image-button`);
      propertyDetail.open(home, origin || undefined);
      addCheckSection(home);
    }
    function addCheckSection(home) {  // ours, between qi's overview and "what the sources say": the lines checked for this renter, evidence under them
      const overview = el.detailDialog.querySelector('#listing-overview'); if (!overview) return;
      const rec = cards.get(home.id); const sec = mk('section', 'listing-section listing-check'); sec.id = 'listing-check';
      if (rec) {
        sec.innerHTML = `<h2>Checked against what you need.</h2><ul class="rows listing-rows">${rowsHTML(rec, true)}</ul><p class="listing-micro ht-summary">${summaryHTML(rec.L)}</p>`;
        sec.querySelector('.listing-rows').addEventListener('click', (e) => {
          const row = e.target.closest('.row.has-ev'); if (!row) return;
          const next = row.nextElementSibling; if (next && next.classList.contains('ht-ev-row')) { next.remove(); row.classList.remove('viewing'); return; }
          const ev = evCache.get(home.id + '|' + row.dataset.dim); if (!ev) return;
          const li = mk('li', 'ht-ev-row'); li.innerHTML = `<div class="ev-where">${chip(ev.status)}<span>${esc(ev.label)}</span></div><ul class="ht-ev">${evidenceHTML(ev)}</ul>`;
          row.after(li); row.classList.add('viewing');
        });
      } else sec.innerHTML = '<p class="listing-micro ht-notyet">Not checked for you yet. Say what you need and each line gets a status, its evidence and a next step.</p>';  // 10-27: one line, not a paragraph (the detail page is kept to numbers and statuses)
      overview.after(sec);
    }
    // the browsing grid (qi's Shopify-style collection): every candidate place, grouped by suburb
    let collection = 'all'; let collectionMotion = null;
    function buildCollections() {
      const counts = new Map(); homesList.forEach((h) => counts.set(h.suburb, (counts.get(h.suburb) || 0) + 1));
      const groups = [['all', 'All']].concat([...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 4).map(([sub]) => [sub, sub]));
      el.collectionControls.replaceChildren(...groups.map(([key, label]) => { const b = btn(key === collection ? 'active' : '', label, () => { collection = key; renderGrid(); }); b.dataset.collection = key; b.setAttribute('aria-pressed', String(key === collection)); return b; }));
    }
    function specNode(home, cls) {
      const row = mk('div', cls + ' specs-row');
      [['bed', bedText(home.beds)], ['bath', `${home.baths} bath`]].forEach(([name, text]) => { const sp = mk('span'); sp.append(qsvg(name), document.createTextNode(text)); row.append(sp); });
      row.append(mk('span', '', `Available ${fmtDate(home.available) || 'on request'}`));
      return row;
    }
    function renderGrid() {
      const visible = homesList.filter((h) => collection === 'all' || h.suburb === collection);
      el.grid.replaceChildren();
      visible.forEach((home, index) => {
        const card = mk('article', 'property-card'); card.dataset.homeId = home.id; card.style.setProperty('--card-index', String(index)); card.style.setProperty('--reveal-delay', `${(index % 3) * 80}ms`);
        const visual = mk('div', 'property-image-wrap');
        const open = btn('property-image-button', '', (e) => openDetail(home, e.currentTarget)); open.setAttribute('aria-label', 'View ' + home.title); open.append(imgEl(home, 'property-image'));
        visual.append(open, saveButton(home));
        const copy = mk('div', 'property-copy'); const titleRow = mk('div', 'property-title-row'); const h3 = mk('h3'); h3.append(btn('property-title-button', home.title, () => openDetail(home)));
        const price = mk('p', 'property-price'); price.append(document.createTextNode(money(home.price)), mk('span', '', ' /wk')); titleRow.append(h3, price);
        copy.append(titleRow, mk('p', 'property-location', home.suburb), specNode(home, 'property-specs'), compareButton(home, 'card-compare'));
        card.append(visual, copy); el.grid.append(card);
      });
      if (collectionMotion) collectionMotion.refresh();
      el.emptyGrid.hidden = visible.length > 0;
      el.collectionCount.textContent = `${visible.length} place${visible.length === 1 ? '' : 's'}`;
      el.collectionControls.querySelectorAll('[data-collection]').forEach((b) => { const on = b.dataset.collection === collection; b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)); });
    }
    // the filters (qi's realestate.com.au-parity panel): applied = read out as one sentence and sent to the server like anything typed
    let appliedFilters = emptyRentalFilters(); let filterPanel = null;
    // what the panel's "Show N homes" preview counts: a place is ruled out only by what the sources say (rent, bedrooms, bathrooms, suburb,
    // availability, a listing that says no pets, the type); anything the matrix has no fact for passes instead of hiding the place
    class Known extends Array { constructor(known) { super(); this.known = known || {}; } includes(x) { return Object.prototype.hasOwnProperty.call(this.known, x) ? this.known[x] : true; } }
    const filterViews = [];
    function filterView(home, facts) {
      const pets = (facts.find((f) => f.dim === 'J1') || {}).status;
      return { ...home, tags: new Known({ pet: pets !== 'conflict' }), features: new Known({}), nearby: [], furnished: true, affordable: true, deposit: false, cars: home.cars == null ? 99 : home.cars };
    }
    const TYPE_WORDS = { house: 'a house', townhouse: 'a townhouse', apartment: 'an apartment', villa: 'a villa' };
    const FEATURE_LABEL = Object.fromEntries(FEATURE_GROUPS.flatMap((g) => g.items));
    function filterSentence(c) {
      const parts = []; const beds = (n) => (n === 0 ? 'a studio' : `${n} bedroom${n === 1 ? '' : 's'}`);
      if (c.bedsMin != null && c.bedsMin === c.bedsMax) parts.push(beds(c.bedsMin));
      else if (c.bedsMin != null && c.bedsMax != null) parts.push(`${c.bedsMin} to ${c.bedsMax} bedrooms`);
      else if (c.bedsMin != null) parts.push(`at least ${beds(c.bedsMin)}`);
      else if (c.bedsMax != null) parts.push(`up to ${c.bedsMax} bedrooms`);
      if (c.priceMin != null && c.priceMax != null) parts.push(`between $${c.priceMin} and $${c.priceMax} a week`);
      else if (c.priceMax != null) parts.push(`under $${c.priceMax} a week`);
      else if (c.priceMin != null) parts.push(`from $${c.priceMin} a week`);
      if (c.location) parts.push(`near ${c.location}`);
      if (c.availableBy === 'now') parts.push('available now'); else if (c.availableBy) parts.push(`moving in before ${fmtDate(c.availableBy) || c.availableBy}`);
      if (c.pet) parts.push('I have a pet');
      if (c.furnished) parts.push('furnished');
      if (c.types.length) parts.push(c.types.map((t) => TYPE_WORDS[t] || t).join(' or '));
      if (c.bathsMin != null) parts.push(`${c.bathsMin}+ bathrooms`);
      if (c.carsMin != null && c.carsMin > 0) parts.push(`${c.carsMin}+ car space${c.carsMin === 1 ? '' : 's'}`);
      if (c.features.length) parts.push(c.features.map((k) => (FEATURE_LABEL[k] || k).toLowerCase()).join(', '));
      if (c.sunny) parts.push('lots of natural light'); if (c.quiet) parts.push('a quiet street');
      if (c.affordable) parts.push('affordable housing only'); if (c.excludeDeposit) parts.push('not already secured by a deposit');
      if (c.keywords) parts.push(c.keywords);
      return parts.length ? sentence(parts.join(', ')) + '.' : '';
    }
    function updateFilterIndicator() { if (!el.filtersOpen) return; const n = activeRentalFilterCount(appliedFilters); el.filtersOpen.dataset.count = n ? String(n) : ''; el.filtersOpen.setAttribute('aria-label', n ? `Open filters, ${n} active` : 'Open filters'); }
    function mountFilters() {
      if (filterPanel || !el.filtersForm) return;
      filterPanel = mountRentalFilters({ form: el.filtersForm, dialog: el.filtersDialog, homes: filterViews, getApplied: () => ({ ...appliedFilters, types: [...appliedFilters.types], features: [...appliedFilters.features] }),
        onApply(c) { appliedFilters = c; updateFilterIndicator(); const text = filterSentence(c); if (text) submit(text); else toast('Pick at least one filter first'); } });
      const seen = new Set(); el.filtersForm.querySelectorAll('#rental-suburbs option').forEach((o) => { if (seen.has(o.value)) o.remove(); else seen.add(o.value); });  // one suggestion per suburb
    }
    if (el.filtersOpen) el.filtersOpen.addEventListener('click', () => { mountFilters(); if (!filterPanel) return; panel.suspend(); filterPanel.open(); });
    // dialogs and toggles (qi's)
    document.querySelectorAll('[data-close]').forEach((n) => n.addEventListener('click', () => n.closest('dialog').close()));
    [el.savedDialog, el.filtersDialog, el.aboutDialog].forEach((d) => d.addEventListener('click', (e) => { if (e.target !== d) return; const r = d.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close(); }));
    $('#saved-open').addEventListener('click', () => { panel.suspend(); updateSaved(); el.savedDialog.showModal(); });
    $('#about-open').addEventListener('click', () => { panel.suspend(); el.aboutDialog.showModal(); });
    const motionToggle = $('#motion-toggle'); if (RM.matches) motionToggle.hidden = true;
    motionToggle.addEventListener('click', () => { const paused = $('#orbit').dataset.paused !== 'true'; $('#orbit').dataset.paused = String(paused); motionToggle.setAttribute('aria-pressed', String(paused)); motionToggle.textContent = paused ? 'Resume motion' : 'Pause motion'; });
    // on the card out front: the photo and "View place" open the detail page; the heart saves; Compare selects
    el.mainSlot.addEventListener('click', (e) => {
      const main = e.target.closest('.result-main'); if (!main) return; const home = homesById.get(main.dataset.id);
      if (e.target.closest('.result-photo-button, .result-detail-button')) { if (home) openDetail(home, e.target.closest('.result-photo-button') || undefined); return; }
      const save = e.target.closest('.save-home'); if (save) { e.stopPropagation(); toggleSave(save.dataset.saveId); return; }
      const cmp = e.target.closest('.result-compare'); if (cmp) homeCompare.toggle(cmp.dataset.compareId);
    });

    const ui = {
      el, meta, example: EXAMPLE,
      stage: () => stage,
      // a server `state` event: what it means happens now (a new search clears the old shortlist, "Ready" ends the tour);
      // showing it can wait (8631 holds the label until the current sentence has been spoken: pass show = false, then phase() later)
      state(ev, show = true) {
        if (ev.phase === 'searching') newSearch();
        else if (searchOpen) { searchOpen = false; sourcesCount(); }
        if (ev.phase === 'idle' && !/paus/i.test(ev.label || '')) app.classList.remove('touring');
        if (show) ui.phase(ev.phase, ev.label);
      },
      phase(p, label) {  // what is shown: the Orb's state, the label in the conversation box, the panel's status line, the big line behind
        phaseNow = p; phaseLabel = label || p; const txt = sentence(phaseLabel);
        app.dataset.phase = p; el.voice.dataset.phase = p;
        if (el.phase.textContent !== txt) el.phase.textContent = txt;
        setOrbState(ORB_STATE[p] || 'idle');
        el.hero.classList.toggle('is-thinking', p === 'thinking' || p === 'searching');
        panel.setStatusText(p === 'searching' ? 'Checking the sources…' : p === 'thinking' ? txt + '…' : '');
        if (p === 'thinking' || p === 'searching') asking = false;
        if (p === 'idle' || p === 'paused') app.classList.remove('touring');
        if (p === 'paused' && searchOpen) { searchOpen = false; sourcesCount(); }
        if (p === 'listening' && /your turn/i.test(txt) && panel.isOpen()) panel.focus();
        heroTitle();
      },
      level(x) { if (orbState === 'listening') orb.setLevel(Math.max(0, Math.min(1, x || 0))); },
      botLevel(x) { if (orbState === 'speaking') orb.setLevel(Math.max(0, Math.min(1, x || 0))); },
      interrupt() {
        el.caption.classList.add('dim');
        el.voice.classList.remove('cut'); void el.voice.offsetWidth; el.voice.classList.add('cut');
      },
      caption(t) {
        el.caption.classList.remove('dim'); el.caption.textContent = t || '';
        el.conversation.hidden = !t && !el.transcript.textContent;
        if (!t) return;
        panel.appendTurn('assistant', t, joinTurn); joinTurn = true;
        if (!RM.matches) el.caption.animate([{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: EASE });
      },
      transcript(t, interim) {
        el.transcript.innerHTML = t ? `<span class="you-l">You</span>${esc(t)}` : '';
        el.transcript.classList.toggle('interim', !!interim);
        if (t || el.caption.textContent) el.conversation.hidden = false;
        if (interim && t) panel.setDraft(t);
      },
      userSaid(t) {
        ui.transcript(t, false); panel.setDraft(''); panel.appendTurn('user', t); joinTurn = false;
        if (stage === 'home') {
          setStage('talk');
          const b = voiceButton(); panel.open({ view: b && b.classList.contains('on') ? 'voice' : 'chat' });
        }
      },
      error(m) {
        el.caption.innerHTML = `<span class="error">${esc(m)}</span>`; el.conversation.hidden = false;
        setOrbState('error'); setTimeout(() => { if (orbState === 'error') ui.phase('idle', 'Error'); }, 1600);
      },
      latency(firstEventMs, firstWordMs) {
        meta('latency', firstEventMs == null && firstWordMs == null ? '' : `First event ${firstEventMs == null ? '–' : firstEventMs + ' ms'} · first word ${firstWordMs == null ? '–' : firstWordMs + ' ms'}`);
      },
      events(n) { if (el.metrics) el.metrics.title = `${n} events this session`; },
      note(t) { if (el.note) el.note.textContent = t || ''; },
      needs(ev) {
        const p = ev.profile || {}; const ask = new Set(ev.asking || []); const assumed = new Set(ev.assumed || []);
        const rem = new Set(ev.remembered || []);  // fields still carried over from last time (memory.py): dashed chip, "last time"
        asking = ask.size > 0;
        const chips = [];
        NEEDS.forEach(([dim, ic, get, askText, assumedText]) => {
          const v = get(p);
          if (v != null) chips.push([rem.has(FIELD_OF[dim]) ? 'set remembered' : 'set', ic, v, dim]);
          else if (ask.has(dim)) chips.push(['asking', ic, askText, dim]);
          else if (assumed.has(dim)) chips.push(['assumed', ic, assumedText, dim]);
        });
        (p.extras || []).forEach((x, i) => chips.push([rem.has('extras') ? 'extra remembered' : 'extra', 'plus', x, 'extra' + i]));
        const html = chips.map(([cls, ic, t], i) => `<span class="criterion-chip need ${cls}" style="--i:${i}"${cls.includes('remembered') ? ' title="From last time"' : ''}>${icon(ic)}<span>${esc(t)}</span></span>`).join('');
        el.criteria.innerHTML = html; el.criteria.hidden = !chips.length;
        el.needsResults.innerHTML = html; el.needsResults.hidden = !chips.length;
        panel.setCriteria(chips.map(([cls, ic, t, dim]) => ({ key: dim, label: t })));
        document.querySelectorAll('.agent-criteria .criterion-chip').forEach((c, i) => { if (chips[i]) c.classList.add('need', ...chips[i][0].split(' ')); });  // 'set remembered' is two classes
        appliedFilters = { ...appliedFilters, priceMax: p.budget != null ? Number(p.budget) : null, bedsMin: p.bedrooms != null ? Number(p.bedrooms) : null, bedsMax: p.bedrooms != null ? Number(p.bedrooms) : null, pet: !!(p.pets && !/^no\b/i.test(p.pets)) };  // the anchor is a commute, not a suburb box
        updateFilterIndicator();
        if (ev.parser) meta('parser', ev.parser === 'llm' ? `Needs read by Nemotron${ev.parse && ev.parse.provider ? ' via ' + sentence(ev.parse.provider) : ''}` : 'Needs read by rules');
        if (stage === 'home' && !ev.quiet) setStage('talk');
        heroTitle();
      },
      // a returning renter (GET /api/hello?renter=…): their last needs as chips, a line under the title, two buttons, and a way to be forgotten
      remembered(mem, actions) {
        if (!mem || !mem.profile) return;
        ui.needs({ profile: mem.profile, remembered: mem.remembered || [], quiet: true });
        let box = document.getElementById('welcome-back');
        if (!box) { box = document.createElement('div'); box.id = 'welcome-back'; box.className = 'suggestions welcome-back'; el.heroLede.insertAdjacentElement('afterend', box); }
        // Dot-style state (10-26): replies that arrived while they were away (inbox.py), what they were still waiting on (memory.py open loops), belief versions (beliefs.py)
        const away = mem.away && mem.away.unread ? mem.away : null;
        const open = (mem.open || []).filter((o) => o.street).slice(0, 2);
        const flips = mem.beliefs && mem.beliefs.flips ? mem.beliefs : null;
        const extra = [];
        if (away) extra.push(`<span><b>While you were away:</b> ${away.unread} agent repl${away.unread === 1 ? 'y' : 'ies'} · ${esc([...new Set(away.items.map((it) => it.street || it.listing_id))].join(', '))}</span>`);
        if (open.length) extra.push(`<span><b>Still open:</b> ${esc(open.map((o) => `${String(o.label || o.dim).toLowerCase()} at ${o.street}`).join(' · '))}</span>`);
        if (flips) { const r = flips.recent && flips.recent[0]; extra.push(`<span><b>On file:</b> ${flips.flips} belief flip${flips.flips === 1 ? '' : 's'}${r ? ` · latest ${esc(String(r.label || r.dim).toLowerCase())} at ${esc(r.street || r.listing_id)} v${esc(r.from_version)} → v${esc(r.version)}` : ''}</span>`); }
        box.innerHTML = `<p><b>Welcome back.</b> Last time${mem.ago ? ` <span class="wb-ago">(${esc(mem.ago)})</span>` : ''} it was ${esc(mem.summary || 'the same search')}. Same again, or has anything changed?</p>`
          + (extra.length ? `<p class="wb-extra">${extra.join('')}</p>` : '')
          + `<button type="button" data-act="same">Same again <span>↗</span></button><button type="button" data-act="change">Something's changed</button><button type="button" class="wb-link" data-act="forget">Forget me</button>`
          + `<small class="wb-tech">Memory: H-MEM style · Beliefs: World Model style, versioned, never overwritten${away ? ' · replies read by Nemotron' : ''}</small>`;
        if (flips && flips.recent) flips.recent.forEach((r) => ui.change({ ...r, type: 'change', earlier: true }));  // the Changes panel opens with the history, newest first
        box.onclick = (e) => {
          const b = e.target.closest('button'); if (!b) return;
          if (b.dataset.act === 'same' && actions && actions.sameAgain) actions.sameAgain();
          else if (b.dataset.act === 'change') { el.text.placeholder = 'Tell me what’s different, e.g. “under 800 this time”'; el.text.focus(); }
          else if (b.dataset.act === 'forget' && actions && actions.forget) actions.forget();
        };
        el.text.placeholder = 'Same again, or tell me what’s changed…';
        el.heroLede.hidden = true;
      },
      source(ev) {
        stageHeadings();
        let li = el.sources.querySelector(`li[data-name="${cssEsc(ev.name)}"]`);
        if (!li) {
          const stage = stageOf(ev);
          li = document.createElement('li'); li.dataset.name = ev.name; li.dataset.stage = stage;
          // into its group: just before the heading that follows this stage's heading (sources arrive in table order, not stage order)
          const heads = [...el.sources.querySelectorAll('li.ht-stage')]; const at = heads.findIndex((h) => h.dataset.stage === stage);
          const after = at >= 0 ? heads[at + 1] : null;
          if (after) el.sources.insertBefore(li, after); else el.sources.appendChild(li);
          li.innerHTML = '<span class="s-ico"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.4 8.3 2.4 2.4 4.8-5.1"/></svg></span><span class="s-name"></span><span class="s-n"></span>';
        }
        li.className = ev.status === 'done' ? 'done' : 'running';
        li.title = `${ev.table || ''} · ${ev.request_id || ''}${ev.mock ? ' · mock' : ''}`;
        li.querySelector('.s-name').textContent = (ev.label || ev.name).replace(/-/g, '‑');  // non-breaking hyphen: "by-laws" wraps as a whole word
        li.querySelector('.s-n').textContent = ev.status === 'done' ? `${Number(ev.rows || 0).toLocaleString('en-AU')} rows · ${fmtMs(ev.ms)}` : 'checking…';
        if (ev.mock) el.sourcesWrap.classList.add('is-mock');
        sourcesCount();
      },
      card(L) {
        if (!L || !L.id) return;
        const rank = Number(L.rank) || 99;
        let rec = cards.get(L.id);
        if (rec) { rec.L = L; rec.rank = rank; }
        else { rec = { L, rank, ask: new Set(), see: new Set(), was: new Map(), flash: null, moved: null }; cards.set(L.id, rec); }
        if (mainId !== L.id) { litKey = null; closeEvidence(); }  // a different place is being introduced: the last line and its evidence were about another one
        joinTurn = false; app.classList.add('touring');
        showMain(L.id);
      },
      cardUpdate(ev) {  // agent reply or new material: same card, new statuses; changed lines flash and keep a "was …" note
        const L = ev.listing; const rec = L && cards.get(L.id); if (!rec) return;
        const old = new Map((rec.L.cells || []).map((c) => [c.dim, c.status]));
        const flash = (L.cells || []).filter((c) => (old.has(c.dim) && old.get(c.dim) !== c.status) || (rec.flash && rec.flash.has(c.dim))).map((c) => c.dim);
        flash.forEach((dim) => { if (!rec.was.has(dim) && old.has(dim)) rec.was.set(dim, old.get(dim)); });
        rec.flash = null;
        const rank = Number(L.rank) || rec.rank; const from = rec.rank;
        rec.L = L; rec.rank = rank;
        if (L.id === mainId) renderMain(rec, flash); else renderSide();
        if (rank !== from) { rankBadges(); showMoved(rec, from, rank); }
      },
      highlight(ev) {
        const rec = cards.get(ev.listing_id); if (!rec) return;
        if (mainId !== ev.listing_id) showMain(ev.listing_id);
        app.classList.add('touring');
        litKey = ev.listing_id + '|' + ev.dim;
        if (ev.question && !rec.ask.has(ev.dim)) rec.ask.add(ev.dim);
        if (ev.viewing) { if (!rec.see) rec.see = new Set(); rec.see.add(ev.dim); }  // nothing to ask the agent on this place: the line worth checking at the viewing
        renderMain(rec);
      },
      evidence(ev) {
        evCache.set(ev.listing_id + '|' + ev.dim, ev);
        const main = mainEl();
        const row = main && main.dataset.id === ev.listing_id && main.querySelector(`.row[data-dim="${cssEsc(ev.dim)}"]`);
        if (row) { row.classList.add('has-ev'); openEvidence(ev, !row.classList.contains('lit')); }
      },
      change(ev) {  // arrives just before the card_update it explains: toast it, log it, and let that update show "was <from>" on the line
        // ev.earlier = a belief flip from an earlier visit (beliefs.py via /api/hello): listed, not toasted, nothing to re-rank now
        const rec = cards.get(ev.listing_id); const addrOf = (id) => { const r = cards.get(id); return r ? splitTitle(r.L)[0] : (id === ev.listing_id && ev.street ? ev.street : id); };
        if (rec && ev.dim && !ev.earlier) { if (ev.from && !rec.was.has(ev.dim)) rec.was.set(ev.dim, ev.from); (rec.flash = rec.flash || new Set()).add(ev.dim); }
        const before = ev.rank_before || [], after = ev.rank_after || [];
        const reranked = !ev.earlier && after.length > 0 && before.join() !== after.join();
        const src = SOURCE_NAMES[ev.source] || sentence(String(ev.source || '').replace(/_/g, ' '));
        const when = ev.ts ? (ev.earlier ? fmtWhen(ev.ts) : String(ev.ts).slice(11, 16)) : '';
        const ver = ev.version ? `<span class="ch-ver" title="Belief version (beliefs.py): every flip is a new version; the old one stays on file">v${esc(ev.from_version)} → v${esc(ev.version)}</span>` : '';
        const reader = ev.reader === 'llm' ? `<span class="ch-reader">read by ${esc(modelName(ev.model || 'Nemotron'))}</span>` : '';
        const li = document.createElement('li'); if (ev.earlier) li.className = 'earlier';
        li.innerHTML = `<div class="ch-top"><b>${esc(addrOf(ev.listing_id))}</b><span>${esc(src)}${when ? ' · ' + esc(when) : ''}</span></div>`
          + `<div class="ch-line"><span class="ch-dim">${esc(ev.label)}</span>${chip(ev.from)}<span class="arrow" aria-label="to">→</span>${chip(ev.to)}${ver}${reader}</div>`
          + (reranked ? `<div class="ch-rank">New order: ${after.map((id, i) => `#${i + 1} ${esc(addrOf(id))}`).join(', ')}</div>` : '');
        if (ev.earlier) el.changes.append(li); else el.changes.prepend(li);
        el.changesBox.hidden = false; el.changesCount.textContent = String(el.changes.children.length);
        if (ev.earlier) return;
        let moved = '';
        if (reranked) {
          const moves = [];
          after.forEach((id, i) => { const r = cards.get(id); if (r && r.rank !== i + 1) { moves.push([r, r.rank, i + 1]); r.rank = i + 1; } });
          rankBadges();
          moves.forEach(([r, from, to]) => { showMoved(r, from, to); if (r.L.id === ev.listing_id) moved = ` · now #${to}`; });
        }
        toast(`${addrOf(ev.listing_id)} · ${ev.label}: ${STATUS[ev.from] || ev.from} → ${STATUS[ev.to] || ev.to} (${src.toLowerCase()})${moved}`);
      },
      meter(db, thr) {
        if (!el.meterBar) return;
        const pct = (v) => Math.max(0, Math.min(100, ((v + 75) / 60) * 100));
        el.meterBar.style.width = pct(db) + '%'; el.meterThr.style.left = pct(thr) + '%';
        ui.level((db - thr + 10) / 30);
      },
      clear() {
        resetShortlist(); el.mainSlot.replaceChildren(); el.side.innerHTML = ''; el.stage.classList.remove('refreshing');
        asking = false; searchOpen = false; joinTurn = false;
        el.criteria.innerHTML = ''; el.criteria.hidden = true; el.needsResults.innerHTML = ''; el.needsResults.hidden = true; el.sources.innerHTML = ''; el.sourcesCount.textContent = ''; el.sourcesWrap.classList.remove('is-mock');
        el.changes.innerHTML = ''; el.changesBox.hidden = true; el.changesCount.textContent = '0';
        el.caption.textContent = ''; el.caption.classList.remove('dim'); ui.transcript('', false); el.conversation.hidden = true;
        panel.reset(); panel.close(); panel.setResults(0); panel.setContext(null);
        homeCompare.clear(); appliedFilters = emptyRentalFilters(); updateFilterIndicator();
        const wb = document.getElementById('welcome-back'); if (wb) { wb.remove(); el.heroLede.hidden = false; }
        setStage('home'); if (!RM.matches) resetOrbit();
      },
    };
    setStage('home');
    return ui;
  }
  return { create, esc, fmtDate };
})();
