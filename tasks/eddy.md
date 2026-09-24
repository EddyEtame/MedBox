# Eddy — the console, the AI, and the five minutes

You own what the jury sees and what wins the differentiation marks. At the
national final, *Innovation & différenciation* is 20 points and *Pitch &
démonstration* is 20 — forty of seventy decided by your half of this list.

**Your files:** `web/**`, `server/ai/**`, `docs/pitch.md`
Everything else belongs to Brad. Ask before touching `server/app.py`.

---

## E1 — The 3D console — Tuesday afternoon into Wednesday
**The single biggest differentiator. Nothing else on this list beats it.**

Three.js on top of the same `/ws` socket the 2D board already uses. The data is
already flowing and already correct; this is a second view onto it, not a rewrite.

- The ship's hull thermal shading driven by the real aggregate crew state, with
  the fever threshold as a visible waterline.
- Each crew member is a point in a bay. Urgency drives colour, using the same
  four bands the board uses so the two views can never disagree.
- Quarantine zones seal visibly as `quarantine.zones[z].sealed` flips.
- **The provenance flight** — see E2. This is the part that matters.

**Rules that protect you:**
- The 2D board in `web/index.html` must keep working, untouched, as a separate
  view. If WebGL misbehaves on the demo machine on Friday morning you switch
  views and carry on. Never put something on stage that can take the demo down.
- One WebGL context. Instanced geometry for the crew. Hard 16.6 ms frame budget,
  and degrade particles before you degrade frames.

**Done when** you can run `contamination` and watch six bays go red and a zone
seal, at 60 fps, with the 2D board still one click away.

---

## E2 — Provenance flights — Wednesday
**This is the idea that makes the 3D load-bearing instead of decorative.**

Every claim the AI makes is anchored to the instrument that produced the
evidence. The model says *elevated temperature with falling oxygen in bay four* —
you click that sentence, the camera flies to bay four, and the raw trace is
there at the sensor.

The AI structurally cannot say anything the ship cannot show you the source of.

It is also your answer to the hardest question you will get in the Q&A:
*"how can you trust a small local model with a medical opinion?"* — you don't
have to, because every sentence traces to a measurement in one click, and the
urgency ordering is deterministic anyway.

**Done when** clicking any hypothesis flies the camera to the sensor behind it.

---

## E3 — Make the AI good — Tuesday
`server/ai/schemas.py` holds the system prompt and the JSON schema. The plumbing
works; the quality is yours.

- Tune `SYSTEM_PROMPT` until the hypotheses are specific and the questions are
  ones a real medic would ask. Iterate against `single-patient` scenario.
- The model must never produce diagnosis language. Test it adversarially — feed
  it an obvious case and try to make it say "this is pneumonia".
- Keep responses short. The person reading may be treating someone.
- Watch latency. If first token is slow on the demo machine, drop to a smaller
  model in `config.toml` rather than accepting a laggy demo.

**Done when** ten runs in a row give useful, non-diagnostic, fast answers.

---

## E4 — The self-explaining guide — Wednesday
Your idea, and it is worth real marks on Axe 5.

Rather than a static help page, the assistant explains its own capabilities.
Declare every capability and its trigger phrases in one manifest, have the
router read it, and generate the guide from the same file. Add a capability and
the guide has already documented it, because there is no second copy to forget.

Phrase shortcuts worth having: *"start a check"*, *"what's my temperature"*,
*"who is worst"*, *"seal the zone"*, *"replay the last session"*.

**Done when** adding a capability makes the guide describe it with no
documentation written.

---

## E5 — Cough detection — Wednesday, only if E1 and E2 are done
Microphone → log-mel frames → small classifier → an event on the fast track.
No LLM anywhere near it.

Public datasets exist so you do not record your own: **COUGHVID** (~25k
crowdsourced coughs, EPFL) and **Coswara** (IISc Bangalore). AudioSet already
carries a labelled cough class.

**Cut this without regret if the 3D is not finished.** A cough counter is worth
less than a console that baffles them.

---

## E6 — The demo and the pitch — Thursday
**This is worth more than any feature and it is the thing teams skip.**

- Write `docs/pitch.md`: the five minutes, minute by minute.
- **Minute 1 is the team introduction, individually, in English. It is mandatory.**
  Write it out and learn it. It is the first impression the jury gets.
- Rehearse against a stopwatch. At the national final, overrunning cuts the stream.
- **Record the demo video on Thursday** while everything still works. The
  national round allows no live demo, only video.
- Rehearse killing Ollama on stage. That fifteen seconds is your Axe 4 mark.
- Write down the three answers you will need:
  - *Why not Open WebUI?* — "Because a triage station is not a chat window.
    When fifteen percent of the crew is down, nobody is typing prompts."
  - *How can you trust a local model medically?* — E2 is the answer.
  - *What happens when a sensor lies?* — measured-vs-assumed is already in the
    triage output. Show it.

**Done when** the run-through fits in five minutes, twice running.

---

## Order of work

1. **E3** Tuesday morning — short, and it unblocks judging the AI's quality
2. **E1** Tuesday afternoon and Wednesday morning — the big one
3. **E2** Wednesday — the idea that makes E1 count
4. **E4** Wednesday evening if E1 and E2 are solid
5. **E5** only if everything above is genuinely done
6. **E6** Thursday, all day, no exceptions
