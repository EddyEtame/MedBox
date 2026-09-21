"""The MedBox server: FastAPI, the simulation loop, and the web UI, one process.

Frontend and backend are served from the same origin on the same port. There is
no CORS, no proxy and no second process to start. `python medbox.py` is the
whole system.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, scenarios
from .ai.capabilities import manifest
from .ai.ollama import CLIENT
from .ai.validate import enforce
from .bus import BUS
from .config import CONFIG, ROOT
from .db import Database
from .quarantine import QuarantineRegistry
from .sensors.synthetic import ScenarioSource
from .speech import Announcer
from .voice import TRANSCRIBER
from .symptoms import SymptomLog
from .triage import Urgency, assess

log = logging.getLogger("medbox")
WEB_DIR = ROOT / "web"


def triage_order(row: dict) -> tuple:
    """Sort key for the board: band first, then aggregate, then id.

    NEWS2 escalates any single parameter scoring 3 to medium on its own, so a
    crew member on an aggregate of 3 can need urgent review while someone on 4
    needs only a ward review. Sorting on the raw aggregate alone filed the
    urgent one lower, which is the one mistake a triage board must not make.
    """
    return (
        -Urgency(row["triage"]["urgency"]).rank,
        -row["triage"]["total"],
        row["patient"]["id"],
    )


class MedBox:
    """Holds the live state of the station."""

    def __init__(self) -> None:
        self.db = Database(CONFIG.database.resolved)
        self.source = ScenarioSource(CONFIG.ship.crew_size)
        self.quarantine = QuarantineRegistry(
            CONFIG.ship.quarantine_zones, CONFIG.ship.zone_capacity
        )
        self.db.upsert_patients(self.source.roster())
        # What crew members say, kept apart from what the box measures. The
        # log is handed the recorder rather than importing the database, so
        # nothing in the measurement path depends on it.
        self.symptoms = SymptomLog(on_record=self.db.record_event)
        # Decides what the station says out loud. Fast track only: every line
        # comes from what triage.py and quarantine.py computed, never from the
        # assistant. See server/speech.py.
        self.announcer = Announcer()
        self.latest: dict[str, dict] = {}
        self.scenario: scenarios.Scenario | None = None
        self.scenario_t0: float | None = None
        self._fired: set[int] = set()
        self._task: asyncio.Task | None = None
        self._persist_every = CONFIG.server.board_hz * 2  # write to disk ~2s
        self._tick = 0

    # ---- scenario control -------------------------------------------------
    def load_scenario(self, name: str) -> scenarios.Scenario:
        sc = scenarios.load(name)
        self.source.reset()
        self.symptoms.clear()
        self.announcer.reset()
        self.quarantine.assignments.clear()
        self.scenario = sc
        self.scenario_t0 = time.monotonic()
        self._fired.clear()
        self.db.record_event("scenario_start", sc.name)
        return sc

    def stop_scenario(self) -> None:
        self.scenario = None
        self.scenario_t0 = None
        self._fired.clear()
        self.source.reset()
        self.symptoms.clear()
        self.announcer.reset()
        self.quarantine.assignments.clear()

    def _advance_scenario(self, now: float) -> None:
        if self.scenario is None or self.scenario_t0 is None:
            return
        elapsed = time.monotonic() - self.scenario_t0
        for i, step in enumerate(self.scenario.steps):
            if i in self._fired or step.at > elapsed:
                continue
            self._fired.add(i)
            self._run_step(step, now)

    def _run_step(self, step: scenarios.Step, now: float) -> None:
        p = step.payload
        if step.action == "afflict":
            count = int(p.get("patients", 1))
            pool = self.source.healthy_ids()[:count]
            targets = {
                k: float(v)
                for k, v in p.items()
                if k in ("temperature", "spo2", "pulse", "respiration")
            }
            self.source.afflict(pool, targets, float(p.get("over", 30)), now)
            self.db.record_event("afflict", json.dumps({"patients": pool, **targets}))
            BUS.publish({"type": "event", "kind": "onset", "patients": pool})
        elif step.action == "note":
            BUS.publish({"type": "event", "kind": "note", "text": str(p.get("text", ""))})

    # ---- the fast track ---------------------------------------------------
    def _board(self) -> list[dict]:
        rows = []
        for pid, entry in self.latest.items():
            rows.append(entry)
        rows.sort(key=triage_order)
        return rows

    async def loop(self) -> None:
        """Sample, score, quarantine, broadcast. Never awaits the AI."""
        interval = 1.0 / max(1, CONFIG.server.board_hz)
        while True:
            started = time.perf_counter()
            now = time.time()
            say: list = []
            self._advance_scenario(now)

            for reading in self.source.sample(now):
                v = reading.vitals()
                result = assess(**v)
                patient = self.source.patients[reading.patient_id]
                self.latest[reading.patient_id] = {
                    "patient": {
                        "id": patient.id,
                        "name": patient.name,
                        "role": patient.role,
                        **{k: val for k, val in v.items()},
                    },
                    "triage": result.to_dict(),
                }
                change = self.quarantine.evaluate(reading.patient_id, v, result)
                if change is not None:
                    self.db.record_event(
                        "quarantine", json.dumps(change.to_dict()), reading.patient_id
                    )
                    BUS.publish({"type": "quarantine", "change": change.to_dict()})
                    say.extend(self.announcer.on_quarantine(
                        change.to_dict(), self.quarantine.sealed_zones()
                    ))
                if self._tick % self._persist_every == 0:
                    self.db.record_reading(reading.patient_id, now, v, reading.source)

            if self._tick % self._persist_every == 0:
                self.db.commit()

            rows = self._board()
            say.extend(self.announcer.on_board(rows))
            say.extend(self.announcer.on_ai(CLIENT.available, CLIENT.stand_in))
            BUS.publish(
                {
                    "type": "board",
                    "at": now,
                    "ship": CONFIG.ship.name,
                    "board": rows,
                    "quarantine": self.quarantine.to_dict(),
                    "ai": {"available": CLIENT.available, "error": CLIENT.last_error,
                           "stand_in": CLIENT.stand_in},
                    # Whether this machine can transcribe at all. A microphone
                    # button that appears and then fails is worse than one that
                    # was never offered.
                    "ears": {"available": TRANSCRIBER.available,
                             "error": TRANSCRIBER.last_error},
                    "scenario": self.scenario.name if self.scenario else None,
                    # Usually empty. Only transitions get spoken, because a
                    # station announcing a HIGH band ten times a second is a
                    # station whose sound gets turned off inside a minute.
                    "say": [u.to_dict() for u in say],
                }
            )
            self._tick += 1
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def watch_ai(self) -> None:
        """Poll Ollama so the screen shows its true state within a few seconds."""
        while True:
            await CLIENT.probe()
            await asyncio.sleep(5.0)


STATION = MedBox()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    STATION.source.start()
    loop_task = asyncio.create_task(STATION.loop())
    ai_task = asyncio.create_task(STATION.watch_ai())
    log.info("MedBox %s ready on http://%s:%s", __version__, CONFIG.server.host, CONFIG.server.port)
    try:
        yield
    finally:
        for t in (loop_task, ai_task):
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        STATION.source.stop()
        STATION.db.close()


app = FastAPI(title="MedBox", version=__version__, lifespan=lifespan)


@app.get("/api/status")
async def status() -> dict:
    return {
        "version": __version__,
        "ship": CONFIG.ship.name,
        "crew": CONFIG.ship.crew_size,
        "ai": {
            "available": CLIENT.available,
            "model": CLIENT.model,
            "error": CLIENT.last_error,
            "stand_in": CLIENT.stand_in,
        },
        "ears": {
            "available": TRANSCRIBER.available,
            "error": TRANSCRIBER.last_error,
            "model": str(TRANSCRIBER.model_dir.name),
        },
        "scenario": STATION.scenario.name if STATION.scenario else None,
        "scenarios": scenarios.available(),
        "screens_connected": BUS.subscriber_count,
    }


@app.get("/api/board")
async def board() -> dict:
    return {"board": STATION._board(), "quarantine": STATION.quarantine.to_dict()}


@app.get("/api/patient/{patient_id}")
async def patient(patient_id: str) -> dict:
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    return {
        **entry,
        "history": STATION.db.history(patient_id, limit=120),
        "reported": STATION.symptoms.for_patient(patient_id),
    }


@app.post("/api/patient/{patient_id}/symptom")
async def report_symptom(patient_id: str, body: dict) -> dict:
    """Record something the crew member said.

    This is the only way a human statement enters MedBox, and it enters as a
    quotation. It reaches the assistant as context and the screen as words in
    quotation marks. It does not touch triage: NEWS2 is computed from the
    instruments in the loop above and never reads this.
    """
    if patient_id not in STATION.latest:
        raise HTTPException(404, f"No crew member {patient_id}")
    try:
        entry = STATION.symptoms.add(
            patient_id,
            body.get("text", ""),
            source=body.get("source", "typed"),
            confidence=body.get("confidence"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    BUS.publish({"type": "symptom", "reported": entry.to_dict()})
    return {"reported": STATION.symptoms.for_patient(patient_id)}


# A few seconds of speech is well under a megabyte. The cap is not about disk,
# it is that an endpoint which accepts an unbounded upload from a browser is a
# way to wedge the machine the demo runs on.
MAX_AUDIO_BYTES = 4 * 1024 * 1024


@app.post("/api/patient/{patient_id}/listen")
async def listen(patient_id: str, request: Request) -> JSONResponse:
    """Transcribe a recording and file it as something the crew member said.

    Slow track. It can fail, it can be missing, it can take four seconds, and
    none of that touches a measurement: the board keeps streaming at ten hertz
    throughout because the work happens in a thread.

    What comes back is a guess, and it is stored as one — source "voice" with
    the confidence attached, which the interface shows. An operator acting on a
    misheard symptom should be able to see that it was misheard.
    """
    if patient_id not in STATION.latest:
        raise HTTPException(404, f"No crew member {patient_id}")

    # The raw body, not a multipart form. The browser posts the Blob directly,
    # which means python-multipart is not a dependency — one fewer thing to
    # install on a machine whose only job on Friday is to work.
    raw = await request.body()
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "That recording is too long. Keep it to a few seconds.")
    if not raw:
        raise HTTPException(400, "The recording was empty.")

    # A real file on disk, because PyAV demuxes from a path and a container it
    # cannot seek in is a container it may refuse. Deleted either way.
    tmp = Path(tempfile.gettempdir()) / f"medbox-{uuid.uuid4().hex}.webm"
    try:
        tmp.write_bytes(raw)
        heard = await TRANSCRIBER.listen(tmp)
    finally:
        tmp.unlink(missing_ok=True)

    if heard is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Nothing was transcribed",
                "detail": TRANSCRIBER.last_error or "no speech was found in the recording",
                "note": "Type it instead. Vitals and triage are unaffected.",
            },
        )

    text, confidence = heard
    try:
        entry = STATION.symptoms.add(patient_id, text, source="voice", confidence=confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    BUS.publish({"type": "symptom", "reported": entry.to_dict()})
    return JSONResponse(content={
        "heard": entry.to_dict(),
        "reported": STATION.symptoms.for_patient(patient_id),
    })


# This must be declared BEFORE /api/scenario/{name}. Starlette matches routes
# in declaration order, so with the parameterised route first, "stop" was
# read as a scenario name and the Reset button in both views silently 404'd
# instead of stopping anything.
@app.post("/api/scenario/stop")
async def stop_scenario() -> dict:
    STATION.stop_scenario()
    return {"stopped": True}


@app.post("/api/scenario/{name}")
async def start_scenario(name: str) -> dict:
    try:
        sc = STATION.load_scenario(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"started": sc.name, "description": sc.description, "duration": sc.duration}


@app.post("/api/assess/{patient_id}")
async def ai_assess(patient_id: str) -> JSONResponse:
    """Slow track. Returns 503 when the AI is down — the board is unaffected."""
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    triage = entry["triage"]
    result = await CLIENT.assess(
        entry["patient"], triage, STATION.symptoms.prompt_note(patient_id)
    )
    if result is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI unavailable",
                "detail": CLIENT.last_error,
                "note": "Vitals and triage are unaffected. This is the degraded path working as designed.",
            },
        )

    # Never splat the model's dict into the response. Anything it invented that
    # the schema does not name — a `diagnosis` key, an `escalate` verdict —
    # used to travel straight through to the API surface, hidden only by the
    # fact that no renderer happened to look for it. enforce() rebuilds the
    # answer from the schema's own keys and reports what it took out.
    safe = enforce(result, triage.get("urgency", ""))
    if not safe["ok"]:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI output rejected",
                "detail": "; ".join(safe["blocked"]) or "the assistant returned nothing usable",
                "note": "Vitals and triage are unaffected. A malformed assessment takes the same degraded path as a dead assistant.",
            },
        )

    return JSONResponse(content={
        **safe,
        # Stamped by the server, from what the server knows. An assessment that
        # cannot say which crew member, which score and which moment it was
        # written against cannot be detected as stale by a panel whose band
        # updates ten times a second — and the whole demo is vitals
        # deteriorating while you watch.
        "patient_id": patient_id,
        "news2_at_assessment": triage.get("total"),
        "urgency_at_assessment": triage.get("urgency"),
        "at": time.time(),
        "model": CLIENT.model,
        # From the probe, never from the payload. The flag that tells a jury
        # "this is not a language model" must not be emitted by the thing it
        # is labelling.
        "stand_in": CLIENT.stand_in,
    })


@app.get("/api/assistant/help")
async def assistant_help() -> dict:
    """What this box can and cannot do.

    Served from data the station owns, so the guide survives the assistant
    being killed. When the assistant is up it narrates the same facts in its
    own words; it is the voice, never the source.
    """
    return manifest(ai_available=CLIENT.available, stand_in=CLIENT.stand_in)


@app.post("/api/assistant/introduce")
async def assistant_introduce() -> JSONResponse:
    """Let the assistant introduce itself, from facts it is handed."""
    text = await CLIENT.introduce()
    if text is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI unavailable",
                "detail": CLIENT.last_error,
                "note": "The guide above is unaffected: it is the station's own, not the model's.",
            },
        )
    return JSONResponse(content={"text": text, "stand_in": CLIENT.stand_in})


@app.get("/api/interconnect/health")
async def interconnect() -> dict:
    """Public summary for other ESA teams on the ship.

    Deliberately carries no names or per-person readings: another team's power
    grid needs to know a zone is sealed and how many are down, not who.
    """
    board = STATION._board()
    counts: dict[str, int] = {}
    for row in board:
        u = row["triage"]["urgency"]
        counts[u] = counts.get(u, 0) + 1
    return {
        "ship": CONFIG.ship.name,
        "crew_total": len(board),
        "crew_fit": counts.get("routine", 0),
        "crew_impaired": sum(v for k, v in counts.items() if k != "routine"),
        "urgency_counts": counts,
        "quarantine_zones_sealed": STATION.quarantine.sealed_zones(),
        "medical_capacity_ok": counts.get("high", 0) <= 2,
    }


@app.websocket("/ws")
async def telemetry(ws: WebSocket) -> None:
    await ws.accept()
    async with BUS.subscribe() as q:
        try:
            while True:
                message = await q.get()
                await ws.send_json(message)
        except WebSocketDisconnect:
            return
        except Exception:
            return


# The UI is served from the same process on the same port.
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _page(name: str) -> FileResponse:
    target = WEB_DIR / name
    if not target.exists():
        raise HTTPException(500, f"web/{name} is missing")
    return FileResponse(target)


# The ship is the front door. The flat board stays one click away and needs no
# GPU, so a machine that cannot run WebGL still runs the whole demo.
@app.get("/")
async def index() -> FileResponse:
    return _page("ship.html")


@app.get("/ship")
async def ship() -> FileResponse:
    return _page("ship.html")


@app.get("/board")
async def board_page() -> FileResponse:
    return _page("index.html")
