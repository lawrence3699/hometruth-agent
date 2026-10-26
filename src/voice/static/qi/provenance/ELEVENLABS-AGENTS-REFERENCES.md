# ElevenLabs Agents communication UI — v5 evidence

Inspected 25 October 2026 in Chrome: https://elevenlabs.io/agents.
Opened its launcher only. The panel remained disconnected; no call, message, microphone permission or terms acceptance occurred.

## Direct DOM measurements

- Expanded panel: `380 × 480px`, constrained to `min(380px, 100vw - 32px)`; white, `28px` corner radius. Its outer hairline uses black at 5%. Shadow: `0 2px 4px rgba(0,0,0,.04), 0 6px 16px rgba(0,0,0,.04)`.
- Compact launcher: `56px` tall on desktop; `36px` decorative orb, left/bottom inset `10px`. The viewport bottom margin is `16px`.
- Orb: `160 × 160px`, at `left:50%; top:50%; margin-left:-80px; margin-top:-128px`. In the 380 × 480 panel, its bounds start at `(110,112)`.
- Top controls: `40px` circular buttons at `12px` from the top and side. Background `#F5F3F1`, black icons `20px`. The right control is **Collapse**, which returns the panel to its launcher; it is not a larger-window/maximize control. The left is **Show messages**.
- Status/intro region starts at panel y=`296px` (`top:50% + 56px`), with `24px` horizontal padding. Source type is Inter regular, `13/18px`, color `#777169`.
- Bottom toolbar: `16px` padding, `12px` gap, total height `80px`. Composer is white, `48px` high, `24px` radius. Hairline/shadow: `0 0 0 .5px rgba(0,0,0,.125), 0 1px 1px rgba(0,0,0,.04), 0 2px 4px rgba(0,0,0,.04)`.
- Input: Inter regular `16/24px`, left padding `18px`. Send icon `18px`, resting color `#A59F97`; 32px inner target and 42px button width including right padding.
- End-call button exists in the inactive DOM but is inert and transparent. It is `48px`, circular, black with an `18px` white crossed-phone icon.

## Active behavior verified from the page's public frontend source

- Starting voice requires a separate Start call action; simply opening the panel does not start a session.
- Connection states: connecting, disconnecting, speaking, thinking, listening. The chat button appears when there are messages. Chat switches the orb to `40px` at top-left `(12,12)` and displays the conversation history.
- During an active session the composer uses the remaining width beside the End button: `288px` at the 380px panel size (`288 + 12 + 48 + 32 outer padding`). This is source-derived; no live session was started to measure it.
- Status text changes are debounced `200ms` and slide vertically from `translateY(100%)` to zero, exiting at `-100%` through a top/bottom fade mask. Intro/status opacity entrance delay is `.3s`; toolbar slides up with `.2s` delay; End appears with `.15s` delay. Panel/orb use shared layout animation. An exact global spring curve was not established.
- Marketing orb source uses texture `agents-2`, `160 × 160`, noise scale `1`, exit duration `.8s`. This is visually distinct from the open-source UI Orb demo already bundled in qi.home. The final v5 conversation panel now uses the actual marketing renderer and original texture; the earlier UI Orb remains a separate hero component.

Evidence files: `agents-reference/metrics.json`, `controls.json`, `dynamic-3.js`, `expanded-widget.js` and URL manifests. The control/source chunk is loaded from ElevenLabs' public CDN; no app code was executed to bypass UI state.

## Original assets and qi.home adaptation

Original DOM paths are saved unchanged in `dist/assets/elevenlabs/`: `chat.svg`, `collapse.svg`, `call.svg`, `end.svg`, `send.svg`, plus `source-manifest.json`. Only the SVG namespace was added for standalone files. No microphone or distinct maximize SVG was present in this widget; `call.svg` is the source's phone symbol. Aliasing a control name does not turn it into a different original glyph.

qi.home copies the 380 × 480 panel, 160px orb presentation, 28px panel radius, 40px top controls and 48px end control. It keeps the user-requested Domain F37 Bolton typography and existing rental-search context. Any 520 × 640 enlarged mode is a qi.home extension, not a measured ElevenLabs breakpoint. Recognition and read-out remain browser speech APIs with local matching; the frontend does not connect to ElevenLabs Agents services.

## Final v5: original marketing renderer integration

`dist/agents-orb.js` exports `createAgentsOrb(host)`, returning `ready`, `setState`, `setLevel` and `destroy`. It lazy-loads the exact marketing renderer core from `assets/elevenlabs/orb-renderer.js` and isolated original OGL modules from `orb-engine.js`. The 40,755-character renderer body, including the fluid simulation and shader strings, is copied verbatim from the observed `24594.e2cc6e2f9d501726.js` source. React/site glue, tracking, the audio analyser and conversation connection are excluded.

Original image assets are `orb-agents-2.png` (the initial/fallback image), `orb-agents-2-texture.jpg` (the shader texture) and `orb-noise.png` (the source grain overlay). No image, shader or motion texture was generated. Source URLs, extraction boundaries, hashes and adaptations are in `dist/assets/elevenlabs/orb-source-manifest.json`. A separate license grant for this marketing renderer was not identified; it is not labelled MIT. The different ElevenLabs UI Orb's MIT license does not apply to these marketing files.

The standalone adapter owns sizing, visibility, reduced-motion and cleanup. The original renderer receives local UI-state audio-band modulation; `setLevel` can provide a normalized level, but this module does not capture or analyse a microphone. The actual shader remains unchanged.

Chrome QA confirmed the original blue/green fluid sphere, successful shader linking and `ready -> {renderer:true}`. Idle, speaking, listening and thinking states worked. Minimize/reopen retained a 320 × 320 backing canvas while hidden, with no zero-size resize or hidden-frame drawing. Destroy during texture loading settled `ready` as `{renderer:false,destroyed:true}`. Final destroy left zero canvases and zero Orb holder nodes. Application console errors: zero. The diagnostic page was moved out of `dist`; evidence screenshot is `work/agents-reference/original-renderer-qa.png`.
