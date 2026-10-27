# How HomeTruth uses the sponsor technology

This page covers rule 6.4 of the Open Agent Hackathon 2026: how we used Zetaris, Meterless, NVIDIA and Cursor, and what is unique about each use.

## Zetaris: every piece of evidence comes from a federated query

**The problem it solves.** HomeTruth exists because rental facts are fragmented. The rent is on the listing, the aspect is on the floor plan, the pet rule is in the strata by-laws, the market rent is in government bond data, and the commute comes from transit data. Zetaris lets one search run over all of those sources together, and it gives every claim a query receipt.

**How it is wired.**

1. Our server publishes each evidence source as JSON at `/api/zetaris/<source>`. There are seven sources: `listings`, `photo_facts`, `documents`, `public_rent`, `public_transit`, `sun_geometry` and `floorplan_facts`. Each row has an `evidence_id`, which is a hash of the evidence content, so both sides agree on it.
2. `scripts/zetaris/10_register_hometruth.sql` sets up Zetaris:
   - It creates a Lightning database, `HOMETRUTH_SRC`, with seven **REST tables** that point at those URLs.
   - It creates seven views, `hometruth.<source>`, which flatten the JSON with `LATERAL VIEW explode(items)`.
   - REST tables re-fetch on every query, so the data stays with us and Zetaris queries it in place. No copy and no bucket are needed.
3. When a renter starts a search, `src/voice/zetaris_live.py` sends seven SQL queries in parallel, one per source. Each query is `SELECT evidence_id, listing_id, dim, fact FROM hometruth.<source> WHERE listing_id IN (<this search's candidates>)`.
4. Every returned evidence row is tagged with the query it came from. The UI shows this in two places:
   - The source panel shows "7/7 · via Zetaris" with real row counts and timings.
   - Each evidence row reads "Zetaris query a906b00b". Hover over it to see the full query id, the time and the SQL.

**Measured on the hosted server.**
- Each query takes 1.4–2.5 s.
- All seven sources are lit about 3 s after the voice starts.
- In the measured search, 21 of 21 evidence rows came via Zetaris.
- The row counts of all seven views match our endpoints exactly.

**When Zetaris is slow or down.**
- If a source times out, the search uses that source's last successful query, and the page marks it *earlier*.
- If a source has never answered, the page marks it *failed* and its evidence *local copy*.
- Every query is logged to `runs/zetaris_log.jsonl`, and `/api/hello` reports the query and success counts.

## Meterless: runtime provider, memory and versioned beliefs

**Runtime provider.**
- `src/llm/provider.py` is the only way the app reaches a model. It implements the "Add Meterless as a provider" Power Prompt (Meterless Runtime 1.4, provider contract v4):
  - It exposes three settings: base URL, runtime token and routing mode (`meterless/auto`).
  - It runs four checks: connection, authentication, model discovery and a text request.
  - **Meterless Runtime (Nightshift) is the default provider.** If it isn't running, the call goes to NVIDIA directly.
- Every call appends a line to `runs/llm_log.jsonl`. The line records the provider, the model, a prompt hash, the latency and the tokens. It never records a key.
- In Nightshift, Lane 1 runs **Nemotron 3.5 Lightning**. On 25 Oct, `scripts/check_nvidia.py` passed 16 of 16 checks, and `meterless/auto` was confirmed to reach `nvidia/nemotron-3.5-lightning-30b-a3b` through Nightshift.

**H-MEM-style memory** (`src/voice/memory.py`).
- The app remembers each renter's needs and shortlist across visits.
- The next visit opens with "Welcome back". It then says what changed while you were away (agent replies that arrived), what is still open and what is on file.
- **Forget me** deletes all of it.

**World-Model-style beliefs** (`src/voice/beliefs.py`).
- Every cell of every home is a versioned belief. v1 is what the sources said at search time. v2 comes after an agent reply, and so on.
- Each version records who changed it (a pasted reply, or one that arrived in the inbox while you were away), in which session, when, and the ranking before and after.
- The log is append-only, and a reply with the same event id is applied only once, so replaying never doubles an action. The Changes panel replays this log.

We implemented H-MEM and World Model in Python from the Meterless specifications. We did not use the TypeScript reference package.

**Honest note.** Nightshift is a desktop app. It runs on our laptop, not on the server. So the hosted demo's model calls go to NVIDIA directly, and each call is logged as `direct NVIDIA (Meterless no_token)`. Run the same code locally with Nightshift open and the calls go through Meterless.

## NVIDIA: Nemotron does the reading, Riva does the listening

Every model call checks what the model returns. If a check fails, the app falls back to rules or templates, so a model can never add a fact.

**Nemotron 3.5 Lightning** (`nvidia/nemotron-3.5-lightning-30b-a3b`) does five text jobs:

| Task | What Nemotron does | What we check |
|---|---|---|
| `needs` | turns the renter's sentence into a checklist (budget, bedrooms, commute target, move-in date, pets and extras) | values checked against rules; anything missing is asked for, never guessed |
| `intent` | when the rules aren't sure, decides what an interruption means: skip, a question about this home, a new need, stop, and so on | must be one of the known intents |
| reply reading | reads an agent's reply and decides which cell it answers, the new state and the quote that settles it | the dimension must be on the checklist; the state must be one of four; the quote must be an exact substring of the reply; no numbers that aren't in the reply |
| `narrate` | rewrites template sentences into natural speech | only numbers from the facts; state words kept; no added facts; otherwise the template is used |
| `polish_ask` (off by default) | smooths the wording of a clarifying question | must still be one question, keep every field it asks about, and add no numbers |

**Nemotron 3.5 Super VL** (`nvidia/nemotron-3.5-super-vl-120b-a12b`) does the vision jobs:

- **Listing photos** (`photo_facts`): room type, condition and the visible signs of it, and whether fittings look new or old. These fill photo-backed cells, and every one is labelled with the model that read it.
- **Floor plans** (`floorplan_facts`): the north arrow and which wall has the main window, which together give the aspect, plus a few layout facts. The model only says what it sees, and rules decide the state. These facts feed the sun-and-aspect check.
- **3D plan** (`plan3d_rooms`, `plan3d_photo`): names the numbered regions of a segmented floor plan, and places each photo in its room.
- **Style match** (`style`): reads the renter's reference photos and the listing photos into the same finish attributes, such as floor, palette, kitchen, light and era. The result is a soft preference and never affects the ranking.

**Riva speech** (real-time voice version, `src/voice/pipecat_app.py`, Pipecat over WebRTC):
- **Parakeet** (`parakeet-ctc-1.1b-asr`) does speech recognition.
- **Magpie** (`magpie-tts-multilingual`) is the NVIDIA voice. The hosted demo uses an ElevenLabs voice instead.

## Cursor

We did not use Cursor. Rule 5.1 makes it optional.

## What's unique

- **Evidence-first speech.** The voice only says what is in the evidence matrix. Every "why it fits" sentence comes from one cell, and that cell's evidence row carries its Zetaris query id. The model may smooth the wording but can't add a fact, and code checks every rewrite.
- **Four honest states, with unknowns turned into questions.** Most tools hide what they don't know. HomeTruth shows it and gives you the question to ask the agent.
- **Answers change the world model.** An agent's reply becomes a new version of a belief, with the quote and the rank change. You can see exactly why a home moved up or down.
- **An interruptible voice tour.** It handles "skip", "what about parking?" and "it also needs to be furnished" mid-sentence, and re-plans without repeating what you've already heard. In our simulation of 21 scripted renters, it handled 15 of 15 interruptions as meant.
