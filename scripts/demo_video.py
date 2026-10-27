# -*- coding: utf-8 -*-
"""Record the HomeTruth demo for the hackathon video: drive the page in headless Chrome like a person (a visible cursor, typing
letter by letter), and keep two things on one clock: the screencast frames and the speech the page itself plays.

  record   .venv/bin/python scripts/demo_video.py record --base http://127.0.0.1:8660 --out runs/video/take1
  assemble .venv/bin/python scripts/demo_video.py assemble runs/video/take1      → raw.mp4 (30 fps) + app_audio.wav + marks.json

The page speaks through Web Audio (app.js player), so an init script wraps AudioBufferSourceNode.start / stop and remembers each
buffer, when it started, from which offset and when it was cut (interruptions). After the run the buffers are read back and laid on a
silent track at those times: the sound in the video is exactly what a person in the room would have heard.
Frames: Page.startScreencast only delivers frames at the CSS size (1280×720, it ignores the 1.5× device scale), so frames are taken
with Page.captureScreenshot in a loop instead (1920×1080 JPEG q88, about 15–20 a second, each stamped with the middle of its capture);
assemble holds each frame until the next one (variable → constant 30 fps). Marks (scene names) are written at the moment the step runs.
The edit (cuts, captions, narration, title cards) is scripts/demo_video_edit.py; this file only records.
Chrome debugging port 9346 (ui_screenshots.py uses 9343/9344, cardflow 9333)."""
import asyncio, base64, json, math, os, random, subprocess, sys, tempfile, time, urllib.request, wave
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, SCALE = 1280, 720, 1.5
SR = 48000

NEED = "Two bedrooms near UNSW, I have a cat, and I'd like air con in the bedroom."
ANSWER = "Under 900, mid-November."
QUESTION = "Is the first one close to UNSW?"
REPLY = "The agent at Alder Lane says no pets in that building, sorry."  # pets is a must-have here: the cell flips to conflict and the place drops out of the top three

# Wraps Web Audio playback (what the page says), draws a cursor that follows the real mouse events, and a click ripple.
# The cursor is a manual popover so it can be lifted above an open <dialog> (top layer): __curTop() re-shows it last.
INIT = r"""
(() => {
  window.__aud = [];
  const P = AudioBufferSourceNode.prototype, oStart = P.start, oStop = P.stop;
  const now = () => performance.timeOrigin + performance.now();
  P.start = function (when, offset) {
    const rec = { t: now(), offset: offset || 0, buf: this.buffer, stop: null, end: null, text: ((document.querySelector('#caption') || {}).textContent || '').slice(0, 200) };
    window.__aud.push(rec); this.__rec = rec;
    this.addEventListener('ended', () => { if (rec.end == null) rec.end = now(); });
    return oStart.apply(this, arguments);
  };
  P.stop = function () { if (this.__rec && this.__rec.stop == null) this.__rec.stop = now(); return oStop.apply(this, arguments); };
  window.__said = [];
  if (window.speechSynthesis) { const os = speechSynthesis.speak.bind(speechSynthesis); speechSynthesis.speak = (u) => { window.__said.push({ t: now(), text: u.text }); return os(u); }; }
  const put = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur'; c.setAttribute('popover', 'manual');
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M5 2.5l13.5 9.2-6.2 1.3 3.6 7.1-2.7 1.3-3.5-7.2L5 18.6z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    c.style.cssText = 'position:fixed;inset:auto;left:0;top:0;margin:0;padding:0;border:0;background:transparent;overflow:visible;pointer-events:none;width:26px;height:26px;transform:translate(-80px,-80px);z-index:2147483647';
    document.documentElement.appendChild(c); try { c.showPopover(); } catch (e) {}
    window.__curTop = () => { try { c.hidePopover(); c.showPopover(); } catch (e) {} return 'cursor on top'; };
    addEventListener('mousemove', (e) => { c.style.transform = `translate(${e.clientX - 4}px,${e.clientY - 2}px)`; }, true);
    addEventListener('mousedown', (e) => {
      const r = document.createElement('div'); r.setAttribute('popover', 'manual');
      r.style.cssText = `position:fixed;inset:auto;margin:0;padding:0;border:0;left:${e.clientX - 16}px;top:${e.clientY - 16}px;width:32px;height:32px;border-radius:50%;background:rgba(35,131,226,.32);pointer-events:none;transition:transform .5s ease,opacity .5s ease`;
      document.documentElement.appendChild(r); try { r.showPopover(); } catch (er) {} window.__curTop();
      requestAnimationFrame(() => requestAnimationFrame(() => { r.style.transform = 'scale(1.9)'; r.style.opacity = '0'; }));
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', put); else put();
})();
"""

