# FUN Challenge submission — Ya Hakim

Deadline: **Thursday 17 September, 23:59. No extensions.**

---

## Project description (148 words — the form caps at 150)

> **Ya Hakim** — Arabic for *"hey, doctor."*
>
> A patient appears on the projector. The whole room interrogates him from their
> phones. He is proud, funny, and hiding exactly one thing — and the heart
> monitor catches him lying before anyone else does. Waste time and he
> deteriorates. At zero he flatlines, the room goes silent for two full seconds,
> and the diagnosis is revealed.
>
> The trick underneath: **the diagnosis is never sent to the AI.** Case fields
> are copied into the prompt by allowlist, so the answer is structurally absent
> — not filtered out, never present. We ship 100 adversarial attacks proving it.
> At the festival, the audience gets to try: every jailbreak they type goes on
> the big screen, HELD or LEAK.
>
> The same engine is also a clinical-reasoning simulator for medical schools.
>
> 281 tests. Plays with no internet.

---

## The three-minute demo

Rehearse this. The timings are the point — especially the silence.

| Time | What happens | What you say |
|---|---|---|
| 0:00 | Title card on the projector | "Ya Hakim. There's a man in that bed and he will not tell you what's wrong with him." |
| 0:10 | QR up, crowd joins | "Scan that. You're the doctors." |
| 0:30 | Questions land, he deflects | *say nothing, let him be funny* |
| 0:50 | Someone asks about drinking. **Point at the monitor** | "He just said two glasses. Watch his heart rate." **96 → 114.** "He's lying." |
| 1:20 | Vitals go amber, then red | "Nobody's asked about his eyes yet." |
| 1:45 | **FLATLINE.** Tone. Colour drains. | *stop talking* |
| 1:50 | **Two seconds of black silence** | *do not fill it* |
| 1:53 | Reveal card | "He died. Someone got it right." |
| 2:05 | Switch to `/prove` | "Now the part I actually care about." |
| 2:15 | Hit **Run the 100** | "His diagnosis was never in the prompt. Here's 100 jailbreaks proving it." Counter climbs. **0 leaks.** |
| 2:35 | QR on screen | "Your turn. Try to make him say it." Crowd attacks live. |
| 2:50 | Flash `/app` for five seconds | "And the same engine trains medical students. That part's free for schools." |

**Do not** open with the SaaS dashboard. Open with the man in the bed.

---

## Why this wins on their rubric, not on features

| Criterion | Weight | Our play |
|---|---|---|
| Functionality | 20% | 281 tests, CI green, works offline |
| Creativity & Originality | 20% | The answer is never in the prompt — and we let you attack it |
| **Entertainment / Fun** | 20% | A room of 200 shouting at a dying man; the flatline |
| **Demo Presentation** | 20% | Scripted above. The silence does the work |
| Impact / Usefulness | 20% | The school simulator, third act |

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
