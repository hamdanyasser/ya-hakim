# Ya Hakim

**Clinical reasoning practice with patients who hide things.** A browser-based
simulator for medical and nursing schools: a learner interviews a patient with a
personality and a secret, examines, orders investigations, treats, commits to a
diagnosis and plan — and an attending debriefs them against published
guidelines. Plus a classroom mode: one projector, a room of phones, one patient,
a 150-second clock.

**This is an education tool with synthetic patients. It is not a medical
device, not clinical decision support, and not medical advice.**

---

## What is in the box

| Surface | For | What it does |
|---|---|---|
| `/` | Everyone | The site: what it is, how it works, pricing. |
| `/app` | Schools | Accounts, cohorts, assignments, the case library, the encounter, the debrief, dashboards, the case editor (with AI drafting), billing. |
| `/screen` + `/play` | A lecture theatre | Classroom mode: projector + phones, a three-patient campaign with a leaderboard. |

Three built-in cases (decompensated alcoholic liver disease, diabetic
ketoacidosis, carbon monoxide poisoning), each written to current published
guidance and validated on every commit. Schools write their own; a case
publishes only when it passes the same checks.

## The one rule this project is built around

**The diagnosis never reaches the model.** A case file's `diagnosis`,
`accepted_answers`, `partial_answers`, `key_questions` and `key_keywords` never
enter a prompt, a client payload before the debrief, a log a learner can see,
or a URL. The prompt is built from an **allowlist** — fields are copied *in* by
name (`ALLOWED_IN_PROMPT` in `engine/patient.py`), so a field added next week
cannot leak. An output guard checks every reply anyway. `tests/test_no_leak.py`
proves all of it, including with a canary field injected into every case.

Two consequences worth knowing:

- **Exam findings and results are revealed only by an action** (examining,
  ordering) and are meant to point at the answer — that is clinical reasoning.
  They may never *name* it; that is tested.
- **The debrief cites guidance by id from a curated registry**
  (`engine/guidelines.py`: NICE, RCEM, BSG, EASL, ESC, AHA, JBDS, ADA, GINA,
  GOLD, BTS, Resuscitation Council UK, UK NPIS, GMC). The model chooses ids; the
  engine resolves them. A source not in the registry cannot be cited.

## Running it

Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**, click *Start free*, create your school. That
account is the admin; invite instructors from *Admin*, create a cohort and share
its invite link with learners.

Copy `.env.example` to `.env` for the live model (`ANTHROPIC_API_KEY`) and for
billing (`STRIPE_*`). **Both are optional.**

- **No model key:** the patient has a scripted voice built from the same
  allowlisted material; the debrief still marks every line of the mark sheet.
  This is the development path and what CI runs.
- **No Stripe keys:** every school is on the free plan (5 seats, every feature).

Docker: `docker compose up --build` (data in a named volume). Set `APP_URL` in
`.env`; when it is `https://…` session cookies are marked Secure automatically.
`.dockerignore` keeps `.env`, `data/` and local virtualenvs out of the image.
Run a single server process: encounter locks, rate limits and classroom rooms
live in memory.

## How an encounter works

Twelve minutes on the clock. The monitor runs the whole time; untreated, the
patient reaches a critical state at around ten minutes and then arrests.

- **Interview.** Each case has four to six key history topics. Covering one for
  the first time stabilises the patient briefly. The **first** topic is the one
  the patient lies about — press it twice, or ask the person who brought them
  in, and the front drops. While they are lying, **their heart rate spikes on
  the monitor** in front of the learner. An engine-derived **mood** (guarded →
  defensive → rattled → scared → pleading → resigned) shows on screen and, in
  live mode, steers the model's tone.
- **Examine, order, treat.** A generic catalog (`engine/clinical.py`: 14
  examinations, 40 investigations with realistic turnaround, 30 treatments)
  identical for every case, so the menu never gives the diagnosis away. A case
  records only what is abnormal. Key treatments visibly improve the monitor;
  harmful ones set the patient back, and the debrief explains why for *this*
  patient.
- **Commit.** Working diagnosis, differentials, plan, reasoning.
- **Debrief** (`engine/grading.py`). A deterministic mark sheet — data gathering
  40, clinical management 40, communication 20, with outcome modifiers — where
  every point is explained. Then, with a key, a narrative from the attending
  model grounded in that sheet, allowed to re-mark communication within bounds,
  citing the registry by id. Without a key, a checklist narrative.

## For instructors

- **Cohorts** with their own invite links; **assignments** with due dates.
- **Dashboard:** domain averages, diagnosis accuracy, the most-missed questions
  and examinations across the school, harmful treatments given, hardest cases,
  learners who need attention, every debrief on record.
