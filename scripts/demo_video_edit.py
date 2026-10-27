# -*- coding: utf-8 -*-
"""Cut the hackathon video from one recorded take (scripts/demo_video.py): title card, the parts of the live demo worth seeing,
narration in the gaps, chapter labels, an end card with how it is built.

  voice  .venv/bin/python scripts/demo_video_edit.py voice  [--voice Charlie]   narration → runs/video/vo/*.wav (cached by text)
  cards  .venv/bin/python scripts/demo_video_edit.py cards  --base http://127.0.0.1:8660   title / end / labels → runs/video/cards/*.png
  build  .venv/bin/python scripts/demo_video_edit.py build  runs/video/take1   → deliverables/video/HomeTruth_demo.mp4

The page's own voice (Sarah, what the app says) is never re-voiced or re-timed: a demo part is cut on sentence boundaries from the take.
The narrator only talks over the title, a held frame, silent parts of the page and the end card, so the two voices never overlap.
Narration text lives in NARRATION below and in deliverables/video/SCRIPT.md (for a person to read it instead)."""
import hashlib, json, os, subprocess, sys, wave
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "voice"))
VO = os.path.join(ROOT, "runs", "video", "vo")
CARDS = os.path.join(ROOT, "runs", "video", "cards")
OUT = os.path.join(ROOT, "deliverables", "video")
SR = 48000
FPS = 30
W, H = 1920, 1080

NARRATION = {
    "hook": ("Renting in Sydney, every listing says perfect. The photos are staged, the air con is somewhere in the flat, "
             "and you find out at the viewing. HomeTruth is a rental agent that checks each place against what you need, "
             "and tells you how it knows."),
    "zetaris": ("While it talks, it checks seven sources. Each one is a live SQL query through Zetaris, run where the data lives, "
                "and every line of evidence keeps its query ID."),
    "reply": ("When the agent writes back, paste the reply in. The cell flips, the ranking moves, and every change is kept with its source."),
    "explore": ("Behind it are over four hundred real Sydney rentals, saved from public listing pages, next to a hand-built test set. "
                "NVIDIA Nemotron's vision model reads the photos and floor plans. It describes what it sees; it never decides the ranking."),
    "end": ("Your words go to NVIDIA Nemotron through Meterless Nightshift, and every piece of evidence comes back through Zetaris, "
            "labelled supported, inferred, conflict or unknown. HomeTruth never guesses. Know what's true before you apply."),
    # the two-minute cut (plan_short) uses these instead
    "hook_s": ("Every listing says perfect. HomeTruth checks each place against what you need, and shows you how it knows."),
    "zetaris_s": ("Seven sources, each a live query through Zetaris."),
    "end_s": ("Over four hundred real Sydney rentals. Nemotron reads your request through Meterless Nightshift, and Zetaris brings back the evidence. "
              "HomeTruth never guesses."),
}

# chapter labels (top-left pill) and their text
LABELS = {
    "need": "Say what you need",
    "ask": "It only asks for what's missing",
    "sources": "Seven live sources · Zetaris",
    "walk": "Every line says what backs it",
    "photo": "Photo read by NVIDIA Nemotron",
    "interrupt": "Interrupt any time",
    "real": "Real listing · NSW bond data",
    "reply": "Agent replies update the ranking",
    "explore": "400+ real Sydney listings",
}


def key_of(text, voice, model):
    return hashlib.sha1(f"{voice}|{model}|{text}".encode()).hexdigest()[:12]


