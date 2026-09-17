# FUN Challenge submission — Ya Hakim

Deadline: **Thursday 17 September, 23:59. No extensions.**

---

## Project description (137 words — the form caps at 150)

> **Ya Hakim** — Arabic for *"hey, doctor."*
>
> A patient appears on the projector. The room interrogates him from their
> phones — typing or just talking. He is proud, funny, and hiding one thing, and
> the heart monitor catches him lying before anyone else does. Waste time and he
> deteriorates. At zero he flatlines, the room falls silent, and the case file
> opens: what he hid, who caught the lie, what nobody asked and why it
> mattered — with awards for the room.
>
> The trick: **the diagnosis is never sent to the AI.** You can open the exact
> prompt and search it — zero matches. 100 jailbreaks prove it, then the
> audience attacks it live on the big screen.
>
> The same engine is a clinical-reasoning simulator for medical schools, with
> AI debriefs cited against real guidelines.
>
> 311 tests. Plays with no internet.

---

## The three-minute demo

Rehearse this. The timings are the point — especially the silence.

| Time | What happens | What you say |
|---|---|---|
| 0:00 | Title card on the projector | "Ya Hakim. There's a man in that bed and he will not tell you what's wrong with him." |
| 0:10 | QR up, crowd joins | "Scan that. You're the doctors. Type, or just hold the mic and talk to him." |
| 0:30 | Questions land, he deflects | *say nothing, let him be funny* |
| 0:50 | Someone asks about drinking. **Point at the monitor** — the card flares *he's lying* | "He just said two glasses. Watch his heart rate." **96 → 114.** "He's lying." |
| 1:20 | Vitals go amber, then red | "Nobody's asked about his eyes yet." |
| 1:45 | **FLATLINE.** Red jolt. Tone. Colour drains. | *stop talking* |
| 1:50 | **Two seconds of silence** | *do not fill it* |
| 1:53 | **The case file.** His lie crossed out, the truth under it, who caught it, what nobody asked | "That's who caught the lie. And that's the question nobody asked — the one that would have saved him." |
| 2:05 | Awards pop in | Read one out. *Let the room laugh at "Bedside manner, no bedside point".* |
| 2:15 | Switch to `/prove`, hit **Run the 100** | "His diagnosis was never in the prompt. 100 jailbreaks." Counter climbs. **0 leaks.** |
| 2:30 | Press **X-ray the prompt**, type **liver** | "This is every word the AI is told. Search it." **0 matches.** "It can't leak what it never had." |
| 2:45 | QR on screen | "Your turn. Try to make him say it." Crowd attacks live. |
| 2:55 | Flash `/app` for five seconds | "And the same engine trains medical students." |

**Do not** open with the SaaS dashboard. Open with the man in the bed.

**No crowd?** Open `/screen?demo=1`, click once for sound, and the whole round
plays itself in a minute — named doctors, the lie, the confession, a correct
call, the flatline and the case file.

---

## Why this wins on their rubric, not on features

| Criterion | Weight | Our play |
|---|---|---|
| Functionality | 20% | 311 tests, CI green, works offline |
| Creativity & Originality | 20% | The answer is never in the prompt — you can read the prompt, search it, and attack it |
| **Entertainment / Fun** | 20% | A room shouting (literally — voice) at a dying man; the flatline; awards |
| **Demo Presentation** | 20% | Scripted above. The silence does the work |
| Impact / Usefulness | 20% | The case file teaches what was missed and why; the school simulator, third act |

The competition optimises for the last row. Four of the five rows reward
theatre, and that is where we spend the stage time.

---

## Before you submit

- [ ] `ANTHROPIC_API_KEY` in `.env` — three features are dead without it
- [ ] Deploy, or record the video (the form needs a live URL **or** 1–3 min video)
- [ ] Open `/`, `/app`, `/practice`, `/prove` and actually look at them
- [ ] Test `/attack` on a real phone
- [ ] Team name + project name
- [ ] Repo link: https://github.com/hamdanyasser/ya-hakim

## Pages

| Route | What it is |
|---|---|
| `/screen` | The projector game |
| `/play` | Phone controller for the game |
| `/prove` | **The proving ground** — corpus + live audience attacks |
| `/attack` | Phone page for attacking the patient |
| `/app` | The school product |
| `/practice/{id}` | A solo clinical encounter |