WAIT = ("new Promise(res => { const t0 = Date.now(); const f = () => { let ok = false; try { ok = !!(__COND__); } catch (e) {}"
        " if (ok) res('after ' + (Date.now() - t0) + ' ms'); else if (Date.now() - t0 > __MS__) res('TIMED OUT'); else setTimeout(f, 60); }; f(); })")
QUIET = "(window.HT && !HT.S.playing && !HT.S.streamOpen)"  # nothing being said and no turn streaming
CAPTION = "((document.querySelector('#caption') || {}).textContent || '')"


class CDP:
    def __init__(self, ws):
        self.ws, self.mid, self.pending, self.handlers = ws, 0, {}, {}

    async def reader(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self.pending.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg)
            elif msg.get("method") in self.handlers:
                self.handlers[msg["method"]](msg.get("params", {}))

    async def call(self, method, **params):
        self.mid += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.mid] = fut
        await self.ws.send(json.dumps({"id": self.mid, "method": method, "params": params}))
        msg = await fut
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            return "JS ERROR " + json.dumps(r["exceptionDetails"])[:300]
        return r.get("result", {}).get("value")


class Driver:
    """Person-like input: the mouse glides (eased) and the page's own cursor follows the real mouse events."""

    def __init__(self, cdp, out, lock=None):
        self.cdp, self.out, self.x, self.y = cdp, out, W * 0.62, H * 0.75
        self.lock = lock or asyncio.Lock()  # input events sent while a screenshot is being taken get dropped: the two take turns
        self.marks, self.t0 = [], time.time()

    def log(self, msg):
        print(f"  +{time.time() - self.t0:6.1f}s {msg}", flush=True)

    def mark(self, name):
        self.marks.append({"name": name, "t": time.time()})
        self.log(f"MARK {name}")

    async def move(self, x, y, dur=0.7):
        n = max(8, int(dur * 60))
        x0, y0 = self.x, self.y
        for i in range(1, n + 1):
            k = i / n
            e = k * k * (3 - 2 * k)  # smoothstep
            self.x, self.y = x0 + (x - x0) * e, y0 + (y - y0) * e
            async with self.lock:
                await self.cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=self.x, y=self.y)
            await asyncio.sleep(dur / n)

    async def center(self, sel):
        # the page has scroll-behavior: smooth, so a plain scrollIntoView animates and the rect read right after it is stale
        r = await self.cdp.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) return null;"
                              " e.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'instant'});"
                              " return new Promise(res => requestAnimationFrame(() => requestAnimationFrame(() => { const b = e.getBoundingClientRect();"
                              " res([b.left + b.width / 2, b.top + b.height / 2, b.width, b.height]); }))); })()")
        if not r:
            raise RuntimeError(f"no element {sel}")
        return r

    async def click(self, sel, dur=0.7, settle=0.25):
        x, y, w, h = await self.center(sel)
        await self.move(x + random.uniform(-w, w) * 0.12, y + random.uniform(-h, h) * 0.12, dur)
        await asyncio.sleep(settle)
        async with self.lock:
            for t in ("mousePressed", "mouseReleased"):
                await self.cdp.call("Input.dispatchMouseEvent", type=t, x=self.x, y=self.y, button="left", clickCount=1)
                await asyncio.sleep(0.07)
        await self.cdp.js("window.__curTop && __curTop()")
        ok = await self.cdp.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!(e instanceof HTMLInputElement)) return 'not an input';"
                               " if (document.activeElement === e) return 'focused'; e.focus(); return 'focused by script'; })()")
        if ok == "focused by script":
            self.log(f"click on {sel} missed the focus; focused it by script")

    async def type(self, text, cps=16):
        for ch in text:
            async with self.lock:
                await self.cdp.call("Input.insertText", text=ch)
            await asyncio.sleep(random.uniform(0.6, 1.4) / cps + (0.12 if ch in ",." else 0))

    async def enter(self):
        async with self.lock:
            await self._enter()

    async def _enter(self):
        for t in ("keyDown", "keyUp"):
            await self.cdp.call("Input.dispatchKeyEvent", type=t, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                                nativeVirtualKeyCode=13, **({"text": "\r"} if t == "keyDown" else {}))

    async def key(self, key, code=None, vk=0):
        async with self.lock:
            for t in ("keyDown", "keyUp"):
                await self.cdp.call("Input.dispatchKeyEvent", type=t, key=key, code=code or key, windowsVirtualKeyCode=vk)

    async def wheel(self, dy, dur=1.2):
        n = max(6, int(dur * 30))
        for i in range(n):
            async with self.lock:
                await self.cdp.call("Input.dispatchMouseEvent", type="mouseWheel", x=self.x, y=self.y, deltaX=0, deltaY=dy / n)
            await asyncio.sleep(dur / n)

    async def wait(self, cond, timeout):
        got = await self.cdp.js(WAIT.replace("__COND__", cond).replace("__MS__", str(int(timeout * 1000))))
        self.log(f"wait {cond[:70]!r} -> {got}")
        return got


