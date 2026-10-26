#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shoot the dollhouse test page (static/qi/dollhouse-test.html) in headless Chrome over the DevTools protocol, one listing at a time:
orbit (default view), room (camera flown to the first inside room, photo strip below) and sun (21 June, 3 pm, shadows on the floor).
WebGL in headless Chrome needs the SwiftShader flags below. Console errors are collected and printed; the script exits 1 if any appear.

Run with a voice server up:  VOICE_PORT=8638 TTS_BACKEND=say .venv/bin/python src/voice/server.py
                             .venv/bin/python scripts/dollhouse_shots.py --port 8638 [--listing L-D17153470 ...]
Output: runs/screenshots/dollhouse_<DomainId>_{orbit,room,sun}.png (1280 × 900, 2× device scale)."""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs", "screenshots")
DEFAULT = ["L-D17153470", "L-D17129985", "L-D17796276"]
WAIT = ("new Promise(res => { const t0 = Date.now(); const f = () => { let ok = false; try { ok = !!(__COND__); } catch (e) {}"
        " if (ok) res('after ' + (Date.now() - t0) + ' ms'); else if (Date.now() - t0 > __MS__) res('TIMED OUT'); else setTimeout(f, 50); }; f(); })")


async def shoot(base: str, listings, port: int) -> int:
    prof = tempfile.mkdtemp(prefix="cdp-dollhouse-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", "--window-size=1280,900", f"--user-data-dir={prof}",
                             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--use-gl=angle", "--use-angle=swiftshader",
                             "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-features=TranslateUI", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    targets = None
    for _ in range(100):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2))
            break
        except Exception:
            time.sleep(0.2)
    assert targets, "chrome did not come up"
    page = next(t for t in targets if t["type"] == "page")
    errors = []
    os.makedirs(OUT, exist_ok=True)
    try:
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            mid = 0
            pending = {}

            async def recv_until(target_id):
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == target_id:
                        return msg.get("result", msg)
                    m = msg.get("method")
                    if m == "Runtime.exceptionThrown":
                        d = msg["params"]["exceptionDetails"]
                        errors.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:300])
                    elif m == "Runtime.consoleAPICalled" and msg["params"].get("type") in ("error", "warning"):
                        errors.append(msg["params"]["type"] + ": " + " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"]["args"])[:300])
                    elif m == "Log.entryAdded" and msg["params"]["entry"].get("level") in ("error", "warning"):
                        e = msg["params"]["entry"]
                        errors.append(f"log {e.get('level')}: {e.get('text', '')[:200]} {e.get('url', '')}")

            async def call(method, **params):
                nonlocal mid
                mid += 1
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                return await recv_until(mid)

            async def js(expr):
                r = await call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value", r)

            async def wait(cond, timeout=30.0):
                return await js(WAIT.replace("__COND__", cond).replace("__MS__", str(int(timeout * 1000))))

            async def shot(name):
                r = await call("Page.captureScreenshot", format="png")
                path = f"{OUT}/{name}.png"
                open(path, "wb").write(base64.b64decode(r["data"]))
                print("  saved", path, flush=True)

            await call("Page.enable")
            await call("Runtime.enable")
            await call("Log.enable")
            await call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=2, mobile=False)
            for lid in listings:
                did = lid.split("D", 1)[-1]
                print(f"{lid}:", flush=True)
                await call("Page.navigate", url=f"{base}/static/qi/dollhouse-test.html?listing={lid}")
                print("  ready:", await wait("window.__dollhouse_ready === true || window.__dollhouse_ready === false", 40), flush=True)
                ok = await js("window.__dollhouse_ready === true")
                if not ok:
                    print("  not mounted:", await js("window.__dollhouse_error || document.getElementById('meta').textContent"), flush=True)
                    errors.append(f"{lid}: dollhouse not mounted")
                    continue
                print("  frames:", await wait("window.__dollhouse.frames() > 20", 20), flush=True)
                print("  gl:", await js("(() => { const gl = document.querySelector('canvas.ht-dollhouse-canvas').getContext('webgl2'); return gl ? gl.getParameter(gl.RENDERER) : 'none'; })()"), flush=True)
                await js("window.__dollhouse.pause(); window.__dollhouse.resetView(); 'ok'")
                await asyncio.sleep(1.5)
                await shot(f"dollhouse_{did}_orbit")
                first = await js("(window.__dollhouse.plan.rooms.find(r => r.inside && r.type !== 'balcony') || window.__dollhouse.plan.rooms[0]).id")
                await js(f"window.__dollhouse.focusRoom({first}); 'ok'")
                await asyncio.sleep(1.8)
                await shot(f"dollhouse_{did}_room")
                await js("window.__dollhouse.resetView(); window.__dollhouse.pause(); window.__dollhouse.setSun('winter', 15); 'ok'")
                await asyncio.sleep(1.5)
                await shot(f"dollhouse_{did}_sun")
    finally:
        proc.terminate()
    if errors:
        print("console / page errors:")
        for e in errors:
            print("  ", e)
        return 1
    print("console clean")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8638, help="voice server port")
    ap.add_argument("--base", help="server base URL (default http://127.0.0.1:<port>)")
    ap.add_argument("--listing", nargs="*", default=DEFAULT)
    ap.add_argument("--cdp-port", type=int, default=9347)
    a = ap.parse_args()
    return asyncio.run(shoot(a.base or f"http://127.0.0.1:{a.port}", a.listing, a.cdp_port))


if __name__ == "__main__":
    sys.exit(main())
