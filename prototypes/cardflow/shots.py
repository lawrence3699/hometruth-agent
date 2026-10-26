# -*- coding: utf-8 -*-
"""Run the card-flow demo in headless Chrome and save screenshots at fixed moments, plus an optional video.

Needs the page served on 8640 (python3 -m http.server 8640 --directory prototypes/cardflow),
Google Chrome in /Applications, `websockets` (in .venv) and ffmpeg for the video.
    .venv/bin/python prototypes/cardflow/shots.py            # screenshots only
    .venv/bin/python prototypes/cardflow/shots.py --video    # also runs/screenshots/cardflow_demo.mp4
Output: runs/screenshots/cardflow_<nn>_<name>.png (1440 x 900 at 2x)."""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "runs", "screenshots")
URL = "http://127.0.0.1:8640/?shots=1#demo"
PORT = 9333

# (name, condition polled in the page, extra wait in seconds after it holds)
STEPS = [
    ("idle", "document.body.classList.contains('ready') && S.phase === 'idle'", 1.4),
    ("ask", "S.phase === 'asking' && !S.speaking", 0.2),
    ("scan", "S.phase === 'search'", 2.2),
    ("tally", "S.phase === 'search' && $('#tBest').textContent !== '–'", 0.5),
    ("fly", "S.cards.length > 0 && S.cards.some(c => c.flying)", 0.5),
    ("pick1", "S.focus === 0 && S.cards.length && !S.cards.some(c => c.flying)", 2.2),
    ("turning", "S.f > 0.3 && S.f < 0.7", 0.0),
    ("pick2_cat", "S.focus === 1 && $('#detail [data-cell=\"J1\"].hot') !== null", 0.4),
    ("agent_flip", "S.log.length > 0", 0.6),
    ("reranked", "S.agentDone === true", 0.8),
    ("compare_slide", "!S.demo", 0.0),
]


async def main(video):
    os.makedirs(OUT, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="cdp-cardflow-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", "--window-size=1440,900",
                             f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames_dir = tempfile.mkdtemp(prefix="cardflow-frames-")
    frames = []
    try:
        targets = None
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
                break
            except Exception:
                time.sleep(0.2)
        assert targets, "chrome did not come up"
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            mid = 0
            pending = {}

            async def reader():
                while True:
                    msg = json.loads(await ws.recv())
                    if "id" in msg and msg["id"] in pending:
                        pending.pop(msg["id"]).set_result(msg.get("result", msg))
                    elif msg.get("method") == "Page.screencastFrame":
                        p = msg["params"]
                        path = os.path.join(frames_dir, f"{len(frames):05d}.jpg")
                        open(path, "wb").write(base64.b64decode(p["data"]))
                        frames.append((p["metadata"]["timestamp"], path))
                        asyncio.create_task(call("Page.screencastFrameAck", sessionId=p["sessionId"]))

            async def call(method, **params):
                nonlocal mid
                mid += 1
                fut = asyncio.get_event_loop().create_future()
                pending[mid] = fut
                await ws.send(json.dumps({"id": mid, "method": method, "params": params}))
                return await fut

            async def js(expr):
                r = await call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
                return r.get("result", {}).get("value")

            async def shot(name, k):
                r = await call("Page.captureScreenshot", format="png")
                path = f"{OUT}/cardflow_{k:02d}_{name}.png"
                open(path, "wb").write(base64.b64decode(r["data"]))
                print(f"  saved {path}", flush=True)

            task = asyncio.create_task(reader())
            await call("Page.enable")
            await call("Runtime.enable")
            await call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=2, mobile=False)
            if video:
                await call("Page.startScreencast", format="jpeg", quality=82, maxWidth=1440, maxHeight=900, everyNthFrame=1)
            await call("Page.navigate", url=URL)
            t0 = time.time()
            k = 0
            for name, cond, extra in STEPS:
                deadline = time.time() + 150
                while time.time() < deadline:
                    try:
                        if await js(f"typeof S !== 'undefined' && !!({cond})"):
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)
                else:
                    print(f"  timeout waiting for {name}", flush=True)
                    continue
                await asyncio.sleep(extra)
                k += 1
                print(f"  +{time.time() - t0:5.1f}s {name}", flush=True)
                if name == "compare_slide":
                    await asyncio.sleep(1.5)
                    await js("smoothTo($('#compare').offsetTop - innerHeight * 0.45), 1")
                    await asyncio.sleep(1.6)
                    await shot(name, k)
                    await js("smoothTo($('#compare').offsetTop), 1")
                    await asyncio.sleep(2.4)
                    k += 1
                    await shot("compare", k)
                    await js("smoothTo($('#compare').offsetTop + innerHeight * 0.75), 1")
                    await asyncio.sleep(2.4)
                    k += 1
                    await shot("questions", k)
                else:
                    await shot(name, k)
            if video:
                await asyncio.sleep(0.5)
                await call("Page.stopScreencast")
            errors = await js("JSON.stringify(window.__errors || [])")
            print("  page errors:", errors)
            task.cancel()
    finally:
        proc.terminate()
    if video and frames:
        lst = os.path.join(frames_dir, "list.txt")
        with open(lst, "w") as f:
            for i, (ts, path) in enumerate(frames):
                dur = (frames[i + 1][0] - ts) if i + 1 < len(frames) else 0.04
                f.write(f"file '{path}'\nduration {max(dur, 0.001):.4f}\n")
        out = os.path.join(OUT, "cardflow_demo.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", "fps=30,scale=1440:-2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "20", out], check=True)
        print(f"  video {out} ({len(frames)} frames, {frames[-1][0] - frames[0][0]:.1f}s)")
    shutil.rmtree(frames_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main("--video" in sys.argv))