async def scenario(d):
    """The demo as one take; the edit picks the parts."""
    js = d.cdp.js
    await js("fetch('/api/reset', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session: HT.S.session})}).then(r => r.status)")
    await d.wait("document.querySelector('#text') && document.querySelectorAll('.nt-gcard').length > 0", 30)
    d.mark("home")
    await asyncio.sleep(4)

    d.mark("type_need")
    await d.click("#text", dur=1.0)
    await asyncio.sleep(0.4)
    await d.type(NEED)
    await asyncio.sleep(0.6)
    await d.enter()
    d.mark("need_sent")
    await d.wait(f"/budget/i.test({CAPTION}) && HT.S.playing", 30)  # the question is being said (the caption shows before the audio starts)
    await d.wait(QUIET, 30)
    await asyncio.sleep(0.9)

    d.mark("type_answer")
    await d.type(ANSWER)
    await asyncio.sleep(0.5)
    await d.enter()
    d.mark("answer_sent")
    await d.wait("document.querySelectorAll('#sources li.src').length >= 5", 30)
    d.mark("sources_running")
    await d.wait("document.querySelectorAll('#sources li.src.done').length >= 7", 60)
    d.mark("sources_done")
    await d.move(W * 0.83, H * 0.86, 0.8)  # out of the way of the walkthrough

    await d.wait(f"/^First/i.test({CAPTION})", 60)
    d.mark("card1")
    await d.wait(f"/^Second/i.test({CAPTION})", 240)
    d.mark("card2")
    await asyncio.sleep(5.5)
    d.mark("interrupt")
    await d.click("#text", dur=0.8)
    await d.type(QUESTION)
    await d.enter()
    d.mark("question_sent")
    await d.wait(f"/^Third|last one/i.test({CAPTION})", 300)
    d.mark("card3")
    await d.wait(f"/top three/i.test({CAPTION}) && HT.S.playing", 240)
    d.mark("wrap")
    await d.wait(QUIET, 90)
    await asyncio.sleep(1.0)

    d.mark("type_reply")
    await d.click("#text", dur=0.8)
    await d.type(REPLY)
    await d.enter()
    d.mark("reply_sent")
    await d.wait("+(document.querySelector('#changes-count') || {}).textContent > 0", 40)
    d.mark("changed")
    await d.wait(f"/Noted|conflict/i.test({CAPTION}) && HT.S.playing", 20)
    await d.wait(QUIET, 60)
    await asyncio.sleep(1.5)
    # the database views sit under the callout: bring them up first, or the tab click only scrolls them to the bottom edge
    await js("(() => { const v = document.querySelector('#views'); window.scrollTo({top: v.getBoundingClientRect().top + scrollY - 150, behavior: 'smooth'}); })()")
    await asyncio.sleep(1.4)
    await d.click("#views [data-view=changes]")
    d.mark("view_changes")
    await asyncio.sleep(5.5)
    await d.click("#views [data-view=table]")
    d.mark("view_table")
    await asyncio.sleep(5.5)
    await d.click("#views [data-view=walk]")
    await asyncio.sleep(1.0)
    if await js("!!document.querySelector('#agent-panel:not([hidden]) button[aria-label=\"Minimize conversation\"]')"):
        await d.click('#agent-panel button[aria-label="Minimize conversation"]')  # the gallery needs the whole width
        await asyncio.sleep(0.8)

    d.mark("to_explore")
    await js("document.querySelector('#explore').scrollIntoView({behavior: 'smooth', block: 'start'})")
    await asyncio.sleep(2.5)
    await d.click("#ex-filter [data-f=real]")
    d.mark("real_filter")
    await asyncio.sleep(2.0)
    await d.wheel(380, 1.8)
    await asyncio.sleep(1.2)

    # a real place whose photos carry "this advert has been digitally furnished" (Day Avenue, Domain): Nemotron VL read it
    sel = ".nt-gcard[data-open='L-D14397815']"
    if not await js(f"!!document.querySelector({json.dumps(sel)})"):
        sel = ".nt-gcard[data-open^='L-D']"
    await d.click(sel, dur=0.9)
    d.mark("peek_open")
    await d.wait("document.querySelector('#peek').open", 10)
    await js("window.__curTop && __curTop()")
    await asyncio.sleep(3.5)
    await d.move(W * 0.5, H * 0.6, 0.6)
    for _ in range(5):
        await d.wheel(430, 1.4)
        await asyncio.sleep(1.8)
    d.mark("peek_scrolled")
    await asyncio.sleep(1.5)
    await d.key("Escape", "Escape", 27)
    await asyncio.sleep(1.5)
    d.mark("end")
    await asyncio.sleep(1.0)


