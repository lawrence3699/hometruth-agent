// ink.js · the page's own line drawings for the Notion-style preview (2026-10-27). Drawn for HomeTruth in the manner of notion.com's
// illustrations (thick black ink, flat fills, hatching); nothing here is copied from Notion. Each is a string of inline SVG.
const H = (id) => `<defs><pattern id="${id}" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="#111" stroke-width="1.6"/></pattern></defs>`;
const S = 'fill="none" stroke="#111" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"';

export const LOGO = `<svg class="nt-logo" viewBox="0 0 28 28" aria-hidden="true"><rect x="2" y="2" width="24" height="24" rx="5.5" fill="#fff" stroke="#111" stroke-width="2.4"/><path d="M7.6 14.6 14 9l6.4 5.6M9.6 13.1v7.3h8.8v-7.3" fill="none" stroke="#111" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/><path d="m11.9 16.9 1.6 1.6 3-3.2" fill="none" stroke="#0075de" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// a house being looked at through a magnifying glass, the lens showing a tick
export const HOUSE = `<svg viewBox="0 0 250 200" ${S} role="img" aria-label="Drawing of a house under a magnifying glass">${H('ink-h1')}
<path d="M12 182c52-4 120 3 226-3"/>
<path d="M48 181V97l62-49 62 49v84z" fill="#fff"/>
<path d="M54 96 110 52l56 44z" fill="url(#ink-h1)" stroke="none"/>
<path d="M34 106 110 44l76 62"/>
<path d="M140 64V40h16v37" fill="#fff"/>
<rect x="93" y="128" width="34" height="53" rx="3" fill="#ffb110"/>
<circle cx="119" cy="156" r="2.4" fill="#111" stroke="none"/>
<rect x="60" y="113" width="24" height="24" rx="2.5" fill="#e6f3fe"/><path d="M72 113v24M60 125h24"/>
<circle cx="182" cy="136" r="31" fill="#fff"/><circle cx="182" cy="136" r="22" fill="#f2f9ff" stroke-width="2"/>
<path d="M170 136l9 9 16-18" stroke="#0075de" stroke-width="5.5"/>
<path d="M204 159l25 25" stroke-width="10"/>
<path d="M203 44l9-9M214 60h13M196 30V17" stroke-width="3"/>
</svg>`;

// a clipboard whose four lines carry the four statuses: supported, inferred, conflict, unknown
export const CLIPBOARD = `<svg viewBox="0 0 210 220" ${S} role="img" aria-label="Drawing of a clipboard with four checked lines">
<rect x="40" y="32" width="130" height="176" rx="10" fill="#fff"/>
<rect x="73" y="18" width="64" height="28" rx="7" fill="#ffb110"/><circle cx="105" cy="31" r="4" fill="#fff" stroke-width="2.4"/>
<circle cx="67" cy="78" r="11" fill="#1aae39"/><path d="m61.5 78.5 4 4 7-8" stroke="#fff" stroke-width="3"/>
<path d="M89 74h56M89 85h34" stroke-width="3"/>
<circle cx="67" cy="114" r="11" fill="#fff"/><path d="M67 103a11 11 0 0 0 0 22z" fill="#ffb110" stroke="none"/><circle cx="67" cy="114" r="11"/>
<path d="M89 110h46M89 121h40" stroke-width="3"/>
<circle cx="67" cy="150" r="11" fill="#f64932"/><path d="m62.5 145.5 9 9m0-9-9 9" stroke="#fff" stroke-width="3"/>
<path d="M89 146h52M89 157h26" stroke-width="3"/>
<circle cx="67" cy="186" r="11" fill="#fff" stroke-dasharray="4 4"/><path d="M63.6 183a3.6 3.6 0 1 1 5 3.3c-1 .5-1.6 1.2-1.6 2.3" stroke-width="2.6"/><circle cx="67" cy="193.2" r="1.4" fill="#111" stroke="none"/>
<path d="M89 182h40M89 193h22" stroke-width="3"/>
<path d="M182 50l10-10M186 70h14M174 34V20" stroke-width="3"/>
</svg>`;

// a key on a ring with a hatched tag: the place you end up taking
export const KEY = `<svg viewBox="0 0 240 150" ${S} role="img" aria-label="Drawing of a house key with a tag">${H('ink-h2')}
<circle cx="70" cy="76" r="36" fill="#0075de"/><circle cx="70" cy="76" r="13" fill="#fff"/>
<path d="M106 76h112"/><path d="M190 76v20h12V76M164 76v14h12V76" fill="#fff"/>
<path d="M46 49C38 36 32 30 26 28"/>
<path d="M6 22l22-8 9 26-22 8z" fill="#fff"/><path d="M6 22l22-8 9 26-22 8z" fill="url(#ink-h2)"/><circle cx="24" cy="23" r="2.4" fill="#fff"/>
<path d="M214 40l9-9M222 56h12M204 28V16" stroke-width="3"/>
</svg>`;

// a speech bubble with a question mark: what to ask the agent
export const ASK = `<svg viewBox="0 0 120 100" ${S} role="img" aria-label="Drawing of a speech bubble with a question mark">
<path d="M14 18h92v52H52L28 90V70H14z" fill="#fff"/>
<path d="M50 36a10 10 0 1 1 14 9c-2.6 1.3-4 3-4 6v1" stroke-width="4"/><circle cx="60" cy="61" r="2.6" fill="#111" stroke="none"/>
</svg>`;

// someone peeking over the top edge of the product window, hands on the edge (notion.com puts a doodle beside its product shot)
export const PEEK = `<svg viewBox="0 0 160 104" ${S} role="img" aria-label="Drawing of someone peeking over the window">
<path d="M40 101C36 66 52 34 80 34s44 32 40 67z" fill="#fff" stroke="none"/><path d="M40 101C36 66 52 34 80 34s44 32 40 67"/>
<path d="M41 74C38 46 56 30 80 30c24 0 42 16 39 44-6-12-18-18-30-14-8-10-26-10-34 2-6 2-10 6-13 12z" fill="#111"/>
<circle cx="66" cy="72" r="10" fill="#e6f3fe" stroke-width="3"/><circle cx="94" cy="72" r="10" fill="#e6f3fe" stroke-width="3"/><path d="M76 72h8" stroke-width="3"/>
<circle cx="66" cy="76" r="3" fill="#111" stroke="none"/><circle cx="94" cy="76" r="3" fill="#111" stroke="none"/>
<path d="M80 86q-3 4 2 6" stroke-width="2.6"/>
<path d="M22 104V93a8 8 0 0 1 16 0v11" fill="#fff"/><path d="M28 97v7M33 97v7" stroke-width="2.4"/>
<path d="M122 104V93a8 8 0 0 1 16 0v11" fill="#fff"/><path d="M127 97v7M132 97v7" stroke-width="2.4"/>
<path d="M141 42l8-8M145 57h10M133 28V16" stroke-width="3"/>
<path d="M17 34l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" fill="#ffb110" stroke-width="2.2"/>
</svg>`;