def voice(name="Charlie", model="eleven_v4"):
    """Each narration paragraph as one take (prosody runs through the paragraph); cached by voice + model + text."""
    from llm import provider as llm
    llm.load_env()
    import eleven
    os.makedirs(VO, exist_ok=True)
    key = eleven.api_key()
    out = {}
    for k, text in NARRATION.items():
        path = os.path.join(VO, f"{k}_{key_of(text, name, model)}.wav")
        if not os.path.exists(path):
            pcm = eleven.synth(text, name, key, model_id=model, sample_rate=24000, timeout=90,
                               voice_settings={"stability": 0.5, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True})
            with wave.open(path, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
            print("  synthesised", os.path.basename(path))
        with wave.open(path) as w:
            out[k] = {"wav": path, "s": round(w.getnframes() / w.getframerate(), 2)}
        print(f"  {k:8s} {out[k]['s']:5.1f}s  {text[:70]}")
    json.dump(out, open(os.path.join(VO, "index.json"), "w"), indent=1)
    return out


# ---------------- cards: rendered by headless Chrome from HTML, 1920×1080 (overlays transparent) ----------------
CSS = """
*{box-sizing:border-box} html,body{margin:0;width:1920px;height:1080px;overflow:hidden;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#191918;-webkit-font-smoothing:antialiased}
body.card{background:#fff} body.clear{background:transparent}
.brand{position:absolute;left:120px;top:84px;display:flex;align-items:center;gap:16px;font-size:34px;font-weight:700;letter-spacing:-.01em}
.brand svg{width:46px;height:46px}
h1{margin:0;font-size:92px;line-height:1.05;letter-spacing:-.035em;font-weight:700}
.hook{position:absolute;left:120px;top:250px;right:120px}
.tbl{margin-top:70px;display:grid;grid-template-columns:620px 90px 1fr;row-gap:34px;font-size:40px;align-items:center}
.tbl .h{font-size:24px;font-weight:600;color:#787774;text-transform:uppercase;letter-spacing:.08em}
.tbl .say{color:#37352f} .tbl .arw{color:#9b9a97;font-size:40px}
.tbl .row{display:contents} .tbl .row.off>*{visibility:hidden}
.pill{display:inline-flex;align-items:center;gap:14px;padding:10px 24px;border-radius:999px;font-size:36px;font-weight:600}
.pill i{width:16px;height:16px;border-radius:50%;background:currentColor}
.conflict{background:#fde8e6;color:#c4352b} .inferred{background:#fdf0d8;color:#b26a00} .unknown{background:#ebebea;color:#5f5e5b} .supported{background:#e3f1e8;color:#2c7a4b}
.end{position:absolute;left:120px;top:210px;right:120px}
.end h1{font-size:84px}
.grid{margin-top:64px;display:grid;grid-template-columns:1fr 1fr;gap:28px}
.box{background:#f7f6f3;border-radius:22px;padding:34px 40px;min-height:200px}
.box b{display:block;font-size:34px;margin-bottom:12px;letter-spacing:-.01em} .box p{margin:0;font-size:27px;line-height:1.42;color:#37352f}
.foot{position:absolute;left:120px;right:120px;bottom:70px;display:flex;justify-content:space-between;align-items:flex-end;font-size:24px;color:#787774}
.foot .url{font-size:40px;font-weight:700;color:#191918;letter-spacing:-.01em}
.label{position:absolute;left:__LX__px;top:__LY__px;display:inline-flex;align-items:center;gap:16px;background:rgba(255,255,255,.96);border:1.5px solid #e3e2e0;
  border-radius:999px;padding:14px 30px 14px 16px;font-size:31px;font-weight:600;box-shadow:0 10px 30px rgba(15,15,15,.12)}
.label .n{width:44px;height:44px;border-radius:50%;background:#191918;color:#fff;display:grid;place-items:center;font-size:24px;font-weight:700}
.sub{position:absolute;left:50%;bottom:64px;transform:translateX(-50%);max-width:1500px;width:max-content;background:rgba(20,20,19,.84);color:#fff;
  font-size:38px;line-height:1.38;font-weight:500;padding:18px 34px;border-radius:16px;text-align:center}
"""


def hook_html(logo, upto):
    rows = [("Bright, fully furnished", "conflict", "Photos virtually staged"),
            ("Air conditioning", "inferred", "Living room only"),
            ("Pets considered", "unknown", "Nothing in writing")]
    body = "".join(f'<div class="row{"" if i < upto else " off"}"><span class="say">“{a}”</span><span class="arw">→</span>'
                   f'<span><span class="pill {st}"><i></i>{b}</span></span></div>' for i, (a, st, b) in enumerate(rows))
    return (f'<body class="card"><div class="brand">{logo}HomeTruth</div><div class="hook"><h1>Every listing says “perfect”.</h1>'
            f'<div class="tbl"><span class="h">The listing says</span><span></span><span class="h">What is actually on file</span>{body}</div></div></body>')


END_BOXES = [
    ("NVIDIA Nemotron", "Nemotron 3.5 Lightning reads what you ask for, routed through Meterless Nightshift. Nemotron 3.5 Super VL reads the listing photos and floor plans."),
    ("Zetaris", "Seven live SQL queries on every search, one per source. Every line of evidence keeps the ID of the query that returned it."),
    ("Meterless Nightshift", "The runtime in front of Nemotron. Every model call is logged with its route, model, prompt hash and latency."),
    ("Real data", "400+ Sydney rentals saved from public listing pages, NSW Fair Trading bond lodgements (CC BY 4.0) and transit times."),
]


def end_html(logo):
    boxes = "".join(f'<div class="box"><b>{a}</b><p>{b}</p></div>' for a, b in END_BOXES)
    return (f'<body class="card"><div class="brand">{logo}HomeTruth</div><div class="end"><h1>Know what’s true before you apply.</h1>'
            f'<div class="grid">{boxes}</div></div><div class="foot"><span class="url">hometruth.codeprism.tech</span>'
            f'<span>Voices by ElevenLabs · Listing photos © their agencies · Open Agent Hackathon 2026, Track 1</span></div></body>')


def split_sentences(text):
    import re
    return [p.strip() for p in re.split(r"(?<=[.;:?])\s+", text) if p.strip()]


async def _render(base, jobs):
    import asyncio, tempfile, time, urllib.request
    import websockets
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from demo_video import CHROME, CDP
    port = 9347
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", "--window-size=1920,1080",
                             f"--user-data-dir={tempfile.mkdtemp(prefix='cdp-cards-')}", "--no-first-run", "--hide-scrollbars",
                             "--force-color-profile=srgb", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        targets = None
        for _ in range(100):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)); break
            except Exception:
                time.sleep(0.2)
        page = next(t for t in targets if t["type"] == "page")
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            reader = asyncio.create_task(cdp.reader())
            await cdp.call("Page.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=base.rstrip("/") + "/api/hello")
            await asyncio.sleep(1.0)
            logo = await cdp.js("import('/static/notion/ink.js?v=3').then(m => m.LOGO)")
            for name, html, clear in jobs:
                html = html(logo) if callable(html) else html
                await cdp.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0 if clear else 1})
                await cdp.js(f"document.open(); document.write({json.dumps('<!doctype html><html><head><meta charset=utf-8><style>' + CSS + '</style></head>' + html + '</html>')}); document.close(); document.fonts.ready.then(() => 'ok')")
                await asyncio.sleep(0.3)
                r = await cdp.call("Page.captureScreenshot", format="png")
                import base64
                open(os.path.join(CARDS, name + ".png"), "wb").write(base64.b64decode(r["data"]))
                print("  card", name)
            reader.cancel()
    finally:
        proc.terminate()