- **Case editor:** duplicate a built-in case, or *Draft with AI* from a one-line
  brief. `cases/schema.md` documents the format. Validation (`engine/authoring.py`)
  runs on every save and gates publishing: the answer must be absent from the
  persona, keyword groups must not collide, every key question needs an offline
  reply that survives the guard, vitals must pass through all three colours.
  *Test-drive* starts an encounter on an unpublished draft.

## Architecture

```
engine/   pure logic, no I/O
  patient.py     the allowlist, the persona, the output guard, live + canned voices
  encounter.py   how a question lands (topic, cracking, the lie) — shared by both modes
  practice.py    the solo encounter: a JSON state document, wall-clock timestamps
  grading.py     the mark sheet + the attending narrative
  clinical.py    the exam / investigation / treatment catalog
  guidelines.py  the citation registry
  authoring.py   case schema, model drafting, validation
  mood.py vitals.py scoring.py game.py state.py llm.py
server/   FastAPI
  main.py        pages + classroom endpoints;  api_auth.py  api_practice.py  api_org.py
  db.py          SQLite (WAL), one file, no ORM;  auth.py  billing.py  rooms.py  ws.py
web/      vanilla HTML/CSS/JS, no build step
  index.html app.html app.js practice.html practice.js debrief.js app.css
  screen.html screen.js play.html play.js ecg.js room3d.js style.css   (classroom)
cases/    the built-in cases + schema.md
tests/    311 tests, no key, no network
```

Encounter state and debriefs are stored as JSON documents in SQLite; a faculty's
worth of concurrent learners runs on one small VM, and the schema moves to
Postgres without redesign when a customer needs it.

Model: `claude-opus-5` by default (`YH_MODEL` to override), with server-side
refusal fallbacks so a declined turn never ends an encounter. Patient replies use
prompt caching on the persona and low effort for latency; the debrief and case
drafting use structured outputs and high effort.

## Tests

```bash
pytest -q
```

- `test_no_leak.py` — the allowlist guarantee, the canary, the output guard, the
  offline dialogue, the `GameState` contract.
- `test_practice.py` — the solo engine: chart and view carry no secrets, key
  history stabilises and cracks, results arrive after turnaround, arrest and
  time-up, key treatments help and harmful ones set back, the mark sheet scores
  a perfect run high and an empty one low, partial credit, offline debrief
  cites only the registry, arrest caps the score, results never name the
  diagnosis.
- `test_api.py` — the HTTP layer through the real app: malformed input is a 400,
  sign-in is rate limited, seats are enforced under concurrent joins, learners
  cannot reach staff pages or other schools, concurrent encounter actions are
  not lost, a double submit grades once, editing a case does not change an
  attempt in progress, the Stripe webhook applies a signed event, only the
  projector can control a classroom round, idle rooms are reaped, the proving
  ground is paced.
- `test_vitals.py`, `test_mood.py`, `test_redteam.py`, `test_injection.py`
  (100 attacks; `YH_LIVE=1` runs them against the real model).

## Security notes for deployers

Sessions are opaque random tokens stored server-side in an HttpOnly,
SameSite=Lax cookie; all mutating endpoints take JSON. Passwords are scrypt.
Stripe's webhook is the only thing that changes a school's plan. Set
`APP_URL` to your `https://` address (cookies become Secure; override with
`YH_SECURE_COOKIES=0/1`). Instructors can read any debrief in their school;
learners only their own. Patient prompts contain no learner identifiers.

Sign-in is limited per account (10 attempts / 5 min) and, generously, per
address — a cohort usually shares one campus address. The public proving
ground has a per-address pace and an hourly ceiling on live model calls, and
AI case drafting is limited per school. Put the app behind a reverse proxy that
sets `X-Forwarded-For` (uvicorn runs with `--proxy-headers`) so limits see real
client addresses.

## Classroom mode

Unchanged from the party-game origins and still the best way to open a session:
`/screen` on the projector (`?flat=1` disables the 3D room, `?demo=1` plays the
round on its own), phones join by QR. `K` flatlines on demand for rehearsal,
`R` reloads, `M` mutes the monitor. Cases load from `cases/`.

The projector that opens a room holds its **host key** (kept in that browser's
local storage, so a reload keeps control). Starting, revealing, advancing,
killing and resetting the round need it; phones can only join, ask and guess.
A second screen opened on the same code can watch but not drive the round.

When the round ends the reveal opens a **case file**: the lie crossed out with
the truth beneath it, who drew the lie out and who got the truth, the key
questions nobody asked with why each would have mattered, a teaching pearl, and
awards for the room. It is built only in the reveal payload, after the diagnosis
is public. Phones and the projector take **voice** where the browser supports
speech recognition, and each patient speaks with a voice that fits them.

`/prove` has an **X-ray**: the exact system prompt the model receives, before
and after the patient cracks, searchable, with every forbidden term counted in
it — all zero, and `test_api.py` keeps it that way.
