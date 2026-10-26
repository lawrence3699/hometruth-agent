"""Headless replay of the ask flow on a fresh renter (10-27, after the page froze at "Thanks."):
Hello -> first ask -> answer typed while the ask is still being spoken (an interruption) -> bridge -> second ask -> Listening.
Records phase / caption transitions, console errors, screenshots the page and the panel's voice view (Orb at 160 px), and
reports the Orb host box. A page whose main thread freezes makes this script stop at the first probe (the 160 s alarm ends it).

Usage: python3 scripts/ui_flow_check.py http://127.0.0.1:8630 runs/screenshots/flow [/qi]   (or https://hometruth.codeprism.tech; the client UA is set)
The selectors are the qi shell's, which lives at /qi since the Notion page took / (10-27 evening); pass another path to replay a different page.
Needs the system python3 with playwright + its chromium (Mac: already there). Pass check: final.phase == listening, final.timeline == 0, no pageerror (expect is already false again by then: the done event clears it)."""
import sys, time, json, os, signal
signal.alarm(160)
from playwright.sync_api import sync_playwright
import os
base = sys.argv[1]; out = sys.argv[2]; path = sys.argv[3] if len(sys.argv) > 3 else '/qi'; os.makedirs(out, exist_ok=True)
STATE = """({phase:document.querySelector('#app').dataset.phase, hero:document.querySelector('#hero-title').textContent.trim(),
 status:(document.querySelector('.agent-status')||{textContent:''}).textContent.trim(), msg:(document.querySelector('.agent-message')||{textContent:''}).textContent.trim(),
 caption:(document.querySelector('#caption')||{textContent:''}).textContent.trim(), timeline:HT.S.timeline.length, playing:HT.S.playing, streamOpen:HT.S.streamOpen, expect:HT.S.expectAnswer, paused:HT.S.pausedForUser})"""
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
    pg = b.new_page(viewport={'width': 1400, 'height': 900}, user_agent='HomeTruth-client/1')
    pg.on('console', lambda m: errors.append('console.' + m.type + ': ' + m.text) if m.type in ('error', 'warning') else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.goto(base + path); pg.wait_for_timeout(1500)
    pg.evaluate("localStorage.clear(); sessionStorage.clear()"); pg.reload(); pg.wait_for_selector('#hero-title', timeout=30000); pg.wait_for_function('window.HT && HT.S && HT.S.hello', timeout=30000); pg.wait_for_timeout(800)  # the page is built by ui-qi.js and /api/hello has answered
    trans = []; last = None
    def rec(tag):
        global last
        st = pg.evaluate(STATE); key = (st['phase'], st['caption'], st['status'])
        if key != last: trans.append((round(time.time() - t0, 1), tag, st)); last = key; print(f"{time.time()-t0:5.1f}s {tag:12s} phase={st['phase']:10s} status={st['status']!r:30s} caption={st['caption'][:60]!r}", flush=True)
        return st
    t0 = time.time()
    pg.fill('input[placeholder^="Or type"]', 'Hello'); pg.press('input[placeholder^="Or type"]', 'Enter')
    # wait for the first ask to be spoken (caption mentions budget) and interrupt it mid-sentence, like the renter did
    answered = False
    for i in range(240):
        st = rec('t1')
        if not answered and st['playing'] and 'budget' in st['caption'].lower():
            pg.wait_for_timeout(400)
            inp = pg.locator('input[placeholder^="Or send"]')
            inp.fill('Two bedrooms and the city no need for budget'); inp.press('Enter'); answered = True; t_ans = time.time(); rec('answer-sent')
        if answered and st['expect'] and not st['playing'] and st['timeline'] == 0 and 'thanks' not in st['caption'].lower() and time.time() - t_ans > 1.5:
            break
        pg.wait_for_timeout(250)
    final = rec('final')
    pg.screenshot(path=out + '/flow_final.png')
    # voice view of the panel: the Orb at 160px
    pg.evaluate("const b=document.querySelector('.agent-circle'); if(b && b.getAttribute('aria-label')==='Show voice') b.click();")
    pg.wait_for_timeout(1200)
    pg.locator('.agent-panel').screenshot(path=out + '/panel_voice.png')
    orb = pg.evaluate("(()=>{const h=document.querySelector('#voice-orb-host'); const r=h.getBoundingClientRect(); const p=document.querySelector('.agent-panel').getBoundingClientRect(); const o=h.querySelector('.agents-original-orb'); return {x:r.x-p.x,y:r.y-p.y,w:r.width,h:r.height,renderer:o.dataset.renderer,clip:getComputedStyle(o).clipPath,mode:document.querySelector('.agent-panel').dataset.mode}})()")
    b.close()
json.dump({'transitions': trans, 'final': final, 'orb': orb, 'errors': errors, 'answered': answered}, open(out + '/flow.json', 'w'), indent=1, ensure_ascii=False)
print('answered:', answered)
for t, tag, st in trans: print(f"{t:5.1f}s {tag:12s} phase={st['phase']:10s} status={st['status']!r:28s} caption={st['caption'][:70]!r}")
print('final:', json.dumps(final, ensure_ascii=False))
print('orb:', orb)
print('errors:', errors[:10])