def cards(base):
    import asyncio
    os.makedirs(CARDS, exist_ok=True)
    jobs = [(f"hook_{k}", (lambda k: lambda logo: hook_html(logo, k))(k), False) for k in range(4)]
    jobs.append(("end", end_html, False))
    for i, (k, text) in enumerate(LABELS.items()):
        jobs.append((f"label_{k}", f'<body class="clear"><div class="label"><span class="n">{i + 1}</span>{text}</div></body>', True))
    for k, text in NARRATION.items():
        for i, sent in enumerate(split_sentences(text)):
            jobs.append((f"sub_{k}_{i}", f'<body class="clear"><div class="sub">{sent}</div></body>', True))
    CSS_FIX = CSS.replace("__LX__", "40").replace("__LY__", "104")
    globals()["CSS"] = CSS_FIX
    asyncio.run(_render(base, jobs))


# ---------------- build: video segments → concat → overlays; audio = the page's track (cut the same way) + narration ----------------
def read_wav(path):
    with wave.open(path) as w:
        rate, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64) / 32767
    if rate != SR:
        x = np.interp(np.arange(int(len(x) * SR / rate)) * rate / SR, np.arange(len(x)), x)
    return x


def speech_spans(x, thr_db=-40.0, min_gap=0.18):
    """(start, end) seconds of voiced stretches: 20 ms RMS above thr_db, gaps shorter than min_gap merged."""
    hop = SR // 50
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same")[::hop] + 1e-12)
    on = 20 * np.log10(rms) > thr_db
    spans, start = [], None
    for i, v in enumerate(on):
        t = i * hop / SR
        if v and start is None:
            start = t
        elif not v and start is not None:
            spans.append([start, t]); start = None
    if start is not None:
        spans.append([start, len(x) / SR])
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] < min_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def sentence_times(key, x):
    """When each sentence of a narration paragraph is spoken: the (n − 1) longest pauses are the sentence breaks."""
    sents = split_sentences(NARRATION[key])
    spans = speech_spans(x)
    if len(sents) == 1 or len(spans) < len(sents):
        return [(spans[0][0], spans[-1][1])] * len(sents) if len(sents) == 1 else [(spans[0][0] + i * (spans[-1][1] - spans[0][0]) / len(sents), spans[0][0] + (i + 1) * (spans[-1][1] - spans[0][0]) / len(sents)) for i in range(len(sents))]
    gaps = sorted(((spans[i + 1][0] - spans[i][1], i) for i in range(len(spans) - 1)), reverse=True)[:len(sents) - 1]
    cuts = sorted(i for _, i in gaps)
    out, lo = [], 0
    for c in cuts + [len(spans) - 1]:
        out.append((spans[lo][0], spans[c][1])); lo = c + 1
    return out


