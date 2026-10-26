import {FEATURE_GROUPS, currentSydneyDate} from './rental-filters.js?v=6';

const featureNames = Object.fromEntries(FEATURE_GROUPS.flatMap(group => group.items));
const preferenceNames = {pet:'Pets', sunny:'Natural light', quiet:'Quiet surroundings', furnished:'Furnishing'};
let instanceCount = 0;
const finite = value => typeof value === 'number' && Number.isFinite(value);
const money = value => finite(value) ? `$${value.toLocaleString('en-AU')}` : 'Not listed';
const count = value => finite(value) ? String(value) : 'Not listed';
function availability(value, today) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return 'Ask first';
  const date = new Date(`${value}T12:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0,10) !== value) return 'Ask first';
  return value <= today ? 'Now' : new Intl.DateTimeFormat('en-AU', {day:'numeric',month:'short',...(value.slice(0,4) !== today.slice(0,4) ? {year:'numeric'} : {}),timeZone:'UTC'}).format(date);
}
function preferenceValue(home, key) {
  if (key === 'furnished') return home.furnished === true ? 'Furnished' : home.furnished === false ? 'Unfurnished' : 'Not listed';
  if (['pet','sunny','quiet'].includes(key)) {
    const listed = Array.isArray(home.tags) && home.tags.includes(key);
    if (key === 'pet') return listed ? 'Considered' : 'Ask first';
    return listed ? 'Listed' : 'Not listed';
  }
  return Array.isArray(home.features) && home.features.includes(key) ? 'Listed' : 'Not listed';
}

/** Pure presentation model. Absence of a tag/feature never becomes a negative factual claim. */
export function comparisonRows(homes, criteria = {}, today = currentSydneyDate()) {
  const pair = homes.slice(0,2);
  const row = (key, label, read, group = 'facts') => {
    const values = pair.map(read);
    return {key, label, values, group, different:values.length === 2 && values[0] !== values[1]};
  };
  const rows = [
    row('rent', 'Weekly rent', home => money(home.price)),
    row('beds', 'Bedrooms', home => home.beds === 0 ? 'Studio' : count(home.beds)),
    row('baths', 'Bathrooms', home => count(home.baths)),
    row('area', 'Floor area', home => finite(home.areaSize) ? `${home.areaSize} m²` : 'Not listed'),
    row('available', 'Available', home => availability(home.available, today)),
  ];
  const active = [
    ...['pet','sunny','quiet','furnished'].filter(key => criteria[key] === true),
    ...(Array.isArray(criteria.features) ? criteria.features.filter(key => featureNames[key]) : []),
  ];
  // A caller may supply an explicit priority order; otherwise use the stable criteria order above.
  const ordered = Array.isArray(criteria.priorityKeys) ? [...criteria.priorityKeys.filter(key => active.includes(key)), ...active] : active;
  const priorities = [...new Set(ordered)].slice(0,2);
  const keys = priorities.length ? priorities : ['furnished','pet'];
  for (const key of keys) rows.push(row(`preference-${key}`, preferenceNames[key] || featureNames[key], home => preferenceValue(home,key), priorities.length ? 'priorities' : 'details'));
  return rows;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function button(className, text, action) {
  const node = element('button', className, text);
  node.type = 'button';
  if (action) node.addEventListener('click',action);
  return node;
}
function originalIcon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('aria-hidden','true');
  const use = document.createElementNS('http://www.w3.org/2000/svg','use');
  use.setAttribute('href',`#i-${name}`);
  svg.append(use);
  return svg;
}
function photo(home, className) {
  const img = element('img', className);
  img.src = home.image;
  img.alt = `${home.title || home.area} — illustrative design photography`;
  img.decoding = 'async';
  return img;
}
function ensureStyles() {
  const url = new URL('./home-compare.css?v=6', import.meta.url).href;
  if ([...document.querySelectorAll('link[rel="stylesheet"]')].some(link => link.href === url)) return;
  const link = element('link');
  link.rel = 'stylesheet';
  link.href = url;
  link.dataset.homeCompareStyle = '';
  document.head.append(link);
}

