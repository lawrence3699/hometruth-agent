# -*- coding: utf-8 -*-
"""Drive the HomeTruth pages in headless Chrome over the DevTools protocol and save full-resolution screenshots.

Run with the two voice servers up:  .venv/bin/python scripts/ui_screenshots.py 8630 8631 [--prefix qi] [--classic]
Since 2026-10-26 the pages at / wear the qi.home shell (static/qi); --classic shoots the previous pages at /classic instead.
Needs Google Chrome in /Applications and the `websockets` package (in .venv). Output: runs/screenshots/<prefix>_<port>_*.png
Chrome is driven on debugging ports 9343/9344 (prototypes/cardflow/shots.py uses 9333, so both can run at the same time).
Steps wait for things on the page (a question chip, a source row, a card, a highlighted line) instead of fixed sleeps, so the
shots line up with the same moments however long the speech takes. One shot catches a card leaving the wall: for that shot
only, the card's flight is slowed down (window.__slow) so it can be seen mid-air; everything else runs at normal speed."""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", "screenshots")
NEED_PART = "Two bedrooms near Central, I have a cat, and I'd like air con in the bedroom."
ANSWER = "Under 900, mid-November."
NEED_FULL = "Two bedrooms near Central, under 900 a week, I have a cat, moving mid November"
QUESTION = "Is the first one close to the station?"
AGENT = "The agent said the split system is in the living room only."

async def run(url, prefix, port, steps):
    prof = tempfile.mkdtemp(prefix="cdp-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", "--window-size=1440,900", f"--user-data-dir={prof}",
                             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required",
                             "--disable-features=TranslateUI", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    targets = None
    for _ in range(100):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)); break
        except Exception:
            time.sleep(0.2)
    assert targets, "chrome did not come up"
    page = next(t for t in targets if t["type"] == "page")
    try:
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            mid = 0
            async def call(method, **params):
                nonlocal mid
                mid += 1
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == mid:
                        return msg.get("result", msg)
            async def js(expr):
                r = await call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value", r)
            async def shot(name):
                r = await call("Page.captureScreenshot", format="png")
                path = f"{OUT}/{prefix}_{name}.png"
                open(path, "wb").write(base64.b64decode(r["data"]))
                print("  saved", path, flush=True)
            await call("Page.enable"); await call("Runtime.enable")
            await call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=2, mobile=False)
            await call("Page.navigate", url=url)
            await asyncio.sleep(3)
            t0 = time.time()
            for kind, arg in steps:
                if kind == "js":
                    print(f"  +{time.time()-t0:5.1f}s js ->", await js(arg), flush=True)
                elif kind == "wait":  # (condition expression, timeout s)
                    cond, timeout = arg
                    got = await js(WAIT.replace("__COND__", cond).replace("__MS__", str(int(timeout * 1000))))
                    print(f"  +{time.time()-t0:5.1f}s wait {cond[:60]!r} -> {got}", flush=True)
                elif kind == "sleep":
                    await asyncio.sleep(arg)
                elif kind == "shot":
                    print(f"  +{time.time()-t0:5.1f}s shot {arg}", flush=True)
                    await shot(arg)
    finally:
        proc.terminate()

WAIT = ("new Promise(res => { const t0 = Date.now(); const f = () => { let ok = false; try { ok = !!(__COND__); } catch (e) {}"
        " if (ok) res('after ' + (Date.now() - t0) + ' ms'); else if (Date.now() - t0 > __MS__) res('TIMED OUT'); else setTimeout(f, 50); }; f(); })")

def send(text):  # type into the box and submit, like a person pressing Enter (while it is talking this is an interruption)
    return ("(() => { const i = document.querySelector('#text'); const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;"
            f" s.call(i, {json.dumps(text)}); i.dispatchEvent(new Event('input', {{bubbles: true}})); document.querySelector('#composer').requestSubmit(); return 'sent'; }})()")

