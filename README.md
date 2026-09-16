# Ya Hakim

A live multiplayer medical mystery for a room of people.

A patient appears on a projector. Players join from their phones by QR code and
ask him questions in plain language. He answers in character — evasive, joking,
hiding exactly one thing. A heart monitor runs the whole time. Good questions
stabilise him; wasted time makes him deteriorate. If the clock reaches zero he
flatlines, the room goes quiet, and the diagnosis is revealed with a leaderboard.

**This is a party game. It is not a medical tool, it is not medical advice, and
nothing it says should be used for any clinical purpose.** The cases are written
to be fun, not to be right.

---

## The one rule this project is built around

**The diagnosis never reaches the model.**

A case file contains `diagnosis`, `accepted_answers`, `key_questions` and
`key_keywords`. None of them may enter a prompt, a client payload, a log a
player can see, or a URL.

This is an **allowlist**, not a denylist. Fields are copied *in* by name:

```python
ALLOWED_IN_PROMPT = ["name", "age", "personality", "symptoms",
                     "lie", "truth", "cracks_when", "red_herrings"]

def build_persona(case):
    fields = {k: case[k] for k in ALLOWED_IN_PROMPT}   # copy IN, never filter OUT
```

A field added to a case file next week is not copied, so it cannot leak. There
is no filter to forget to update. `tests/test_no_leak.py` proves this by
injecting a canary field into every case and asserting it never appears.

Two further guarantees:

- **`truth` is not in the prompt until it is earned.** The engine counts how
  many times he has been pressed and only then swaps `lie` for `truth`. On the
  first question the truth is not in the payload at all.
- **`GameState` is constructed field by field.** The room object is never
  serialised and stripped — that is the pattern that leaks, because a field
  added later is included by default.

There is also an **output guard**: the model may not be *told* the diagnosis,
but it could still infer it from the symptoms and say it unprompted. Every
reply is checked, on word boundaries, against the secret terms before it
reaches a client. A hit is thrown away and he is nudged back into character.

### Two defects this caught

1. **The spec's own case data leaked.** `cracks_when` shipped as
   `"...asked about his liver..."` — and `cracks_when` is on the allowlist. That
   put `liver`, an accepted answer, straight into the system prompt. Reworded;
   the real trigger now lives in the engine where secrets are safe.
2. **The patient never reached critical.** The specified decline rates needed
   11–15 minutes to cross the critical thresholds in a 150-second round, so the
   red state never appeared and the "never reached critical" bonus was free for
   everyone. `vitals_decline` was retuned; `test_vitals.py` now asserts a round
   passes through all three colours.

---

## Running it

Python 3.10+ (3.10.11 is what this was built on). **Put the venv outside the
project folder** — the project lives in a OneDrive-synced directory and a venv
there means thousands of files syncing, plus occasional file locks mid-demo.

```powershell
python -m venv $env:LOCALAPPDATA\yahakim-venv
& $env:LOCALAPPDATA\yahakim-venv\Scripts\python.exe -m pip install -r requirements.txt
& $env:LOCALAPPDATA\yahakim-venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000/screen** on the projector.

Add `?flat=1` to the URL to disable the 3D room and ship the flat view. That is
the phase-5 kill switch and it touches nothing else.

For the live patient, copy `.env.example` to `.env` and add an Anthropic API
key. **Without a key the game still plays** — see below.

### It runs with no key and no network

The patient has a canned offline voice built from the same allowlisted material
the model gets. Everything else — vitals, scoring, the clock, the ECG, the
flatline — never touches the API at all. The model upgrades exactly one thing:
how good his dialogue is.

That was the development path, it is what CI runs, and it doubles as the
insurance policy if the venue has no internet.

### It runs with no phones

`/screen` has an input bar along the bottom. One person types at the laptop and
the whole game plays. This is built in from the start, not bolted on, and it is
the fallback if the venue wifi is hostile.

---

## Demo day

- **Find the right LAN IP.** `ipconfig` will list several adapters; you want the
  Wi-Fi or Ethernet one, not WSL, Hyper-V or a VPN adapter.
- **Windows Defender will prompt** the first time you bind to `0.0.0.0`. Trigger
  that at home, not on stage.
- **Some venue wifi has AP isolation**, which makes phone→laptop impossible no
  matter how correct the code is. Test before you present. The fallback is a
  laptop hotspot the phones join.
- **Keys on the projector:** `K` flatlines on demand (so the sequence can be
  rehearsed without playing a full round), `R` reloads.

---

## Tests

```powershell
& $env:LOCALAPPDATA\yahakim-venv\Scripts\python.exe -m pytest -q
```

- `test_no_leak.py` — the diagnosis is absent from the persona in both cracked
  and uncracked states, absent from server-authored `GameState`, and a field
  invented next week cannot leak. Also asserts the feed cannot mark a question
  as "key", which would hand players the key list one question at a time.
- `test_vitals.py` — decline is monotonic, thresholds fire at exactly the
  specified boundaries, a round passes through all three colours, and
  stabilising pauses decline for exactly 45s including overlapping stabilisations.
- `test_injection.py` — 100 attacks across ten categories (direct ask,
  instruction override, role break, system extraction, false authority,
  hypothetical framing, multiple choice, Arabic, French, encoded text). Prints
  the leak count. Runs offline in CI; `YH_LIVE=1` runs the same 100 against the
  real model, which is what to run on stage.

All tests run with no API key and no network.

**Honest caveat:** the offline injection run exercises the pipeline and the
output guard, not the model's own resistance. The number that matters on stage
is the `YH_LIVE=1` run, and that has not been executed yet because no key was
available during the build.

---

## The campaign

Three patients, hardest last. Scores carry across all three; `guessed` does not,
so every round is a fresh chance to call it.

| Level | Patient | Stakes |
|---|---|---|
| 1 | Kamal, 54 | The trial. His card tells you to watch the monitor. |
| 2 | Rita, 31 | Standard. |
| 3 | Georges, 62 | A wrong call kills him — and the reveal has a twist. |

Each round is 150 seconds. A round passes through all three monitor colours:
green for ~40s, amber to ~120s, then ~30s of red before he goes.

`cases/schema.md` documents the file format, including the trap that
`accepted_answers` double as the words the patient may never say.

## The 3D room

`web/room3d.js`, three.js r128, every shape a primitive. Floor, wall, a bed of
boxes, a form under a sheet that breathes at his respiratory rate, an IV pole,
and a monitor whose screen is a `CanvasTexture` of the *existing* ECG canvas —
the waveform is not rebuilt in 3D.

Lighting is what sells it: ambient fill, a warm overhead spot with soft shadows,
a cool rim light, and a point light at the monitor that tracks his status.
The camera drifts on a slow sine path and freezes during the two seconds of
silence, along with everything else.

There is an fps readout in the corner. Gate 5 is 60fps or delete it — and
deleting it is `?flat=1`, or removing one `<script>` tag.

## What is deliberately not here

No accounts, no database, no payments, no voice input, no character model, no
spectator replays, no difficulty settings, no admin panel. Rooms live in memory
and cases load from JSON on disk.

All visual assets are generated in code — canvas, CSS, primitives. Nothing is
downloaded at runtime and nothing resembles any existing game, film or
character. The ECG waveform, the paper grid, the flatline tone and the room
code alphabet are all original.
