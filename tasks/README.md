# Who is building what

Two developers, two building days. Tuesday and Wednesday. Thursday is the
dossier, the deck and rehearsal — **no new features on Thursday.**

- [`eddy.md`](eddy.md) — the console, the AI layer, the demo and the pitch
- [`dev-2.md`](dev-2.md) — hardware, history, the patient dialogue, scenarios

## The rule that stops you fighting over files

Each of you owns files nobody else edits. The contracts between them are already
written and tested, so neither of you is blocked waiting for the other.

| Owner | Files |
|---|---|
| **Eddy** | `web/**`, `server/ai/**`, `docs/pitch.md` |
| **Dev 2** | `server/sensors/**`, `server/db.py`, `server/quarantine.py`, `scenarios/**`, `tests/**` |
| **Shared — discuss before editing** | `server/app.py`, `server/triage.py`, `config.toml` |

If you need something changed in a shared file, say so rather than editing
around each other. `server/triage.py` in particular is tested and demoed — it
should not need to change at all.

## Working agreement

- Branch per task: `git checkout -b feat/3d-console`
- Push often. A branch nobody can see is a branch nobody can help with.
- Run the tests before you push: they take two hundredths of a second.
- **Wednesday evening is feature freeze.** Record the demo run that night.

## The architecture rule

Nothing in `triage.py`, `sensors/` or `db.py` may import from `ai/`. The whole
design — and four marks on Axe 4 — rests on the AI never being in the
measurement path.
