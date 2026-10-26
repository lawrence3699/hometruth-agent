# Interaction checks for prototypes/cardflow in headless Chrome: real wheel / key / click events, PASS or FAIL per check.
# Needs the page on 8640. Run: .venv/bin/python prototypes/cardflow/check.py
import asyncio, json, subprocess, tempfile, time, urllib.request
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9334
BASE = "http://127.0.0.1:8640/?t="
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


async def main():
    prof = tempfile.mkdtemp(prefix="cdp-cf-test-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--window-size=1440,900",
                             f"--user-data-dir={prof}", "--no-first-run", "--hide-scrollbars", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2)); break
            except Exception:
                time.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
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
                return r.get("result", {}).get("value")

            async def until(cond, timeout=20):
                t0 = time.time()
                while time.time() - t0 < timeout:
                    if await js(f"typeof S !== 'undefined' && !!({cond})"):
                        return True
                    await asyncio.sleep(0.1)
                return False

            async def wheel(dy, n=1, x=400, y=450):
                for _ in range(n):
                    await call("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=0, deltaY=dy)
                    await asyncio.sleep(0.05)

            async def key(k, code):
                await call("Input.dispatchKeyEvent", type="keyDown", key=k, code=k, windowsVirtualKeyCode=code)
                await call("Input.dispatchKeyEvent", type="keyUp", key=k, code=k, windowsVirtualKeyCode=code)

            async def fresh(tag):
                await call("Page.navigate", url=BASE + tag)
                await until("document.body.classList.contains('ready')", 10)
                await asyncio.sleep(0.3)

            await call("Page.enable"); await call("Runtime.enable")
            await call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)

            # T1 all five must-haves in one sentence: no follow-up question, straight to the tour
            await fresh("t1")
            await js("handleInput('Two bedrooms near Central under 900, mid-November, I have a cat, and air con in the bedroom'), 1")
            ok = await until("S.phase === 'tour' && S.cards.length && !S.cards.some(c => c.flying)", 15)
            picks = await js("S.picks.map(p => p.l.id).join(',')")
            check("one-shot needs -> no question, tour", ok and await js("S.rounds") == 0, picks)
            check("picks are Fenwick, Alder, Ellery", picks == "L-0002,L-0001,L-0031", picks)

            # T2 wheel during the guided tour hands control to the user and snaps to a card
            await until("S.auto === true", 5)
            await asyncio.sleep(1.0)
            await wheel(120, 3)
            await asyncio.sleep(0.4)
            check("wheel cancels guided tour", await js("S.auto") is False)
            await asyncio.sleep(2.2)
            st = await js("({y: scrollY, f: S.f, p: posFor(Math.round(S.f)), focus: S.focus})")
            check("snaps to nearest card", abs(st["y"] - st["p"]) < 3, json.dumps(st))

            # T3 arrow keys step through cards
            f0 = st["focus"]
            await key("ArrowRight", 39)
            ok = await until(f"S.focus === {f0 + 1}", 3)
            await asyncio.sleep(1.2)
            check("ArrowRight -> next card", ok, f"focus {f0} -> {await js('S.focus')}")

            # T4 rail and card clicks
            await js("document.querySelector('#rail button[data-i=\"0\"]').click(), 1")
            check("rail 01 -> first card", await until("S.focus === 0 && Math.abs(scrollY) < 3", 4))
            await asyncio.sleep(0.5)
            await js("S.cards.find(c => c.target === 2).el.click(), 1")
            check("click side card -> third card", await until("S.focus === 2", 4))
            await asyncio.sleep(1.2)

            # T5 scroll on to the compare section: stage fades, dock tucks away; back up restores
            await wheel(400, 12)
            ok = await until("document.body.classList.contains('in-compare')", 4)
            await asyncio.sleep(1.5)
            op = await js("+getComputedStyle(document.querySelector('.stage')).opacity")
            check("compare section takes over", ok and op < 0.15, f"stage opacity {op}")
            check("compare rows revealed", await until("document.querySelector('.cmp').classList.contains('in')", 3))
            await wheel(-400, 14)
            check("scroll back up restores dock", await until("!document.body.classList.contains('in-compare')", 4))
            await asyncio.sleep(1.5)

            # T6 a question about one listing
            await js("handleInput('Is the first one close to the station?'), 1")
            await asyncio.sleep(0.6)
            ok = await until("S.focus === 0 && /minutes to Central/.test(document.querySelector('#aiText').textContent)", 6)
            check("commute question answered on card 1", ok, await js("document.querySelector('#aiText').textContent"))

            # T7 changing a need re-runs the search
            await js("handleInput('Actually under 800 instead'), 1")
            ok = await until("S.phase === 'search'", 4)
            ok2 = await until("S.phase === 'tour' && S.cards.length && !S.cards.some(c => c.flying)", 15)
            rents = await js("S.picks.map(p => p.l.rent)")
            check("new budget -> re-scan and new picks", ok and ok2 and await js("S.needs.A1") == 800 and all(r <= 800 for r in rents), f"rents {rents}")

            # T8 Chinese input
            await fresh("t8")
            await js("handleInput('两房，中央车站附近，预算900以内，11月中入住，有猫'), 1")
            ok = await until("S.phase === 'tour'", 12)
            n = await js("({A1: S.needs.A1, B1: S.needs.B1, G1: S.needs.G1 && S.needs.G1.hub, A4: S.needs.A4 && S.needs.A4.date, J1: S.needs.J1, rounds: S.rounds})")
            check("Chinese needs parsed, no question", ok and n["rounds"] == 0, json.dumps(n, ensure_ascii=False))

            # T9 partial needs: asks at most two, then the answers fill them
            await fresh("t9")
            await js("handleInput('One bedroom near UNSW'), 1")
            await until("S.phase === 'asking' && !S.speaking", 10)
            asked = await js("S.asked")
            check("asks the first two missing must-haves", asked == ["A1", "A4"], json.dumps(asked))
            await js("handleInput('700, early December'), 1")
            await until("S.phase === 'asking' && !S.speaking", 10)
            asked2 = await js("S.asked")
            check("second round asks what is left", asked2 == ["J1"], json.dumps(asked2))
            await js("handleInput('no pets'), 1")
            check("third answer starts the search", await until("S.phase === 'search' || S.phase === 'tour' || S.phase === 'idle'", 6))
            await until("S.phase !== 'search'", 12)

            # T10 nothing fits
            await fresh("t10")
            await js("handleInput('Studio near the CBD under 400, mid November, no pets'), 1")
            ok = await until("S.phase === 'idle' && /Nothing in the fifty/.test(document.querySelector('#aiText').textContent)", 12)
            check("no-fit case explained", ok, await js("document.querySelector('#aiText').textContent"))

            errs = await js("JSON.stringify(window.__errors)")
            check("no page errors", errs == "[]", errs)
    finally:
        proc.terminate()
    print(f"\n{sum(results)}/{len(results)} PASS")

asyncio.run(main())