SLOW_FLIGHT = ("(() => { const orig = Element.prototype.animate; Element.prototype.animate = function (k, o) { const a = orig.call(this, k, o);"
               " if (this.classList && this.classList.contains('fgcard') && window.__slow) a.playbackRate = window.__slow; return a; };"
               " window.__slow = 0.1; return 'card flights slowed 10x'; })()")
CARDS = "document.querySelectorAll('.fgcard').length"
DETAIL_OPEN = "document.querySelector('#detail-dialog').open && document.querySelector('#detail-dialog .listing-photo-main img')"
OPEN_MAIN_DETAIL = "(() => { document.querySelector('.result-main .result-photo-button').click(); return 'detail of the card out front'; })()"
OPEN_GRID_DETAIL = "(() => { document.querySelector('.property-card .property-image-button').click(); return 'detail from the grid'; })()"
CLOSE_DETAIL = "(() => { const b = document.querySelector('#detail-dialog .listing-back'); if (b) b.click(); return 'closed'; })()"
OPEN_REAL_DETAIL = "(() => { const b = document.querySelector('.property-card[data-home-id=\"L-D17153470\"] .property-image-button') || document.querySelector('.property-card[data-home-id^=\"L-D\"] .property-image-button'); if (b) b.click(); return b ? 'detail of a real listing' : 'no real listing card'; })()"  # a Domain sample (scripts/domain_sample.py): Botany Street first (it has a facing and a floor plan, so the sun figure has its wedge)
SCROLL_SUN = "(() => { const s = document.querySelector('#listing-sun'); if (s) s.scrollIntoView({behavior: 'instant', block: 'start'}); return s ? 'at the sun figure' : 'no sun section'; })()"
SCROLL_EXPLORE = "(() => { document.querySelector('#explore').scrollIntoView({behavior: 'instant', block: 'start'}); return 'at the grid'; })()"
SCROLL_TOP = "(() => { window.scrollTo({top: 0, behavior: 'instant'}); return 'top'; })()"
GRID_REVEALED = "[...document.querySelectorAll('.property-card')].some((c) => getComputedStyle(c).opacity === '1')"
SCROLL_CHECK = "(() => { const s = document.querySelector('#listing-check'); if (s) s.scrollIntoView({behavior: 'instant', block: 'start'}); return s ? 'at the checked lines' : 'no check section'; })()"
SCROLL_SOURCES = "(() => { const s = document.querySelector('#listing-features'); if (s) s.scrollIntoView({behavior: 'instant', block: 'start'}); return s ? 'at what the sources say' : 'no sources section'; })()"  # the grouped evidence cards (10-26)
OPEN_FILTERS = "(() => { document.querySelector('#filters-open').click(); return 'filters'; })()"
LIT_WITH_EVIDENCE = "document.querySelector('.fgcard.active .row.lit') && document.querySelectorAll('#evidence li:not(.ev-none)').length > 0"
PHOTO_ROW_LIT = "document.querySelector('.result-main .row[data-dim=\"C2\"].lit') && document.querySelector('#evidence .ev-photo img')"  # the photo-facts line, read by Nemotron VL
WELCOME_SHOWN = "document.querySelector('#welcome-back') && document.querySelector('.criterion-chip.need.remembered')"  # memory: "Welcome back…" + last time's chips
RELOAD = "(() => { location.reload(); return 'reloading'; })()"
# Dot-style state (10-26): a reply that arrives while the renter is away (POST /api/inbox = what scripts/agent_reply.py sends) shows in the welcome box and is folded in on "Same again"
INBOX_POST = "fetch('/api/inbox', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({renter: localStorage.getItem('ht_renter'), listing_id: 'L-0001', text: 'Hi, just confirming: the split system is in the living room only, not in the bedroom.', channel: 'email'})}).then(r => 'inbox ' + r.status)"
AWAY_FOLDED = "[...document.querySelectorAll('#changes li')].some(li => /while you were away/i.test(li.textContent))"  # the Changes panel row for the inbox reply (the spoken line may be reworded by the narrator)
SAME_AGAIN = "document.querySelector('#welcome-back [data-act=same]').click(); 'same again'"
WELCOME_SPOKEN = "/welcome|back|last time/i.test(((document.querySelector('#caption') || {}).textContent || '') + ' ' + ((document.querySelector('#conversation') || {}).innerText || ''))"  # the bot's own welcome line, spoken before the renter says anything

