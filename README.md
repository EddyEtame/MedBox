# MedBox

**Autonomous medical station for a ship with no doctor and no contact with Earth.**

EPSI Workshop B3 2026-27 — *Horizon 2080* — Pillar 1 (HumanTech & HealthTech), option A.

MedBox is a medical case with sensors and a local AI. It reads a crew member's
vitals, scores how urgently they need attention, manages quarantine during an
outbreak, and keeps a medical history — entirely offline, with no cloud, no
account and no internet connection at any point.

> **This is a research and education instrument. It is not a medical device and
> it does not diagnose.** It offers ranked hypotheses and an urgency level
> computed from a published clinical score, and every claim it makes can be
> traced back to the reading that produced it.

---

## Quick start

**Linux / macOS**
```bash
./setup.sh
.venv/bin/python medbox.py
```

**Windows**
```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
.\.venv\Scripts\python medbox.py
```

Then open <http://127.0.0.1:8080>.

**If you are here to use the station rather than build it, read
[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).** It is the operator's guide, and
it is generated from the product by `python tools/guide.py`, so it cannot
describe a MedBox that does not exist. The same facts are on the Help button
inside the console, which keeps working with the assistant killed.

`setup` creates the virtual environment, installs pinned dependencies, installs
and version-checks Ollama, pulls the model, creates the database and runs the
tests. It is safe to run again at any time — every step checks before it acts.

**On Windows it takes two passes.** Ollama ships as an installer. Setup asks
before fetching it — it is 1.2 GB — and the default is No, so nothing large is
downloaded behind your back. Say `y` and it downloads, launches the installer
and stops. Finish the installer, then run `setup.ps1` again: the second pass
finds Ollama and pulls the model. You never need to type `ollama` yourself,
which is just as well, because its installer does not add itself to the PATH
of a PowerShell window that was already open.

Answer that prompt in advance with `-y`:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -y
```

Use it whenever setup is not looking at a terminal — piping the output to a
file, running it from an editor, running it unattended. Without `-y` in those
cases setup declines the download and says so, rather than asking a question
into a log file and waiting forever for an answer.

In a hurry, or on a network that will not carry it? `python setup.py --no-ollama`
skips both downloads. Everything works except the narration, which is the point
of the next section. (A plain `python` is right here — `setup.py` uses only the
standard library, because it is what runs before anything is installed.)

### Hold-to-speak (optional)

The station always talks — the clips are in the repo and need nothing
installed. To let it *listen*, fetch the speech model once:

**Linux / macOS**
```bash
.venv/bin/python tools/assets.py
```

**Windows**
```powershell
.\.venv\Scripts\python tools\assets.py
```

Run it from this folder, the one holding `setup.py`, and use the interpreter
inside `.venv` — a bare `python` has none of the dependencies and will tell you
faster-whisper is missing when it is sitting right there.

No network in the room? Copy `models/faster-whisper-base` (a folder, or a zip
of it) onto a USB drive and use `--from /path/to/the/drive`. Either way the
microphone button stays hidden until a complete model is present, and typing a
symptom works throughout.

---

## The one design decision

**The AI never touches a measurement.**

Two tracks run side by side:

| | Fast track | Slow track |
|---|---|---|
| **Does** | sensors → NEWS2 score → screen | hypotheses, questions, protocol |
| **Speed** | milliseconds, every tick | hundreds of milliseconds, on demand |
| **Model** | none, anywhere | Ollama, schema-constrained |
| **If it fails** | it doesn't — it has no dependencies | the narration stops, nothing else |

Kill Ollama mid-consultation and the vitals keep updating, the triage ordering
holds, quarantine still works and the session keeps recording. Only the
narration stops. That is what "standalone" has to mean: not merely no internet,
but no single process whose death takes the instrument down.

**The rule that keeps it true:** nothing in `server/triage.py`,
`server/sensors/` or `server/db.py` may import from `server/ai/`. If you ever
need to, the design has drifted — stop and fix it instead.

---

## Urgency is NEWS2, not something we invented

`server/triage.py` implements the National Early Warning Score 2 (Royal College
of Physicians, 2017), the score used across the NHS to decide how urgently a
deteriorating patient must be seen.

We measure four of its seven parameters — temperature, SpO₂, pulse and
respiration — and every result carries the list of parameters actually measured,
so the screen never implies more confidence than the hardware earned.

Using a real clinical standard means the urgency level is deterministic,
explainable, defensible, and works with the AI switched off.

---

## Layout

```
medbox.py              entry point — python medbox.py
setup.py               cross-platform installer (Windows + Linux)
config.toml            everything configurable, in one file

server/
  app.py               FastAPI: API, WebSocket and the UI, one port
  triage.py            NEWS2 scoring — pure functions, no I/O      [FAST]
  quarantine.py        zone assignment rules                        [FAST]
  bus.py               pub/sub to every connected screen            [FAST]
  db.py                SQLite: roster, readings, events, history    [FAST]
  sensors/
    synthetic.py       scenario-driven crew — the demo source       [FAST]
    serial_head.py     real ESP32 over USB                          [FAST]
  ai/
    ollama.py          client that is allowed to fail               [SLOW]
    schemas.py         the JSON shape the model must return         [SLOW]

web/                   the 2D console (always works — the fallback)
scenarios/             YAML timelines: demo, tests and training data
tasks/                 who is building what this week
tests/                 pytest

docs/
  USER_GUIDE.md        the operator's guide — GENERATED, do not hand-edit
tools/
  guide.py             builds it; --check fails the suite when it drifts
```

---

## Scenarios

A scenario is a timeline applied to the synthetic crew. The same file drives the
demo, the regression tests and — later — the fine-tuning set.

```bash
curl -X POST http://127.0.0.1:8080/api/scenario/contamination
```

`scenarios/contamination.yaml` is the crisis the brief specifies: six of forty
crew (15%) develop a respiratory infection over ninety seconds. The board
re-orders by urgency, quarantine zones fill and spill, and partway through you
kill Ollama by hand to show the station carrying on.

**Demo from a scenario, never from live sensors.** A rehearsed replay cannot
embarrass you in front of a jury. Live hardware can.

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | version, AI state, available scenarios |
| `GET /api/board` | the full crew board with triage |
| `GET /api/patient/{id}` | one crew member plus their history |
| `POST /api/scenario/{name}` | start a scenario |
| `POST /api/scenario/stop` | reset to nominal |
| `POST /api/assess/{id}` | ask the AI — **503 when it is down, by design** |
| `GET /api/interconnect/health` | crew health summary for other ESA teams |
| `WS /ws` | live telemetry |

`/api/interconnect/health` carries no names and no per-person readings. Another
team's power grid needs to know a zone is sealed and how many crew are down —
not who.

---

## Tests

```bash
.venv/bin/python -m pytest tests/ -q      # Linux
.\.venv\Scripts\python -m pytest tests\ -q  # Windows
```

The triage tests matter more than they look: the score is what the jury sees and
what quarantine keys off, so a silent regression changes the demo's behaviour
without anything visibly breaking.
