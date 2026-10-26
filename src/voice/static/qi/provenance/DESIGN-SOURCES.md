# QI.HOME — reference and asset audit

Current revision 6 · 26 October 2026. The reference audit below began with revision 2 on 25 October 2026; later additions and changes are recorded chronologically.

The revision 2 audit inspected 12 sites. Eleven are listed on Recent; Domain is the user's explicitly requested typography source. Photographs, font binaries and icon paths are existing source assets. No image generation was used. The baseline animation and interface code implements observed design principles. Later use of exact official Orb source and the original Agents renderer is documented separately below.

| Site | Evidence | Applied in this frontend |
|---|---|---|
| Augen | [Recent](https://recent.design/i/erz4438-augen) · [Original](https://augen.pro/) | Compact floating navigation; white object-led canvas; soft edge reveal; a selected photo focuses before expanding; in-place depth dissolve on change; 12px dialog backdrop blur. |
| CLOU Architects | [Recent](https://recent.design/i/mhr3jzb-clou-architects) · [Original](https://www.clouarchitects.com/) | Slow elliptical orbit of six project-like photo thumbnails with restrained depth. |
| Shopify Design | [Recent](https://recent.design/i/7yio1ee-shopify-design) · [Original](https://shopify.design/) | Staggered image entrance in the lower collection and gentle image zoom on hover. |
| Resident | [Recent](https://recent.design/i/helk5ox-resident) · [Original](https://resident.co.nz/en/) | Six original interior photographs; image-first collection with minimal captions. |
| Domain | [Original](https://www.domain.com.au/) · [Rent results](https://www.domain.com.au/rent/sydney-nsw-2000/) | Original F37 Bolton regular and bold; measured semantic typography roles; original shortlist star, filter, arrows, bed and bath SVG paths. |
| Amie | [Recent](https://recent.design/i/lrqqbee-amie) · [Original](https://amie.so/) | Compact, stable recording control with elapsed time and Stop in the existing voice button. |
| Aave | [Recent](https://recent.design/i/cxrtfmi-aave) · [Original](https://aave.com/) | Consistent photo/price/attribute bands; compact matching-reason chips and aligned alternative cards. |
| Mintlify | [Recent](https://recent.design/i/me1vq8t-mintlify) · [Original](https://www.mintlify.com/) | Single search-or-ask input for all states; Command/Ctrl+K focuses the same composer. |
| Vitra Chair Finder | [Recent](https://recent.design/i/426udpb-vitra-office-chair-finder) · [Original](https://findmy.vitra.com/en-en/questionnaire/chairs) | One missing preference at a time in a small floating question card; inline weekly-budget slider while the photo world stays visible. |
| Aside | [Recent](https://recent.design/i/bxucrd4-aside) · [Original](https://aside.com/) | Explicit Pause/Resume motion control and a compact saved count. |
| Interfere | [Recent](https://recent.design/i/mysyrbt-interfere) · [Original](https://interfere.com/) | Concise matching status chip that becomes a found count; no verbose activity feed. |
| Family | [Recent](https://recent.design/i/p1lu7hn-family) · [Original](https://family.co/) | Tactile save feedback, short Saved confirmation, and immediate persistent shortlist count. |

## Domain typography measurements

All rows use `F37 Bolton, Helvetica, Arial, sans-serif`, normal letter-spacing.

| Role | Size / line height | Weight |
|---|---|---|
| Home headline | 31 / 36 px | 700 |
| Collection heading | 25 / 24 px | 700 |
| Navigation | 18 / 44 px | 400 |
| Text input | 16 / 36 px | 400 |
| Primary controls | 16 / 24 px | 700 |
| Rental price | 18 / 24 px | 400 |
| Suburb / property features | 16 / 24 px | 400 |
| Results summary | 16 / 24 px | 400 |
| Dialog title | 24 / 32 px | 400 |
| Filter group label | 18 / 28 px | 400 |

Machine-readable values: `dist/assets/domain/type-scale.json`.
Exact asset origins and checksums: `dist/assets/domain/asset-sources.json` and `dist/assets/asset-sources.json`.

## Scope

This is a frontend prototype using six illustrative homes and local matching rules. Photos illustrate space and mood; they are not photographs of the listed Sydney addresses. Voice input uses the browser's speech-recognition facility when available and after the user starts it. No AI or inventory backend was added.

## Revision 3 additions explicitly requested by the user

- [Realestate.com.au rental filters](https://www.realestate.com.au/rent/): all observed rental-filter groups and the complete 33-item facility inventory. See FILTER-PARITY.md for inspected options and limits of verification. The original site's bedroom dropdown values could not be captured; this implementation supports Studio and 1–10 independently for minimum/maximum.
- [ElevenLabs UI Orb](https://ui.elevenlabs.io/docs/components/orb): actual MIT-licensed official component and shader, bundled locally with its original Perlin texture. No lookalike image or newly drawn shader was substituted. Exact source, license, checksums, dependencies and narrow adaptations are recorded in dist/vendor/orb-sources.json.

The approved v2 visual baseline is archived by tag and Git bundle; see APPROVED-BASELINE.md. Revision 3 keeps its typography, photography and overall layout.

## Revision 4: property details and coherent galleries

The user supplied these exact pages as structural and interaction references:

- [Domain: 62 Miralie Way, Cranbourne West](https://www.domain.com.au/62-miralie-way-cranbourne-west-vic-3977-2021266717): broad image mosaic, compact media controls, price/specification hierarchy, a white photo contact sheet, and a reading column beside persistent actions. The reference is a sale listing; qi.home retains rental pricing and sample rental facts.
- [Realestate: 243 Jefferson Lane, Palm Beach](https://www.realestate.com.au/property-house-qld-palm+beach-444401552): focused dark photo viewer, image count and navigation, separated rental facts, and sticky desktop actions. The narrow-screen adaptation is our implementation choice; the reference's mobile breakpoints were not independently verified.

Both pages were inspected in the browser. Their listing photographs, floorplans, logos and agent portraits were not copied. PROPERTY-DETAIL-REFERENCES.md records observations and verification limits. The frontend combines the observed layout principles with qi.home's existing visual system; it does not claim to reproduce either site's production code.

The added original photography comes from Resident, already documented as a Recent-listed source:

| Resident project | Existing visual continuity | Gallery usage |
|---|---|---|
| [Waimataruru](https://resident.co.nz/en/news/2024/10/capturing-waimataruru-with-kristina-pickford), photography credited to Sam Hartnett | Matches the original room-1 and room-6 images | Four views of the same residential project; the two sample listings reuse that coherent set in different orders. |
| [Mt Barker House](https://resident.co.nz/en/news/2026/04/resident-project-mt-barker-house), Nuku Studio; photography credited to Biddi Rowley | Matches the original room-2 image | Five additional views join the existing photograph for a six-image gallery. |

The exact original asset URLs, dimensions, captions, credits and SHA-256 checksums are in `dist/assets/gallery/source-manifest.json`. Its floorplan fields are null. No generated photographs, fabricated floorplans or unrelated stock photographs were added. The remaining sample homes keep their single existing photograph. These photographs document the Resident projects, not the sample Sydney locations or their simulated facilities.

Property details include local shortlist state, a shareable property fragment, contextual return to the composer, and a personal viewing plan stored only in local storage. The plan does not contact an agent, reserve an inspection, or schedule a notification. Motion polish keeps the existing orbit, stages the selected image into results, preserves aspect ratios, and cleans up interrupted transitions; animation code remains a new implementation of the documented visual references.

## Revision 5: ElevenLabs Agents communication panel

The user explicitly supplied [ElevenLabs Agents](https://elevenlabs.io/agents) as the communication-interface reference. Its inactive expanded panel was inspected in Chrome, with computed DOM measurements and read-only inspection of the public frontend chunks loaded by that page. No call, message, microphone permission or terms acceptance was initiated.

The adaptation uses the measured 380 × 480px white panel, 28px corners, 160px central orb, 40px top controls at 12px insets, 48px pill composer and 48px black end-call control. Source SVG paths for chat, collapse, call, end and send were exported from the rendered DOM without path edits; `dist/assets/elevenlabs/source-manifest.json` records their origin. The original top-right control collapses the panel to a launcher; this adaptation preserves that interaction.

In revision 5, the hero retained its existing official ElevenLabs UI Orb while the floating panel used the actual marketing site’s `agents-2` PNG/JPG, grain texture, fluid simulation and WebGL renderer. Original renderer/shader code was extracted without algorithm changes; a narrow adapter supplies frontend interaction states and manages visibility, reduced motion and disposal. See `dist/assets/elevenlabs/orb-source-manifest.json` for exact URLs, checksums and extraction details. This renderer is a separate source from the MIT-licensed UI component; no license is inferred between them. F37 Bolton and the measured Domain font roles remain unchanged. Browser speech recognition and speech synthesis drive the frontend interaction; no ElevenLabs Agents service is connected. Detailed evidence and source-derived state/motion behavior are in `ELEVENLABS-AGENTS-REFERENCES.md`. Revision 6 replaces the two visible Orb implementations with one shared marketing Orb instance, as described below.

## Revision 5: Shopify Design scroll reveal

[Shopify Design](https://shopify.design/) remains the Recent-listed reference. The collection follows its varied-ratio three-column masonry and original `card-slide-in` behavior: scale 1.5 to 1, opacity established at 5%, 1.5/1.7/1.9/2.1-second durations, and `cubic-bezier(.16,1,.3,1)`. Lateral offsets of -350/0/+350px and vertical offsets of 300px plus 100px per column row are scaled from the source’s 432px card width. Mobile keeps the observed scale 1.15 and 120px vertical travel.

A stationary article anchors observation and measurement while its inner surface animates. Grid row spans preserve DOM reading order; no listing controls are cloned. Each card enters once, while filtered replacement cards enter afresh. Reduced motion, hidden pages, keyboard focus and interrupted animation cleanup reveal readable final content immediately.

## Revision 6: one continuous search flow

The user authorized six frontend upgrades using the already documented photography, fonts, icons and Orb assets. No new external source assets, generated photographs, textures or icon paths were added. The approved v2 appearance and the revision 5 source audit remain the design baseline; the following changes are frontend implementations within that system.

| Upgrade | Implemented behavior | Source continuity and limits |
|---|---|---|
| Current-viewport search workspace | Results open over the viewport where the search starts. A fixed header holds criteria and actions, with a compact composer below the internally scrolling results. The underlying browsing page becomes inert, keeps its scroll position and is restored on close. | Uses the existing white surfaces, Domain type roles and original icons. This workspace is our implementation, not copied production code from a reference site. |
| Canonical editable criteria | Filter controls, supported typed requests and recognized voice transcripts update one criteria object. Chips edit or remove the same fields. The local parser supports rent bounds, known locations, types, bedroom ranges, bathroom/parking minimums, availability, furnishing, pets, light/quiet, the existing facility vocabulary and explicit keywords, with supported English and Chinese phrasing. | Controlled “Needs checking” labels expose recognized unsupported requirements such as commute time, safety, floor level and lease duration. Ambiguities and unsupported exclusions are not presented as verified matches. This is rule parsing, not an AI model or exhaustive language understanding. |
| One shared original Agents Orb | A single `createAgentsOrb` instance and DOM host move among the entry, conversation panel and compact composer/launcher. The hero uses the same original marketing renderer. | Existing `agents-2` textures, PNG fallback, noise and original renderer/shader assets are reused. The official UI Orb added in revision 3 remains archived in the source/bundle but is unused by the current app. No marketing-asset license is inferred from its separate MIT license. |
| First reveal and faster refinement | The first search retains the photograph arrival; later criteria changes use a shorter update. Reduced motion, cancellation and hidden-page handling settle to readable final content. | Builds on the established orbit/Shopify reveal vocabulary. The added timing distinction is application code, not a new visual asset or an asserted copy of source behavior. |
| Card-to-detail photo continuity | The selected original card photograph becomes the first detail photograph and can animate back to the visible source card. Known duplicate file variants are counted once by source identity. | `room-1.jpg` / `gallery/home-1-01.jpg` and `room-6.jpg` / `gallery/home-1-03.jpg` are documented aliases of the same Resident source images. The galleries retain their actual unique views; no additional room or floorplan is invented. |
| Two-home comparison | A compact selection tray opens two equal columns showing original photos, weekly rent, bedrooms, bathrooms, floor area, availability and up to two active preference fields. Differences receive a subtle highlight. Users can open a home or ask about both. | Uses existing sample metadata, original close icon and Domain fonts. A third selection requires an explicit removal. Unknown facts remain “Not listed” or “Ask first”; no winner, score or unsupported factual negative is generated. |

The new modules are `dist/search-workspace.js` / `.css`, `dist/search-intent.js`, `dist/detail-transition.js` and `dist/home-compare.js` / `.css`; photo-transition styles live in the existing `dist/property-detail.css`. Existing application, conversation, property-detail and orbit modules connect these behaviors. In the narrow workspace header, the compare tray condenses to its action button so the compact composer and header controls remain available.

The data boundary is unchanged: six local illustrative listings, simulated metadata and rule-based matching/answers. No real AI backend, continuous-speech backend, live rental inventory or ElevenLabs agent service was added. Speech input/output still uses user-started browser APIs; the Orb shows frontend state and does not measure microphone amplitude by default.

At this documentation checkpoint, 31 parser tests and 26 existing filter tests passed (57 total), and the comparison presentation model passed its local data checks. Final integrated browser QA is still in progress; this audit does not claim complete device coverage or testing with user microphone audio.