async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    classic = "--classic" in sys.argv
    prefix = sys.argv[sys.argv.index("--prefix") + 1] if "--prefix" in sys.argv else ("v3" if classic else "qi")
    args = [a for a in args if a != prefix]
    page = "/classic" if classic else "/"
    which = args or ["8631", "8630"]
    if "8630" in which:
        print("== 8630 (browser version) ==", flush=True)
        await run("http://127.0.0.1:8630" + page, f"{prefix}_8630", 9344, [
            ("js", "fetch('/api/reset', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session: HT.S.session})}).then(r => 'reset ' + r.status)"),
            ("shot", "00_home"),
            ("js", send(NEED_PART)), ("wait", ("document.querySelector('.need.asking')", 20)), ("sleep", 2.5), ("shot", "01_ask"),
            ("js", SLOW_FLIGHT), ("js", send(ANSWER)), ("wait", ("document.querySelectorAll('#sources li.done').length >= 2", 40)), ("sleep", 0.6), ("shot", "02_analysing"),
            ("wait", (CARDS + " >= 1", 40)), ("sleep", 0.6), ("shot", "03_lifting"), ("js", "window.__slow = 0; 'normal speed'"),
            ("wait", (LIT_WITH_EVIDENCE, 40)), ("sleep", 1.2), ("shot", "04_intro_evidence"),
            ("wait", (PHOTO_ROW_LIT, 90)), ("sleep", 1.0), ("shot", "04b_photo_facts"),
            ("wait", (CARDS + " >= 2", 90)), ("wait", (LIT_WITH_EVIDENCE, 40)), ("sleep", 6), ("shot", "05_second_card"),
            ("js", send(QUESTION)), ("sleep", 3), ("shot", "06_interrupt_answer"),
            ("wait", (CARDS + " >= 3", 120)), ("sleep", 8), ("shot", "07_third_card"),
            ("js", send(AGENT)), ("wait", ("document.querySelectorAll('#changes li').length >= 1", 20)), ("sleep", 2), ("shot", "08_agent_reply"),
            ("js", OPEN_MAIN_DETAIL), ("wait", (DETAIL_OPEN, 10)), ("sleep", 1.6), ("shot", "09_detail_top"), ("js", SCROLL_CHECK), ("sleep", 0.8), ("shot", "09b_detail_checked"), ("js", SCROLL_SOURCES), ("sleep", 0.8), ("shot", "09c_detail_sources"),
            ("js", CLOSE_DETAIL), ("sleep", 1.2), ("js", SCROLL_EXPLORE), ("wait", (GRID_REVEALED, 10)), ("sleep", 2.2), ("shot", "10_explore"),
            ("js", OPEN_GRID_DETAIL), ("wait", (DETAIL_OPEN, 10)), ("sleep", 1.6), ("js", SCROLL_CHECK), ("sleep", 0.8), ("shot", "11_detail_grid"),
            # a real listing (Domain sample): its own photos with provenance, the sun figure, floor-plan / photo rows with confidence
            ("js", CLOSE_DETAIL), ("sleep", 1), ("js", OPEN_REAL_DETAIL), ("wait", (DETAIL_OPEN, 10)), ("sleep", 1.6), ("shot", "11b_real_detail"),
            ("js", SCROLL_SUN), ("sleep", 1.4), ("shot", "11c_real_sun"), ("js", SCROLL_SOURCES), ("sleep", 0.8), ("shot", "11d_real_sources"),
            ("js", CLOSE_DETAIL), ("sleep", 1), ("js", SCROLL_TOP), ("sleep", 0.8), ("js", OPEN_FILTERS), ("wait", ("document.querySelector('#filters-dialog').open", 5)), ("sleep", 0.8), ("shot", "12_filters"),
            # come back later: the page remembers this renter (localStorage id → runs/memory) and opens with "Welcome back…"
            ("js", INBOX_POST), ("sleep", 0.5),  # …and meanwhile an agent replied by email (inbox.py)
            ("js", RELOAD), ("sleep", 3), ("wait", (WELCOME_SHOWN, 15)), ("sleep", 1.5), ("shot", "13_welcome_back"),
            ("js", SAME_AGAIN), ("wait", (AWAY_FOLDED, 60)), ("sleep", 2.5), ("shot", "14_away_folded"),
            ("js", "fetch('/api/forget', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({renter: HT.S.renter})}).then(r => 'forgot ' + r.status)"),
        ])
    if "8631" in which:
        print("== 8631 (Pipecat) ==", flush=True)
        await run("http://127.0.0.1:8631" + page, f"{prefix}_8631", 9343, [
            ("shot", "00_home"),
            ("js", "document.querySelector('#connect').click(); 'clicked Start'"),
            ("wait", ("document.querySelector('#conn').dataset.state === 'live'", 30)), ("sleep", 1), ("shot", "01_connected"),
            ("js", send(NEED_FULL)), ("wait", ("document.querySelectorAll('#sources li.done').length >= 2", 40)), ("sleep", 0.5), ("shot", "02_analysing"),
            ("wait", (LIT_WITH_EVIDENCE, 60)), ("sleep", 1), ("shot", "03_intro_evidence"),
            ("wait", (CARDS + " >= 2", 90)), ("wait", (LIT_WITH_EVIDENCE, 40)), ("sleep", 5), ("shot", "04_second_card"),
            ("js", SCROLL_EXPLORE), ("wait", (GRID_REVEALED, 10)), ("sleep", 2.2), ("shot", "05_explore"),
            ("js", OPEN_REAL_DETAIL), ("wait", (DETAIL_OPEN, 10)), ("sleep", 1.6), ("js", SCROLL_SUN), ("sleep", 1.4), ("shot", "05b_real_sun"), ("js", CLOSE_DETAIL), ("sleep", 1),
            ("js", "document.querySelector('#leave').click(); 'leave'"), ("sleep", 1),
            ("js", INBOX_POST), ("sleep", 0.5),  # …and meanwhile an agent replied by email (inbox.py): the welcome line mentions it, "Same again" folds it in
            ("js", RELOAD), ("sleep", 3), ("wait", (WELCOME_SHOWN, 15)), ("js", "window.scrollTo(0, 0); 'top'"), ("sleep", 1.5), ("shot", "06_welcome_back"),  # a reload keeps the explore scroll position
            # the bot speaks first on the second visit: Start again, then wait for the welcome line (narrator may reword it; it must keep welcome/back/last time)
            ("js", "document.querySelector('#connect').click(); 'clicked Start again'"),
            ("wait", ("document.querySelector('#conn').dataset.state === 'live'", 30)),
            ("wait", (WELCOME_SPOKEN, 40)), ("sleep", 1.5), ("shot", "07_welcome_spoken"),
            ("js", SAME_AGAIN), ("wait", (AWAY_FOLDED, 60)), ("sleep", 2.5), ("shot", "08_away_folded"),
            ("js", "document.querySelector('#leave').click(); 'leave'"), ("sleep", 1),
            ("js", "fetch('/api/forget', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({renter: localStorage.getItem('ht_renter')})}).then(r => 'forgot ' + r.status)"),
        ])

asyncio.run(main())