async def record(base, out):
    os.makedirs(os.path.join(out, "frames"), exist_ok=True)
    port = 9346
    prof = tempfile.mkdtemp(prefix="cdp-video-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--window-size={W},{H}", f"--user-data-dir={prof}",
                             "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--autoplay-policy=no-user-gesture-required",
                             "--disable-features=TranslateUI", "--force-color-profile=srgb", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    targets = None
    for _ in range(100):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)); break
        except Exception:
            time.sleep(0.2)
    assert targets, "chrome did not come up"
    page = next(t for t in targets if t["type"] == "page")
    frames = open(os.path.join(out, "frames.jsonl"), "w")
    n = [0]
    try:
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            reader = asyncio.create_task(cdp.reader())

            stop, lock = asyncio.Event(), asyncio.Lock()

            async def grab():
                while not stop.is_set():
                    async with lock:
                        t = time.time()
                        r = await cdp.call("Page.captureScreenshot", format="jpeg", quality=88, optimizeForSpeed=True)
                        t1 = time.time()
                    await asyncio.sleep(0)
                    n[0] += 1
                    name = f"{n[0]:06d}.jpg"
                    with open(os.path.join(out, "frames", name), "wb") as f:
                        f.write(base64.b64decode(r["data"]))
                    frames.write(json.dumps({"f": name, "t": (t + t1) / 2}) + "\n")
            await cdp.call("Page.enable"); await cdp.call("Runtime.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=SCALE, mobile=False)
            await cdp.call("Page.addScriptToEvaluateOnNewDocument", source=INIT)
            await cdp.call("Page.navigate", url=base.rstrip("/") + "/")
            await asyncio.sleep(1.5)
            d = Driver(cdp, out, lock)
            grabber = asyncio.create_task(grab())
            d.mark("start")
            try:
                await scenario(d)
            finally:
                stop.set()
                await grabber
                json.dump(d.marks, open(os.path.join(out, "marks.json"), "w"), indent=1)
                await dump_audio(cdp, out)
            reader.cancel()
    finally:
        frames.close()
        proc.terminate()
    print(f"recorded {n[0]} frames → {out}")


async def dump_audio(cdp, out):
    """Read each played buffer back as 16-bit mono at its own rate, with when / from where / until when it played."""
    k = await cdp.js("window.__aud.length") or 0
    clips = []
    os.makedirs(os.path.join(out, "audio"), exist_ok=True)
    for i in range(k):
        meta = await cdp.js(f"(() => {{ const r = __aud[{i}]; return {{t: r.t, offset: r.offset, stop: r.stop, end: r.end, rate: r.buf.sampleRate, dur: r.buf.duration, ch: r.buf.numberOfChannels, text: r.text}}; }})()")
        b64 = await cdp.js(f"(() => {{ const b = __aud[{i}].buf, n = b.length, out = new Int16Array(n), c0 = b.getChannelData(0), c1 = b.numberOfChannels > 1 ? b.getChannelData(1) : null;"
                           " for (let j = 0; j < n; j++) { const v = c1 ? (c0[j] + c1[j]) / 2 : c0[j]; out[j] = Math.max(-1, Math.min(1, v)) * 32767; }"
                           " const u8 = new Uint8Array(out.buffer); let s = ''; for (let j = 0; j < u8.length; j += 32768) s += String.fromCharCode.apply(null, u8.subarray(j, j + 32768)); return btoa(s); })()")
        path = os.path.join(out, "audio", f"{i:03d}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(meta["rate"])); w.writeframes(base64.b64decode(b64))
        meta["wav"] = os.path.basename(path)
        clips.append(meta)
    said = await cdp.js("window.__said") or []
    json.dump({"clips": clips, "browser_voice": said}, open(os.path.join(out, "audio.json"), "w"), indent=1)
    print(f"  {len(clips)} audio clips; browser-voice fallbacks: {len(said)}")


def assemble(out, fps=30):
    """frames.jsonl + audio.json → raw.mp4 (constant fps) and app_audio.wav on the same timeline; marks.json gets seconds."""
    import numpy as np
    rows = [json.loads(l) for l in open(os.path.join(out, "frames.jsonl"))]
    rows = [r for r in rows if r.get("t")]
    rows.sort(key=lambda r: r["t"])
    marks = json.load(open(os.path.join(out, "marks.json")))
    t0 = rows[0]["t"]
    t_end = max(rows[-1]["t"], marks[-1]["t"]) + 0.5
    with open(os.path.join(out, "frames.txt"), "w") as f:
        f.write("ffconcat version 1.0\n")
        for a, b in zip(rows, rows[1:] + [{"t": t_end}]):
            f.write(f"file 'frames/{a['f']}'\nduration {max(0.001, b['t'] - a['t']):.4f}\n")
        f.write(f"file 'frames/{rows[-1]['f']}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "frames.txt", "-vf", f"fps={fps},format=yuv420p",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "15", "raw.mp4"], cwd=out, check=True)
    meta = json.load(open(os.path.join(out, "audio.json")))
    track = np.zeros(int((t_end - t0) * SR) + SR, dtype=np.float64)
    for c in meta["clips"]:
        with wave.open(os.path.join(out, "audio", c["wav"])) as w:
            rate = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32767
        if rate != SR:
            x = np.interp(np.arange(int(len(x) * SR / rate)) * rate / SR, np.arange(len(x)), x)
        x = x[int(c["offset"] * SR):]
        if c.get("stop") and (not c.get("end") or c["stop"] < c["end"]):
            x = x[:max(0, int((c["stop"] - c["t"]) / 1000 * SR))]
        s = int((c["t"] / 1000 - t0) * SR)
        if s < 0:
            x, s = x[-s:], 0
        track[s:s + len(x)] += x[:len(track) - s]
    track = np.clip(track, -1, 1)
    with wave.open(os.path.join(out, "app_audio.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((track * 32767).astype(np.int16).tobytes())
    secs = [{"name": m["name"], "s": round(m["t"] - t0, 2)} for m in marks]
    json.dump(secs, open(os.path.join(out, "marks_s.json"), "w"), indent=1)
    said = []  # each sentence the page played, on the video's clock (cut = stopped early by an interruption)
    for c in meta["clips"]:
        s = c["t"] / 1000 - t0
        e = (min(c["stop"], c["end"] or c["stop"]) if c.get("stop") else (c.get("end") or c["t"] + (c["dur"] - c["offset"]) * 1000)) / 1000 - t0
        said.append({"s": round(s, 3), "e": round(e, 3), "text": c.get("text", ""), "cut": bool(c.get("stop") and (not c.get("end") or c["stop"] < c["end"]))})
    json.dump(said, open(os.path.join(out, "said_s.json"), "w"), indent=1)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "raw.mp4", "-i", "app_audio.wav", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "raw_with_audio.mp4"], cwd=out, check=True)
    for m in secs:
        print(f"  {m['s']:7.2f}s  {m['name']}")
    print(f"assembled {len(rows)} frames, {len(meta['clips'])} clips → {out}/raw_with_audio.mp4")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "record":
        base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8660"
        out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "runs", "video", "take1")
        asyncio.run(record(base, out))
    elif cmd == "assemble":
        assemble(sys.argv[2])
    else:
        print(__doc__)
