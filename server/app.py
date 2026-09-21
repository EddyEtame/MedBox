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
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, scenarios
from .ai.ollama import CLIENT
from .bus import BUS
from .config import CONFIG, ROOT
from .db import Database
from .quarantine import QuarantineRegistry
from .sensors.synthetic import ScenarioSource
from .triage import assess

log = logging.getLogger("medbox")
WEB_DIR = ROOT / "web"


class MedBox:
    """Holds the live state of the station."""

    def __init__(self) -> None:
        self.db = Database(CONFIG.database.resolved)
        self.source = ScenarioSource(CONFIG.ship.crew_size)
        self.quarantine = QuarantineRegistry(
            CONFIG.ship.quarantine_zones, CONFIG.ship.zone_capacity
        )
        self.db.upsert_patients(self.source.roster())
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
        rows.sort(
            key=lambda r: (-r["triage"]["total"], r["patient"]["id"]),
        )
        return rows

    async def loop(self) -> None:
        """Sample, score, quarantine, broadcast. Never awaits the AI."""
        interval = 1.0 / max(1, CONFIG.server.board_hz)
        while True:
            started = time.perf_counter()
            now = time.time()
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
                if self._tick % self._persist_every == 0:
                    self.db.record_reading(reading.patient_id, now, v, reading.source)

            if self._tick % self._persist_every == 0:
                self.db.commit()

            BUS.publish(
                {
                    "type": "board",
                    "at": now,
                    "ship": CONFIG.ship.name,
                    "board": self._board(),
                    "quarantine": self.quarantine.to_dict(),
                    "ai": {"available": CLIENT.available, "error": CLIENT.last_error,
                           "stand_in": CLIENT.stand_in},
                    "scenario": self.scenario.name if self.scenario else None,
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
    return {**entry, "history": STATION.db.history(patient_id, limit=120)}


@app.post("/api/scenario/{name}")
async def start_scenario(name: str) -> dict:
    try:
        sc = STATION.load_scenario(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"started": sc.name, "description": sc.description, "duration": sc.duration}


@app.post("/api/scenario/stop")
async def stop_scenario() -> dict:
    STATION.stop_scenario()
    return {"stopped": True}


@app.post("/api/assess/{patient_id}")
async def ai_assess(patient_id: str) -> JSONResponse:
    """Slow track. Returns 503 when the AI is down — the board is unaffected."""
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    result = await CLIENT.assess(entry["patient"], entry["triage"])
    if result is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "AI unavailable",
                "detail": CLIENT.last_error,
                "note": "Vitals and triage are unaffected. This is the degraded path working as designed.",
            },
        )
    return JSONResponse(content=result)


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