def ff(*args, cwd=None):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True, cwd=cwd)


ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]


def render_segment(item, take, path, work):
    kind = item["kind"]
    if kind == "cut":
        sp = item.get("speed", 1.0)
        vf = ["-vf", f"scale={W}:{H}:flags=lanczos" + (f",setpts=PTS/{sp}" if sp != 1.0 else "")]  # scale: a take recorded smaller still concatenates
        ff("-ss", f"{item['a']:.3f}", "-to", f"{item['b']:.3f}", "-i", os.path.join(take, "raw.mp4"), "-an", *vf, *ENC, path)
    elif kind == "hold":
        png = os.path.join(work, f"hold_{item['t']:.2f}.png")
        ff("-ss", f"{item['t']:.3f}", "-i", os.path.join(take, "raw.mp4"), "-frames:v", "1", png)
        cx, cy, z1 = item.get("zoom", (W / 2, H / 2, 1.0))
        n = int(item["dur"] * FPS)
        ease = f"(3*pow(min(1,on/{max(1, int(n * 0.55))}),2)-2*pow(min(1,on/{max(1, int(n * 0.55))}),3))"
        z = f"1+{z1 - 1:.4f}*{ease}"
        vf = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':x='max(0,min(iw-iw/zoom,{cx * 2:.1f}-iw/zoom/2))':"
              f"y='max(0,min(ih-ih/zoom,{cy * 2:.1f}-ih/zoom/2))':d=1:s={W}x{H}:fps={FPS}")
        ff("-loop", "1", "-t", f"{item['dur']:.3f}", "-i", png, "-vf", vf, *ENC, path)
    elif kind == "card":
        ff("-loop", "1", "-t", f"{item['dur']:.3f}", "-i", os.path.join(CARDS, item["png"] + ".png"), "-vf", "format=yuv420p", *ENC, path)
    elif kind == "hook":  # hook_0 with rows fading in at item["at"]
        ins, fc, last = ["-loop", "1", "-t", f"{item['dur']:.3f}", "-i", os.path.join(CARDS, "hook_0.png")], [], "[0:v]"
        for k, t in enumerate(item["at"], start=1):
            ins += ["-loop", "1", "-t", f"{item['dur']:.3f}", "-i", os.path.join(CARDS, f"hook_{k}.png")]
            fc.append(f"[{k}:v]format=rgba,fade=in:st={t:.2f}:d=0.35:alpha=1[h{k}];{last}[h{k}]overlay=0:0[v{k}]")
            last = f"[v{k}]"
        ff(*ins, "-filter_complex", ";".join(fc), "-map", last, *ENC, path)
    else:
        raise ValueError(kind)