export function createHomeCompare({homes, getCriteria = () => ({}), onOpenHome, onAsk, notify, onOpen, onSelectionChange} = {}) {
  ensureStyles();
  const prefix = `home-compare-${++instanceCount}`;
  const abort = new AbortController();
  const selected = [];
  let destroyed = false, returnFocus = null, restoreOnClose = true;
  const allHomes = () => typeof homes === 'function' ? homes() : homes || [];
  const find = id => allHomes().find(home => String(home.id) === String(id));
  const pair = () => selected.map(find).filter(Boolean);
  const criteria = () => getCriteria() || {};

  const live = element('div','home-compare-live');
  live.setAttribute('role','status');
  live.setAttribute('aria-live','polite');
  const tray = element('section','home-compare-tray');
  tray.setAttribute('aria-label','Selected homes to compare');
  tray.hidden = true;
  const picks = element('div','home-compare-picks');
  const compareButton = button('home-compare-primary','Compare',() => open());
  tray.append(picks,compareButton);

  const dialog = element('dialog','home-compare-dialog');
  dialog.setAttribute('aria-labelledby',`${prefix}-title`);
  dialog.setAttribute('aria-describedby',`${prefix}-note`);
  const heading = element('header','home-compare-heading');
  const title = element('h2','','Side by side.');
  title.id = `${prefix}-title`;
  const closeButton = button('home-compare-close','',() => close());
  closeButton.append(originalIcon('close'));
  closeButton.setAttribute('aria-label','Close comparison');
  closeButton.autofocus = true;
  heading.append(title,closeButton);
  const scroll = element('div','home-compare-scroll');
  const table = element('table','home-compare-table');
  const caption = element('caption','home-compare-live','Two illustrative homes');
  const tableHead = element('thead');
  table.append(caption,tableHead);
  scroll.append(table);
  const footer = element('footer','home-compare-footer');
  const note = element('p','home-compare-note','Illustrative listings · sample details');
  note.id = `${prefix}-note`;
  const footerActions = element('div','home-compare-footer-actions');
  const clearButton = button('home-compare-text','Clear comparison',() => clear());
  const askButton = button('home-compare-primary','Ask about both',() => {
    const chosen = pair();
    const currentCriteria = criteria();
    close(false);
    queueMicrotask(() => onAsk?.(chosen,currentCriteria));
  });
  askButton.hidden = typeof onAsk !== 'function';
  footerActions.append(clearButton,askButton);
  footer.append(note,footerActions);
  dialog.append(heading,scroll,footer);
  document.body.append(tray,dialog,live);

  function announce(message) {
    live.textContent = message;
    notify?.(message);
  }
  function restoreFocus() {
    if (destroyed || document.querySelector('dialog[open]')) return;
    if (returnFocus?.isConnected && !returnFocus.closest('[inert]') && returnFocus.getClientRects().length) {
      returnFocus.focus({preventScroll:true});
    }
  }
  dialog.addEventListener('cancel',event => {event.preventDefault(); close();},{signal:abort.signal});
  dialog.addEventListener('close',() => {
    document.body.classList.remove('home-compare-open');
    refresh();
    if (restoreOnClose) queueMicrotask(restoreFocus);
    restoreOnClose = true;
  },{signal:abort.signal});
  dialog.addEventListener('click',event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
  },{signal:abort.signal});

  function emitSelection() { onSelectionChange?.([...selected]); }
  function remove(id) {
    const index = selected.indexOf(String(id));
    if (index < 0) return;
    selected.splice(index,1);
    if (dialog.open) close();
    refresh();
    emitSelection();
    live.textContent = `${selected.length} of 2 homes selected`;
  }
  function toggle(id) {
    if (destroyed || !find(id)) return false;
    id = String(id);
    if (selected.includes(id)) { remove(id); return false; }
    if (selected.length === 2) { announce('Compare two homes at a time. Remove one first.'); return false; }
    selected.push(id);
    refresh();
    emitSelection();
    live.textContent = `${selected.length} of 2 homes selected`;
    return true;
  }
  function clear() {
    if (destroyed) return;
    if (dialog.open) close();
    selected.splice(0);
    refresh();
    emitSelection();
    live.textContent = 'Comparison cleared';
  }
  function view(home) {
    close(false);
    queueMicrotask(() => onOpenHome?.(home.id));
  }
  function renderTray() {
    picks.replaceChildren();
    for (const home of pair()) {
      const item = element('div','home-compare-pick');
      const name = element('span','home-compare-pick-name',home.area?.split(',')[0] || home.title);
      const removeButton = button('home-compare-remove','',() => remove(home.id));
      removeButton.append(originalIcon('close'));
      removeButton.setAttribute('aria-label',`Remove ${home.title || home.area} from comparison`);
      item.append(photo(home,'home-compare-thumb'),name,removeButton);
      picks.append(item);
    }
    if (selected.length === 1) picks.append(element('span','home-compare-empty','Choose one more'));
    compareButton.textContent = `Compare ${selected.length}`;
    compareButton.disabled = selected.length !== 2;
    compareButton.setAttribute('aria-label',selected.length === 2 ? 'Compare the two selected homes' : 'Select one more home to compare');
    tray.hidden = selected.length === 0 || dialog.open;
  }
  function renderDialog() {
    const chosen = pair();
    const focusKey = dialog.contains(document.activeElement) ? document.activeElement.dataset.compareFocus : null;
    tableHead.replaceChildren();
    for (const body of [...table.tBodies]) body.remove();
    const headRow = element('tr');
    chosen.forEach((home,index) => {
      const cell = element('th','home-compare-home');
      cell.scope = 'col';
      cell.id = `${prefix}-home-${index}`;
      const photoButton = button('home-compare-photo','',() => view(home));
      photoButton.setAttribute('aria-label',`View ${home.title || home.area}`);
      photoButton.dataset.compareFocus = `photo-${home.id}`;
      photoButton.append(photo(home,''));
      cell.append(photoButton,element('span','home-compare-home-name',home.title || 'Home'),element('span','home-compare-home-area',home.area?.split(',')[0] || 'Location not listed'));
      headRow.append(cell);
    });
    tableHead.append(headRow);
    let currentGroup = 'facts';
    for (const row of comparisonRows(chosen,criteria())) {
      const body = element('tbody',row.different ? 'home-compare-different' : '');
      if (row.group !== currentGroup) {
        currentGroup = row.group;
        const groupRow = element('tr');
        const groupCell = element('th','home-compare-group',row.group === 'priorities' ? 'Your priorities' : 'More details');
        groupCell.colSpan = 2;
        groupRow.append(groupCell);
        body.append(groupRow);
      }
      const labelRow = element('tr');
      const label = element('th','home-compare-label',row.label);
      label.colSpan = 2;
      label.scope = 'rowgroup';
      label.id = `${prefix}-${row.key}`;
      labelRow.append(label);
      const values = element('tr','home-compare-values');
      row.values.forEach((value,index) => {
        const cell = element('td',row.key === 'rent' ? 'home-compare-rent' : '',value);
        cell.setAttribute('headers',`${prefix}-home-${index} ${prefix}-${row.key}`);
        values.append(cell);
      });
      body.append(labelRow,values);
      table.append(body);
    }
    const actionsBody = element('tbody');
    const actionsRow = element('tr');
    chosen.forEach(home => {
      const cell = element('td','home-compare-home-action');
      const viewButton = button('home-compare-view','View home',() => view(home));
      viewButton.dataset.compareFocus = `view-${home.id}`;
      viewButton.setAttribute('aria-label',`View ${home.title || home.area}`);
      cell.append(viewButton);
      actionsRow.append(cell);
    });
    actionsBody.append(actionsRow);
    table.append(actionsBody);
    if (focusKey) [...dialog.querySelectorAll('[data-compare-focus]')].find(node => node.dataset.compareFocus === focusKey)?.focus({preventScroll:true});
  }
  function refresh() {
    if (destroyed) return;
    for (let index = selected.length - 1; index >= 0; index--) if (!find(selected[index])) selected.splice(index,1);
    if (dialog.open && selected.length !== 2) close();
    renderTray();
    if (dialog.open) renderDialog();
  }
  function open() {
    if (destroyed) return false;
    if (pair().length !== 2) { announce('Choose two homes to compare.'); return false; }
    if (dialog.open) { refresh(); return true; }
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    onOpen?.();
    renderDialog();
    restoreOnClose = true;
    dialog.showModal();
    document.body.classList.add('home-compare-open');
    tray.hidden = true;
    closeButton.focus({preventScroll:true});
    return true;
  }
  function close(restore = true) {
    if (!dialog.open) return;
    restoreOnClose = restore;
    dialog.close();
  }
  function setHost(host = null) {
    if (destroyed) return;
    const destination = host?.nodeType === 1 ? host : document.body;
    tray.classList.toggle('compare-tray-inline',destination !== document.body);
    destination.append(tray);
  }
  function destroy() {
    if (destroyed) return;
    if (dialog.open) close(false);
    destroyed = true;
    abort.abort();
    document.body.classList.remove('home-compare-open');
    tray.remove();
    dialog.remove();
    live.remove();
  }
  return {tray,dialog,toggle,isSelected:id => selected.includes(String(id)),selectedIds:() => [...selected],open,close,refresh,sync:refresh,clear,setHost,destroy};
}
