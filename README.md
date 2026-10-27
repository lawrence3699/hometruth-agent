# HomeTruth: a rental checker you can talk to

Tell it what you need in plain English. HomeTruth checks every listing against everything it can find (the listing page, the photos, the floor plan, public data and the agent's replies), then tours the best homes out loud. For every claim it says how it knows, and when nothing backs a claim it gives you the question to ask the agent.

- **Open Agent Hackathon 2026**, Track 1: *Fragmented Intelligence* (it also fits *Explain Why*).
- **Live demo:** https://hometruth.codeprism.tech. Type or talk; voice needs Chrome.
- **Real-time voice version:** https://hometruth-voice.codeprism.tech. NVIDIA Parakeet does the speech recognition, and you can interrupt mid-sentence.
- **Sponsor technology:** [docs/SPONSORS.md](docs/SPONSORS.md) explains how we use Zetaris, Meterless and NVIDIA. We did not use Cursor.

## The problem

Listing pages are written to sell the home. The facts that decide whether it works for you are scattered or missing:

- Is the air conditioning in the bedroom or only the living room?
- Which way do the windows face?
- Are pets allowed in writing?
- How long is the walk to the light rail?

Renters piece these together from photos, floor plans, maps and back-and-forth with agents. Many only find the deal-breaker at the inspection.

## What it does

1. **You say what you need.** For example: *"Two bedrooms near UNSW, under $900 a week, I have a cat."* If one of the five essentials is missing, it asks for it. The essentials are budget, bedrooms, where you need to get to, move-in date and pets. It asks for at most two at a time and asks at most twice. Anything else it assumes and tells you what it assumed.
2. **It searches every source at once.** Seven federated SQL queries go through **Zetaris**, one per source. The source panel lights up row by row, with row counts and timings.
3. **It tours the best homes out loud in short sentences.** For each home it says why it fits, what's special and how it knows. The card, the matrix cell and the evidence row it is talking about light up as it speaks.
4. **Every check has one of four honest states:**
   - **Supported:** a source says so.
   - **Inferred:** likely, but nothing states it.
   - **Conflict:** it goes against what you need.
   - **Unknown:** no source covers it. When a hard requirement is unknown, it shows as **To confirm** and never counts as a match.
5. **Unknowns become questions.** Each home gets the three questions most worth asking its agent. You also get what to look for at the inspection.
6. **Agent replies update everything.** Paste an agent's reply, or let one arrive in the inbox. The affected cells change state, the ranking updates, and a versioned change log records who changed what and when.
7. **You can interrupt at any time.** For example: *"skip this one"*, *"what about parking?"*, *"oh, and it needs to be furnished"*. It re-plans from where you are and doesn't repeat what you've already heard.
8. **It remembers you.** Next visit it says *"Welcome back"*, then tells you what changed while you were away and what is still open. **Forget me** deletes all of it.

There's more on the detail page:
- Sun and aspect: the sun path for the address and the window direction.
- Median rents by postcode from NSW bond lodgements.
- Facts read from the photos and the floor plan, each labelled with the model that read them.
- An approximate 3D plan built from the floor plan.
- **Looks like this:** upload rooms you like and see a style match. It's a soft preference and never affects the ranking.

## How it works

```
 Browser (Notion-style page, voice orb, cards, evidence matrix)
   ▲  event stream: state · needs · source · card · highlight · evidence · say · ask · beat · questions · done
   │  (the page only draws events; the model never draws UI)
   ▼
 src/voice/server.py (:8630, web + browser voice)    src/voice/pipecat_app.py (:8631, Pipecat + WebRTC, Riva ASR/TTS)
   ├─ policy.py        dialogue policy: ask the essentials, classify interruptions, plan and re-plan the tour, rank
   ├─ phraser.py       short sentences built only from the evidence matrix (narrator.py: optional Nemotron rewrite, checked)
   ├─ zetaris_live.py  7 parallel Zetaris queries per search → every evidence row carries its query id
   ├─ beliefs.py       versioned beliefs per cell (World Model style): agent reply → new version + reason + rank change
   ├─ memory.py        cross-visit renter memory (H-MEM style): needs, shortlist, what changed while away
   └─ inbox.py         agent replies waiting for a renter (email/SMS stand-in: scripts/agent_reply.py)
 src/llm/provider.py   the only way out to a model: Meterless Runtime (Nightshift) first → NVIDIA direct → none; logs the route
 src/photo/            Nemotron VL reads listing photos, floor plans, style references; 3D plan from the floor plan
 src/sun/solar.py      sun position for the address and date; src/evidence/bond_rents.py  NSW bond median rents
```

The rules behind the four states are written down per evidence type in [docs/01](docs/01_判断规则与证据分级.md). For example, a listing photo can show that a dishwasher is present, but it can't show that the dishwasher works. The dimensions we check (rent, rooms, commute, pets, sun and so on, 75 in total) are listed in [docs/02](docs/02_维度清单.md). The design docs are in Chinese, the team's working language. This README and [docs/SPONSORS.md](docs/SPONSORS.md) are the English entry points.

### Measured

| What | Result |
|---|---|
| Zetaris queries per search | 7 in parallel, each 1.4–2.5 s on the hosted server. All 7 sources are lit about 3 s after the voice starts. In the measured run, 21 of 21 evidence rows came via Zetaris. |
| From your request to the end of a three-home tour | 52–61 s locally and 59–60 s on the hosted demo. Before this upgrade it took 213–269 s. |
| Until the first home is spoken about | 4.3 s on the hosted demo and 4.8 s locally |
| Longest sentence in a tour | 7.8 s |
| Interruptions handled as meant | 15 of 15, in a simulation of 21 scripted renters, most of whom interrupt mid-tour (`scripts/voice_customer_sim.py`) |
| Old content repeated after you add a need mid-tour | none |
| Unit tests | 270, all offline: Zetaris, Meterless and NVIDIA are faked |

## Run it

You need macOS or Linux and Python 3.12. The web version runs on the standard library alone and works with Python 3.9 or later. Voice input needs Chrome.

```bash
git clone <this repo> hometruth && cd hometruth
python3 src/voice/server.py
```

Open http://127.0.0.1:8630 and type *"Two bedrooms near UNSW under 900 a week, I have a cat"*, or press **Start talking**.

**With no keys at all** the whole flow still runs:
- Needs are parsed by rules.
- Sentences come from templates.
- Source queries are simulated. Hover over a source row and it says *simulated*.
- The voice is macOS `say` or the browser's built-in voice.

To turn on the real services:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-voice.txt
cp .env.example .env    # then fill in what you have; every entry is commented
```

| To get | Set in `.env` | Without it |
|---|---|---|
| Nemotron needs parsing, photo and floor plan reading, reply reading | `NVIDIA_API_KEY` (from build.nvidia.com) | rules and templates |
| Model calls routed through Meterless | Nightshift running locally, plus `METERLESS_BASE_URL` and `METERLESS_RUNTIME_TOKEN` (or `METERLESS_CONNECT_LINK`) | calls go to NVIDIA directly, and each call's log records the route it took |
| Evidence through Zetaris | `ZETARIS_*`, after registering the tables with `scripts/zetaris/10_register_hometruth.sql` (see [docs/SPONSORS.md](docs/SPONSORS.md)) | queries are simulated and evidence is marked *local copy* |
| A natural voice on the web version | `TTS_BACKEND=elevenlabs`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE` | `say` or the browser voice |
| Real-time voice (:8631) | `NVIDIA_API_KEY` (shared by Parakeet ASR and Magpie TTS) | `--fake-speech`: you type instead of talking, but WebRTC and interruption are still real |

The real-time voice version runs with `.venv/bin/python src/voice/pipecat_app.py` and is served at http://127.0.0.1:8631. Add `--dry-run` to see which keys are missing.

## Test it

```bash
python3 -m unittest discover -s tests -p 'test_*.py'          # unit tests, offline
python3 tests/voice_regression.py --base http://127.0.0.1:8630 \
  --out runs/voice_regression/local.jsonl --compare runs/voice_regression/baseline_8630_materials.jsonl
.venv/bin/python scripts/voice_customer_sim.py http://127.0.0.1:8630 runs/voice_sim/local.json   # simulated renters
```

## Data

- **5 synthetic listings** come with a full set of materials: listing text, photos, a floor plan and strata by-laws. They were generated truth-first: we wrote the ground truth, rendered the materials from it, and computed in code which questions each material can answer. They use real suburbs and postcodes but no real full addresses ([docs/03](docs/03_数据schema.md), [docs/04](docs/04_数据生成prompt.md)).
- **483 real Sydney listings** come from search-result pages the team saved by hand from Domain and realestate.com.au. We kept facts only: rent, bedrooms, bathrooms, parking, location and the features list. Nothing was scraped, and these listings have far less evidence, which is why most of their checks are *Unknown* and turn into questions.
- **Public data:**
  - NSW Fair Trading rental bond lodgements, as median rent by postcode, bedrooms and dwelling type (CC BY 4.0; `data/public/`).
  - The sun position, computed from coordinates.
  - Commute times, which are estimates and are marked as such.
- **Not in this repository:**
  - Listing photos, which belong to the agencies. The hosted demo shows them with their source.
  - The illustrative interior photos and the voice-orb renderer used on the hosted demo. The repository ships a simple orb with the same interface.
  - Server deployment scripts.
  - The app runs without any of these, and missing photos show as plain placeholders.

## Repository map

| Path | What |
|---|---|
| `src/voice/` | the app: servers, dialogue policy, phrasing, Zetaris client, beliefs, memory, inbox, front end in `static/` |
| `src/voice/mock_matrix.json` | the evidence matrix: 488 listings × checked dimensions, each cell with its evidence rows |
| `src/llm/provider.py` | model routing (Meterless Runtime → NVIDIA → none) per Meterless's provider contract v4 |
| `src/photo/`, `src/sun/`, `src/evidence/` | photo, floor plan and style reading; the 3D plan; sun geometry; bond rents |
| `scripts/zetaris/` | SQL to register, query and drop the Zetaris tables and views |
| `scripts/` | data import, photo reading, screenshots, regression, the customer simulator, demo-video recording |
| `tests/` | unit tests and the voice regression baselines |
| `docs/` | product plan (00), judgement rules (01), dimensions (02), data schema (03), data generation (04), and so on, in Chinese |

## What we built and what we reused

- Our code was written during the hackathon window, which opened on 22 Oct 2026. The repository's first commit is from 27 Oct.
- **Open-source components used:**
  - three.js (MIT), for the 3D plan.
  - Lucian UX/UI Prompt effects (MIT), in `src/voice/static/qi/vendor/lucian/`.
  - Pipecat (BSD-2-Clause) and the NVIDIA Riva client, for real-time voice.
  - Google Fonts: Inter, Newsreader and IBM Plex Mono.
- **Services:** Zetaris Cloud, Meterless Nightshift, NVIDIA build.nvidia.com (Nemotron, Parakeet, Magpie) and the ElevenLabs text-to-speech API.
- Memory and beliefs follow Meterless's H-MEM and World Model patterns. We implemented them ourselves in Python and didn't use the TypeScript reference package.

## Limitations

- **Meterless on the hosted demo:** Nightshift is a desktop app on our laptop, so the hosted demo's model calls go to NVIDIA directly. Each call logs the route it took. Run locally with Nightshift open, the same code routes through Meterless.
- **Real listings have thin evidence:** they carry only what a search-result card shows, plus what the photos reveal.
- **Approximate features:** commute times, the 3D plan and the style match are approximate, and the app labels them that way.
- **Agent reply channel:** agent replies arrive through a paste box or an inbox file. A real email or SMS webhook is not built yet.
- **No comparison experiment yet:** we planned to compare the same model reading only the listing against multi-source checking. That experiment isn't finished.

## Next

- Hook up the email and SMS reply channel, so questions go to the agent and the answers come back on their own.
- Run the listing-only vs multi-source comparison and publish the numbers.
- Let renters add their own inspection photos as a new evidence source.
