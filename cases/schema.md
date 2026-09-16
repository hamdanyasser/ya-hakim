# Case file schema

A case is one patient, one round. Drop a `.json` file in this folder and the
tests pick it up automatically — every leak and vitals test parametrizes over
whatever is here.

## The split that matters

Fields are in exactly one of two groups, and the difference is the whole
architecture.

**Secret. Never reaches the model, never reaches a client** (except `diagnosis`
at the reveal):

| Field | Type | Notes |
|---|---|---|
| `diagnosis` | string | The answer. Shown only in `phase == "reveal"`. |
| `accepted_answers` | string[] | What counts as a correct guess. **Also doubles as the output blocklist** — see the trap below. |
| `key_questions` | string[] | The topics that buy time. Never shown to anyone. |
| `key_keywords` | string[][] | Parallel to `key_questions`. Player words that match each topic offline. |

**Allowlisted. These and only these are rendered into the prompt** — the list
lives in `engine/patient.py` as `ALLOWED_IN_PROMPT`:

`name`, `age`, `description`, `personality`, `symptoms`, `lie`, `truth`,
`cracks_when`, `red_herrings`

`description` is one or two lines of real-world grounding — job, family,
routine. It goes to the model *and* to the screen (under the patient's name,
and in the phone header), so it doubles as flavour and as UI copy. It is
allowlisted, which means it is checked by exactly the same leak tests as
`personality`: word-boundary-safe against that case's `diagnosis` and
`accepted_answers`, automatically, every run. Write it the way you'd write
`personality` — never medical, never a synonym for the answer. Georges is a
retired boiler engineer; that he spent forty years around heating systems and
still can't see what's poisoning his own house is the point.

**Everything else** (`opening_line`, `canned`, `level_card`, `reveal_note`,
`vitals_start`, `vitals_decline`, `id`) is used by the engine or the UI and is
never rendered into a prompt, because the persona is built by copying
allowlisted fields *in* by name. A field you invent tomorrow is not copied, so
it cannot leak. `test_no_leak.py` proves this with a canary.

## The trap that has already bitten twice

**`accepted_answers` are also the words the patient may never say.** The output
guard blocks them on word boundaries. So an accepted answer that is also an
ordinary word gags the patient.

- Kamal's `cracks_when` originally read *"asked about his liver"* — and
  `cracks_when` is allowlisted, so that put `liver`, an accepted answer,
  straight into the system prompt. Reworded.
- Georges can say **"boiler"** and **"heating"** freely — they are clues and
  asking about them is a key question — but he can never say **"gas"**, because
  that is an accepted answer.
- Rita can say **"sweet"** but never **"sugar"**.

So: keep `accepted_answers` as specific as you can while still being generous
to a non-doctor, then check your `canned` lines against them.
`test_canned_dialogue_never_trips_its_own_guard` does this for you.

## Vitals

```json
"vitals_start":   { "hr": 96, "spo2": 97, "sys": 104, "dia": 68, "rr": 18 },
"vitals_decline": { "hr": 20, "spo2": -4.5, "sys": -12, "dia": -8, "rr": 3.2 }
```

`vitals_decline` is **per minute**. Decline is linear and applies to *effective*
time — the clock keeps running while he is stabilised, but the decline clock
does not.

**Your numbers must make him pass through all three colours inside a 150-second
round.** `test_he_actually_reaches_critical_inside_a_round` enforces this,
because the original Kamal numbers needed 11–15 minutes to reach critical, which
meant the red state never appeared and the "never critical" bonus was free.

Thresholds (in `engine/vitals.py`): critical at `spo2 < 88` **or** `hr > 140`;
declining at `spo2 < 94` **or** `hr > 115`.

A workable shape is stable for ~40s, declining to ~120s, then ~30s of red.

Georges is deliberately an exception: his `spo2` barely moves and `hr` alone
carries him into critical. That is authentic to his case — a pulse oximeter
reads falsely reassuring in carbon monoxide poisoning — and it makes the room
distrust one number, which is good for the game.

## Offline dialogue

`canned` is what the patient says with no API key and no network. It is what CI
runs and the insurance policy if the venue has no internet.

```json
"canned": {
  "<key question verbatim>": "his reply",
  "_whats_wrong": "what he says when asked what he has",
  "_deflect": ["rotated when the question covers nothing"]
}
```

The **first** key question is special: it carries `lie` and `truth`, so it needs
no `canned` entry — the engine serves `lie`, then `truth` once he cracks. Every
other key question needs one. `test_every_key_question_has_keywords_and_a_canned_reply`
checks this.

## Mood

Not a case field — there is nothing to write here. `engine/mood.py` derives a
mood (`guarded`, `uneasy`, `defensive`, `rattled`, `scared`, `pleading`,
`resigned`) from signals the room already has: vitals colour, whether he has
cracked, how many times the one topic has been pressed, and whether the lie
spike is currently active. It is sent to every client in every phase — it
cannot leak, because it never reads a case's secret fields, only the room's
own public state.

It does two things: a badge under the patient's name and age on both screens,
and — live mode only — a short engine-authored behaviour note folded into the
prompt (`MOOD_DIRECTIVES` in `engine/patient.py`), so a bad question landing
mid-lie gets a flustered reply instead of a flat one. The offline voice is
fixed, hand-checked dialogue, so mood does not steer it — only the badge
changes for the canned patient.

## Campaign fields

- `level_card` — three short lines shown on the projector before the round.
- `reveal_note` — one line added to the reveal. Georges uses it for the twist.

## Writing a good case

- **Guessable by non-doctors.** The room is not a medical school. "liver",
  "diabetes", "gas" are the kind of answers that should score.
- **Exactly one hidden thing**, in `lie` / `truth`. Everything else is texture.
- **Symptoms in plain speech.** "belly has been swelling", not "abdominal
  distension". He has never read a textbook and the guard will reject him if he
  sounds like he has.
- **Two red herrings**, both plausible and both dead ends.
- **`cracks_when` is flavour only.** The real trigger is engine-owned, in
  `Room.ask` — it counts how many times the topic has been raised. Keep secrets
  out of this field; it is allowlisted.