def build(take, items, overlays, vo_at, out_name="HomeTruth_demo.mp4", work_name="edit"):
    """items: segments in order (cut / hold / card / hook, each with dur or a..b, and app gain); overlays: (png, start, end) on the
    final timeline; vo_at: narration key → start second on the final timeline."""
    take = os.path.abspath(take)  # the concat list resolves paths against its own folder
    work = os.path.join(take, work_name)
    os.makedirs(work, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    app = read_wav(os.path.join(take, "app_audio.wav"))
    segs, track, t = [], [], 0.0
    for i, it in enumerate(items):
        dur = (it["b"] - it["a"]) / it.get("speed", 1.0) if it["kind"] == "cut" else it["dur"]
        path = os.path.join(work, f"seg_{i:02d}.mp4")
        sig = json.dumps({k: v for k, v in it.items() if k not in ("note", "t0")}, sort_keys=True)
        if not (os.path.exists(path) and os.path.exists(path + ".json") and open(path + ".json").read() == sig):  # same segment as last build: reuse it
            render_segment(it, take, path, work)
            open(path + ".json", "w").write(sig)
        segs.append(path)
        n = int(round(dur * FPS)) / FPS  # what the encoder actually keeps
        piece = np.zeros(int(n * SR))
        if it["kind"] == "cut" and it.get("gain", 1.0) > 0 and it.get("speed", 1.0) == 1.0:  # a sped-up part (typing) keeps no page sound
            a = int(it["a"] * SR)
            seg = app[a:a + len(piece)] * it.get("gain", 1.0)
            r = min(len(seg) // 2, int(0.012 * SR))
            if r:
                seg[:r] *= np.linspace(0, 1, r); seg[-r:] *= np.linspace(1, 0, r)
            piece[:len(seg)] = seg
        track.append(piece)
        it["t0"] = t
        t += n
        print(f"  seg {i:02d} {it['kind']:5s} {it['t0']:7.2f} → {t:7.2f}  {it.get('note', '')}")
    total = t
    app_t = np.concatenate(track)
    vo_t = np.zeros_like(app_t)
    duck = np.ones_like(app_t)
    idx = json.load(open(os.path.join(VO, "index.json")))
    for k, at in vo_at.items():
        x = read_wav(idx[k]["wav"])
        s = int(at * SR)
        vo_t[s:s + len(x)] += x[:len(vo_t) - s]
        a, b = max(0, s - int(0.15 * SR)), min(len(duck), s + len(x) + int(0.2 * SR))
        duck[a:b] = 0.22
    duck = np.convolve(duck, np.ones(int(0.12 * SR)) / int(0.12 * SR), mode="same")
    mix = np.clip(app_t * duck + vo_t * 1.05, -1, 1)
    wav_path = os.path.join(work, "mix.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((mix * 32767).astype(np.int16).tobytes())
    with open(os.path.join(work, "segs.txt"), "w") as f:
        f.writelines(f"file '{p}'\n" for p in segs)
    base = os.path.join(work, "base.mp4")
    ff("-f", "concat", "-safe", "0", "-i", os.path.join(work, "segs.txt"), "-c", "copy", base)
    ins, fc, last = ["-i", base], [], "[0:v]"
    for k, (png, a, b) in enumerate(overlays, start=1):
        ins += ["-loop", "1", "-t", f"{total:.3f}", "-i", os.path.join(CARDS, png + ".png")]
        fc.append(f"[{k}:v]format=rgba,fade=in:st={a:.2f}:d=0.25:alpha=1,fade=out:st={max(a, b - 0.25):.2f}:d=0.25:alpha=1[o{k}];"
                  f"{last}[o{k}]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[w{k}]")
        last = f"[w{k}]"
    final = os.path.join(OUT, out_name)
    if fc:
        ins += ["-i", wav_path]
        ff(*ins, "-filter_complex", ";".join(fc), "-map", last, "-map", f"{len(overlays) + 1}:a", "-t", f"{total:.3f}", *ENC,
           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", final)
    else:
        ff("-i", base, "-i", wav_path, "-c:v", "copy", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ac", "2", final)
    print(f"→ {final}  ({total:.1f} s)")
    return final


# ---------------- the edit: which parts of the take, where the narration and labels go ----------------
ZOOM_SOURCES = (420, 780, 1.6)  # centre (px on the 1920×1080 frame) and zoom of the hold on the sidebar's source list


class Timeline:
    """Lays segments end to end with the same frame rounding build() uses, so overlay times line up with the cut."""

    def __init__(self):
        self.items, self.overlays, self.vo_at, self.t = [], [], {}, 0.0

    def add(self, item, note=""):
        dur = (item["b"] - item["a"]) / item.get("speed", 1.0) if item["kind"] == "cut" else item["dur"]
        item["note"] = note
        start = self.t
        self.items.append(item)
        self.t += int(round(dur * FPS)) / FPS
        return start

    def label(self, key, a, b):
        self.overlays.append((f"label_{key}", a, b))

    def vo(self, key, at, x):
        """Narration paragraph at `at`, with its sentences as subtitles; returns when it ends."""
        self.vo_at[key] = at
        for i, (s0, s1) in enumerate(sentence_times(key, x)):
            self.overlays.append((f"sub_{key}_{i}", at + s0 - 0.05, at + s1 + 0.25))
        return at + len(x) / SR


def plan(take):
    import re
    M = {m["name"]: m["s"] for m in json.load(open(os.path.join(take, "marks_s.json")))}
    S = json.load(open(os.path.join(take, "said_s.json")))

    def said(rx, after=0.0):
        hit = next((x for x in S if x["s"] >= after - 0.05 and re.search(rx, x["text"], re.I)), None)
        if hit is None:
            raise SystemExit(f"no sentence /{rx}/ after {after:.1f}s in {take}/said_s.json")
        return hit

    def last_before(t):
        return max((x for x in S if x["e"] <= t + 0.05), key=lambda x: x["e"])

    idx = json.load(open(os.path.join(VO, "index.json")))
    X = {k: read_wav(v["wav"]) for k, v in idx.items()}
    T = Timeline()

    # 1 · hook card: the three "listing says / on file" rows come in with the second sentence
    hs = sentence_times("hook", X["hook"])
    lead = 0.5
    s2a, s2b = hs[1]
    T.add({"kind": "hook", "dur": lead + s2b + 0.35, "at": [lead + s2a, lead + s2a + 0.36 * (s2b - s2a), lead + s2a + 0.68 * (s2b - s2a)]}, "hook card")
    T.vo("hook", lead, X["hook"])

    # 2 · the need, the two questions, the answer, the search starting (the hook's last sentence plays over the home page);
    #     the recap of the need is cut ("Thanks." → "Checking 7 sources now.")
    q = said(r"budget")
    thanks = said(r".", M["answer_sent"])
    checking = said(r"Checking \d+ sources", thanks["e"])
    short = said(r"places pass|got \d+|walk you through", M["answer_sent"])
    T.add({"kind": "cut", "a": M["home"] + 0.2, "b": M["type_need"] + 1.2}, "home")
    a = T.add({"kind": "cut", "a": M["type_need"] + 1.2, "b": M["need_sent"] + 0.05, "speed": 2.2}, "typing the need (2.2×)")
    T.label("need", a - 1.0, a + (M["need_sent"] - M["type_need"] - 1.2) / 2.2 + 0.5)
    a = T.add({"kind": "cut", "a": M["need_sent"] + 0.05, "b": thanks["e"] + 0.15}, "questions → answer")
    T.label("ask", a + (q["s"] - M["need_sent"] - 0.05), a + (thanks["e"] - M["need_sent"]))
    a = T.add({"kind": "cut", "a": checking["s"] - 0.15, "b": short["e"] + 0.15}, "sources running")
    T.label("sources", a, a + (short["e"] - checking["s"]) + 0.3)

    # 3 · hold on the finished source list: Zetaris
    hold_t = max(short["e"] + 0.1, M["sources_done"] + 1.2)  # a frame that already shows 7/7 (frames trail the page a little)
    h = T.add({"kind": "hold", "t": hold_t, "dur": len(X["zetaris"]) / SR + 1.0, "zoom": ZOOM_SOURCES}, "hold: 7/7 via Zetaris")
    T.vo("zetaris", h + 0.4, X["zetaris"])
    T.label("sources", h, h + len(X["zetaris"]) / SR + 1.0)

    # 4 · the first place, line by line; bedrooms / commute / move-in are cut (the commute comes back in the interruption),
    #     and so is "What's special" (it repeats the air-con line)
    first = said(r"^First", M["sources_done"] - 2)
    rent1 = said(r"^Rent", first["e"] - 0.05)
    pets1 = said(r"^Pets", rent1["e"])
    q1 = said(r"Best question", first["s"])
    a = T.add({"kind": "cut", "a": first["s"] - 0.25, "b": rent1["e"] + 0.15}, "card 1: intro + rent")
    T.label("walk", a, a + (rent1["e"] - first["s"]) + 0.4)
    photo = said(r"VIRTUALLY STAGED|staged", pets1["s"])
    a = T.add({"kind": "cut", "a": pets1["s"] - 0.1, "b": photo["e"] + 0.15}, "card 1: pets → air con → photo")
    T.label("walk", a, a + (photo["s"] - pets1["s"]) - 0.3)
    T.label("photo", a + (photo["s"] - pets1["s"]) + 0.15, a + (photo["e"] - pets1["s"]))
    a = T.add({"kind": "cut", "a": q1["s"] - 0.1, "b": q1["e"] + 0.3}, "card 1: best question")
    T.label("walk", a, a + (q1["e"] - q1["s"]) + 0.4)

    # 5 · the second place, interrupted by a question, answered, back to the tour
    second = said(r"^Second", M["card1"])
    ans = said(r".", M["question_sent"])
    back = said(r".", ans["e"] + 0.01)
    end5 = back["e"] if re.search(r"back|where was I|carry on|second", back["text"], re.I) else ans["e"]
    a = T.add({"kind": "cut", "a": second["s"] - 0.25, "b": end5 + 0.3}, "card 2 + interruption")
    T.label("interrupt", a + (M["interrupt"] - second["s"]), a + (end5 - second["s"]))

    # 6 · the third place: a real listing, rent against NSW bond records
    third = said(r"^Third|last one", M["question_sent"])
    if not re.search(r"^Third", third["text"]):
        third = said(r"^Third|two-bedroom on", third["e"])
    rent3 = said(r"bond|median", third["s"])
    a = T.add({"kind": "cut", "a": third["s"] - 0.25, "b": rent3["e"] + 0.4}, "card 3 (real) + NSW bond rent")
    T.label("real", a, a + (rent3["e"] - third["s"]) + 0.4)

    # 7 · the agent's reply flips a cell and the place drops out; then the Changes and Table views (narration over them)
    noted = said(r"Noted|conflict", M["reply_sent"])
    a = T.add({"kind": "cut", "a": M["type_reply"] - 0.6, "b": M["reply_sent"] + 0.1, "speed": 1.8}, "typing the reply (1.8×)")
    T.label("reply", a, a + (M["reply_sent"] - M["type_reply"] + 0.7) / 1.8)
    a = T.add({"kind": "cut", "a": M["reply_sent"] + 0.1, "b": noted["e"] + 0.8}, "agent reply → change")
    T.label("reply", a, a + (noted["e"] - M["reply_sent"]) + 0.7)
    a = T.add({"kind": "cut", "a": M["view_changes"] - 0.5, "b": min(M["to_explore"] - 0.6, M["view_table"] + 3.0)}, "Changes / Table views")
    T.vo("reply", a + 0.6, X["reply"])

    # 8 · the gallery of real listings and one place's page
    a = T.add({"kind": "cut", "a": M["to_explore"] - 0.2, "b": min(M["end"], M["peek_open"] + 10.0)}, "explore → real listing page")
    T.label("explore", a + 0.3, a + (M["peek_open"] - M["to_explore"]))
    T.vo("explore", a + 1.0, X["explore"])

    # 9 · end card
    e = T.add({"kind": "card", "png": "end", "dur": len(X["end"]) / SR + 1.6}, "end card")
    T.vo("end", e + 0.6, X["end"])
    return T


def plan_short(take):
    """About two minutes: the need and questions (typing at 2×), the sources and Zetaris, the first place's photo and its best question,
    the real third place against NSW bond records, the agent's reply flipping a cell, the real listings, the end card."""
    import re
    M = {m["name"]: m["s"] for m in json.load(open(os.path.join(take, "marks_s.json")))}
    S = json.load(open(os.path.join(take, "said_s.json")))

    def said(rx, after=0.0):
        hit = next((x for x in S if x["s"] >= after - 0.05 and re.search(rx, x["text"], re.I)), None)
        if hit is None:
            raise SystemExit(f"no sentence /{rx}/ after {after:.1f}s in {take}/said_s.json")
        return hit

    idx = json.load(open(os.path.join(VO, "index.json")))
    X = {k: read_wav(v["wav"]) for k, v in idx.items()}
    T = Timeline()

    T.add({"kind": "hook", "dur": 4.4, "at": [0.8, 1.5, 2.2]}, "hook card (short)")
    T.vo("hook_s", 0.4, X["hook_s"])
    q = said(r"budget")
    thanks = said(r".", M["answer_sent"])
    a = T.add({"kind": "cut", "a": M["type_need"] - 0.3, "b": M["need_sent"] + 0.1, "speed": 3.0}, "typing the need (3×)")
    T.label("need", a, a + (M["need_sent"] - M["type_need"] + 0.4) / 3)
    a = T.add({"kind": "cut", "a": M["need_sent"] + 0.1, "b": thanks["e"] + 0.15}, "question → answer")
    T.label("ask", a + (q["s"] - M["need_sent"] - 0.1), a + (thanks["e"] - M["need_sent"]))
    checking = said(r"Checking \d+ sources", thanks["e"])
    short = said(r"places pass|got \d+|walk you through", M["answer_sent"])
    a = T.add({"kind": "cut", "a": checking["s"] - 0.15, "b": short["e"] + 0.15}, "sources running")
    T.label("sources", a, a + (short["e"] - checking["s"]) + 0.3)
    h = T.add({"kind": "hold", "t": max(short["e"] + 0.1, M["sources_done"] + 1.2), "dur": len(X["zetaris_s"]) / SR + 0.8, "zoom": ZOOM_SOURCES}, "hold: Zetaris")
    T.vo("zetaris_s", h + 0.3, X["zetaris_s"])
    T.label("sources", h, h + len(X["zetaris_s"]) / SR + 0.8)

    first = said(r"^First", M["sources_done"] - 2)
    photo = said(r"VIRTUALLY STAGED|staged", first["s"])
    q1 = said(r"Best question", first["s"])
    a = T.add({"kind": "cut", "a": first["s"] - 0.25, "b": first["e"] + 0.1}, "card 1 intro")
    T.label("walk", a, a + (first["e"] - first["s"]) + 0.35)
    a = T.add({"kind": "cut", "a": photo["s"] - 0.1, "b": photo["e"] + 0.1}, "card 1 photo (Nemotron VL)")
    T.label("photo", a, a + (photo["e"] - photo["s"]) + 0.2)
    a = T.add({"kind": "cut", "a": q1["s"] - 0.1, "b": q1["e"] + 0.3}, "card 1 best question")
    T.label("walk", a, a + (q1["e"] - q1["s"]) + 0.4)

    third = said(r"^Third|last one", M["question_sent"])
    if not re.search(r"^Third", third["text"]):
        third = said(r"^Third|two-bedroom on", third["e"])
    rent3 = said(r"bond|median", third["s"])
    a = T.add({"kind": "cut", "a": third["s"] - 0.25, "b": rent3["e"] + 0.4}, "card 3 (real) + NSW bond rent")
    T.label("real", a, a + (rent3["e"] - third["s"]) + 0.4)

    noted = said(r"Noted|conflict", M["reply_sent"])
    a = T.add({"kind": "cut", "a": M["type_reply"] - 0.6, "b": M["reply_sent"] + 0.1, "speed": 3.0}, "typing the reply (3×)")
    T.label("reply", a, a + (M["reply_sent"] - M["type_reply"] + 0.7) / 3)
    a = T.add({"kind": "cut", "a": M["reply_sent"] + 0.1, "b": noted["e"] + 0.8}, "change")
    T.label("reply", a, a + (noted["e"] - M["reply_sent"]) + 0.7)

    a = T.add({"kind": "cut", "a": M["real_filter"] - 2.5, "b": M["peek_open"] + 3.5}, "real listings → one page")
    T.label("explore", a + 0.3, a + (M["peek_open"] - M["real_filter"] + 2.5))
    T.vo("end_s", a + 1.0, X["end_s"])
    e = T.add({"kind": "card", "png": "end", "dur": max(4.0, a + 1.0 + len(X["end_s"]) / SR + 1.4 - T.t)}, "end card")
    return T


def write_script(take, T, path):
    """What is heard, in order, on the final timeline: narration (N), the app's voice (App, cut from the take), the renter's typed lines."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import demo_video
    S = json.load(open(os.path.join(take, "said_s.json")))
    M = {m["name"]: m["s"] for m in json.load(open(os.path.join(take, "marks_s.json")))}
    typed = {"type_need": demo_video.NEED, "type_answer": demo_video.ANSWER, "interrupt": demo_video.QUESTION, "type_reply": demo_video.REPLY}
    rows = [(at, "Narrator", NARRATION[k]) for k, at in T.vo_at.items()]
    t = 0.0
    for it in T.items:
        sp = it.get("speed", 1.0)
        dur = (it["b"] - it["a"]) / sp if it["kind"] == "cut" else it["dur"]
        if it["kind"] == "cut" and sp == 1.0:
            rows += [(t + x["s"] - it["a"], "App (Sarah)", x["text"] + (" [cut off]" if x["cut"] else "")) for x in S if it["a"] - 0.05 <= x["s"] < it["b"]]
        if it["kind"] == "cut":
            rows += [(t + (M[k] - it["a"]) / sp, "Renter (typed)", v) for k, v in typed.items() if k in M and it["a"] - 0.7 <= M[k] < it["b"]]
        t += int(round(dur * FPS)) / FPS
    rows.sort()
    with open(path, "w") as f:
        f.write(f"# HomeTruth demo video: what is heard\n\nTotal {T.t:.0f} s ({int(T.t // 60)}:{int(T.t % 60):02d}). Generated by scripts/demo_video_edit.py from {os.path.relpath(take, ROOT)}.\n"
                "The narrator is ElevenLabs Charlie; to record it with a real voice, read the Narrator lines at these times.\n"
                "The app's lines are the live page's own speech (ElevenLabs Sarah, template narration from the evidence matrix), cut on sentence boundaries.\n\n"
                "| time | who | line |\n|---:|---|---|\n")
        for at, who, line in rows:
            f.write(f"| {int(at // 60)}:{at % 60:04.1f} | {who} | {line.replace('|', '/')} |\n")
    print("→", path)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "voice":
        voice(sys.argv[sys.argv.index("--voice") + 1] if "--voice" in sys.argv else "Charlie")
    elif cmd == "build":
        take = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else os.path.join(ROOT, "runs", "video", "take2")
        T = plan_short(take) if "--short" in sys.argv else plan(take)
        if "--dry" in sys.argv:
            for it in T.items:
                print(" ", it["kind"], it.get("note"), {k: round(v, 2) for k, v in it.items() if isinstance(v, float)})
            for o in T.overlays:
                print("  overlay", o[0], round(o[1], 2), round(o[2], 2))
            print("  vo", {k: round(v, 2) for k, v in T.vo_at.items()}, "total", round(T.t, 1))
        else:
            short = "--short" in sys.argv
            build(take, T.items, T.overlays, T.vo_at, out_name="HomeTruth_demo_2min.mp4" if short else "HomeTruth_demo.mp4", work_name="edit_short" if short else "edit")
            write_script(take, T, os.path.join(OUT, "HomeTruth_demo_2min_script.md" if short else "HomeTruth_demo_script.md"))
    elif cmd == "cards":
        cards(sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8660")
    else:
        print(__doc__)
