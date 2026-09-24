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
| **Eddy** | `web/**`, `server/ai/**`, `server/symptoms.py`, `tools/**`, `docs/pitch.md` |
| **Brad** | `server/sensors/**`, `server/db.py`, `server/quarantine.py`, `scenarios/**` |
| **Shared — discuss before editing** | `server/app.py`, `server/triage.py`, `config.toml` |

Tests belong to whoever owns the code they test, not to one person. A test is
how you say what your own module promises, and handing that to someone else
means the promise gets written by whoever understands it least. So
`tests/test_triage.py` and the sensor and quarantine tests are Brad's, the AI
and console tests are Eddy's, and neither of you needs permission to add one.

If you need something changed in a shared file, say so rather than editing
around each other.

`server/triage.py` is tested and demoed and should change as little as
possible. It has changed once, on 21 September: `to_dict()` now also reports
`single_param_3` and `worst_param`. Nothing about the scoring moved. Those two
go into the AI prompt, because a model told only "aggregate 3, band medium"
sees a small number beside a serious word and writes "a low aggregate of 3,
overall reassuring" underneath a MEDIUM band. It has to be given the reason,
not just the number.

## Working agreement

- Branch per task: `git checkout -b feat/3d-console`
- Push often. A branch nobody can see is a branch nobody can help with.
- Run the tests before you push: they take two hundredths of a second.
- **Wednesday evening is feature freeze.** Record the demo run that night.

## The architecture rule

Nothing in `triage.py`, `sensors/` or `db.py` may import from `ai/`. The whole
design — and four marks on Axe 4 — rests on the AI never being in the
measurement path.
