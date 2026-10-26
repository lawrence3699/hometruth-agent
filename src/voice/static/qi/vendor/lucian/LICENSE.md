# Lucian UX/UI Prompt · elements used by HomeTruth

Source: https://lucianlabs.dev/uxui-prompt/ (catalog version 34c4b3e61d, downloaded 2026-10-27).
Copyright (c) 2026 Seokwoooo. Licensed under the MIT License (full text below).

The `NNN-<slug>.txt` files in this folder are the unmodified originals (first line = the author's copyright comment);
`tokens.css` is the author's theme-token sheet. HomeTruth's ports live in `../../lucian-effects.css` and
`../../lucian-effects.js`: each block there is named by the element number, the `--ux-*` tokens are mapped to the
page's own variables, selectors are scoped as `.ht-fx-NNN…`, and only the part of each element that fits the page
is kept (noted in the block comment). Nothing in this folder is loaded by the page.

## Elements used (25)

| # | Title | Where it ended up |
|---|---|---|
| 002 | Magnetic arrow button | the send button: arrow shoots out on submit, light pull toward the pointer |
| 014 | To-do checklist | the progress ring on each source group heading |
| 018 | Rolling quantity stepper | the odometer on the rank badge and the Saved count |
| 019 | Interest chips multi-select | the needs chips: check slides out when a need is answered; the one being asked flashes |
| 022 | Heart burst like | the save button burst |
| 039 | Sliding pill tabs | the nav pill (Find a place / Explore / Saved) and the suburb groups |
| 047 | Period segmented control | count-up on source row counts, the grid's place count and the card tally |
| 050 | Spotlight-tilt news card | glare + border light + small lift on the photo out front (no tilt) |
| 070 | Stacking toasts | the toast stack |
| 081 | Payment ring and check | the evidence block rising under its line, ring drawn around the status word |
| 083 | Queue bar turning into progress | the bar under "Sources" and the drawn checks on each source |
| 084 | Voice-reactive dot loader | the five dots next to the status line (listening / thinking / speaking) |
| 086 | Streaming AI answer | the caption arriving word by word, cursor while speaking |
| 090 | Error widget that plugs back in | the pulled plug next to an error line |
| 092 | Empty search that loosens filters | the magnifier over empty shelves on the empty grid |
| 212 | Hide-on-scroll header | the top bar coming back slim and blurred when scrolling up through the grid |
| 216 | Staggered hero entrance | the first screen rising in, in order |
| 228 | Cursor-lit glowing card borders | grid cards and small cards lit from the pointer |
| 233 | Rotating-example AI prompt box | the glowing border of the box while it has focus |
| 237 | Line-by-line mask reveal headline | the big headline and its changes |
| 251 | Staggered scroll-in feature cards | the underline of "Every place I can check." |
| 263 | Flowing gradient headline and thinking text | the sheen on "Checking…" while it is still thinking |
| 326 | Flipping-cell waffle chart | a status word flipping to its new colour |
| 363 | Dot grid waves from the cursor | the faint dot grid behind the orbit |
| 368 | Sentence-following reading focus | the bar that glides to the line being discussed |

## Also used by the Notion-style preview (static/notion/notion-fx.js, 2026-10-27)

Ports written for that page's own DOM; each function in notion-fx.js names its element number. Eight originals were added
to this folder for it (044, 056, 061, 213, 217, 260, 271, 275).

| # | Title | Where it ended up |
|---|---|---|
| 002 | Magnetic arrow button | the round black arrow on "Refine with a conversation" |
| 014 | To-do checklist | each source's circle filling and its tick drawing itself in the sidebar |
| 019 | Interest chips multi-select | a need's property tag popping in, its tick sliding out |
| 039 / 047 | Sliding pill tabs / Period segmented control | the database view tabs' underline, the Explore filters and the week/month switch (knob stretches, then catches up) |
| 044 | FAQ accordion | Questions & answers |
| 056 | Monthly–yearly pricing toggle | rents rolling digit by digit between per week and per month |
| 061 | Thumbnail-to-lightbox zoom | photos and the floor plan in the side peek |
| 070 | Stacking toasts | a change from an agent reply |
| 083 | Queue bar turning into progress | the bar under "Sources" |
| 084 | Voice-reactive dot loader | the dots in the talk button (listening / thinking / speaking) |
| 086 | Streaming AI answer | what it says, arriving word by word in the callout |
| 212 | Hide-on-scroll header | the nav, with the reading-progress line |
| 213 | Auto-advancing feature tabs | used in the first version (2026-10-27); the second round replaced the tabs with bento cards, the file stays for reference |
| 216 | Staggered hero entrance | the first screen, the product window last, tilted and blurred |
| 217 | Plan comparison with differences only | the Table view: column lights up, "Differences only" folds equal rows |
| 233 | Rotating-example AI prompt box | example requests typing themselves into the empty box |
| 237 | Line-by-line mask reveal headline | the rotating word in the hero pill and the section headings |
| 251 | Staggered scroll-in feature cards | cards and gallery tiles rising in; each bento card's product slice plays once in view |
| 260 | Scroll-filled sentence | "An unknown is not a yes…" |
| 263 | Flowing gradient headline and thinking text | the sheen on "Checking the sources…" |
| 271 | Filterable changelog | the Changes view timeline |
| 275 | Scroll-following table of contents | the place page's sticky tab row (Checks / Photos / 3D plan / Features), knob from #039 |

## MIT License

Copyright (c) 2026 Seokwoooo

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
