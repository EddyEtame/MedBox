"""The MedBox server: FastAPI, the simulation loop, and the web UI, one process.

Frontend and backend are served from the same origin on the same port. There is
no CORS, no proxy and no second process to start. `python medbox.py` is the
whole system.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, scenarios
from .ai.capabilities import manifest, deterministic_introduction
from .ai.ollama import CLIENT
from .ai.schemas import ANSWER_HEAD_OPERATOR, ANSWER_HEAD_SELF
from .ai.validate import enforce, enforce_answer
from .bus import BUS
from .config import CONFIG, ROOT
from .commands import Command, classify as classify_command
from .learning import INTENTS, INTENT_LABELS_FR, Learning, candidates as intent_candidates
from .ai.intent import classify as classify_intent
from .db import Database
from .quarantine import QuarantineRegistry
from .protocols import ProtocolDataError, ProtocolEngine
from .sensors.synthetic import BASELINE_PROFILE_VERSION, ScenarioSource
from .speech import Announcer
from .spoken import spoken_assessment, spoken_isolation_message, spoken_personal_intro, spoken_station_answer
from .activities import for_crew, for_member, habits_for
from .tts import MAX_CHARS as VOICE_MAX_CHARS, SPEAKER, VOICE_NAME, speaker_for
from .voice import consent_answer
from .voice import TRANSCRIBER
from .symptoms import SymptomLog
from .triage import Urgency, assess

log = logging.getLogger("medbox")
WEB_DIR = ROOT / "web"
DOCUMENTS_DIR = CONFIG.database.resolved.parent / "documents"
MAX_DOCUMENT_BYTES = 12 * 1024 * 1024
ALLOWED_DOCUMENTS = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".txt": {"text/plain"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
}
MANUAL_DELTA_LIMITS = {
    "temperature": (-5.0, 5.0),
    "spo2": (-30.0, 3.0),
    "pulse": (-80.0, 150.0),
    "respiration": (-20.0, 40.0),
    "systolic_bp": (-60.0, 40.0),
}
LISTENING_POLICY_VERSION = "continuous-local-listening-v1"


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
            CONFIG.ship.quarantine_zones,
            CONFIG.ship.zone_capacity,
            require_confirmation=True,
            allow_automatic_release=False,
        )
        try:
            self.protocols: ProtocolEngine | None = ProtocolEngine.load()
            self.protocol_error: str | None = None
        except ProtocolDataError as exc:
            # A damaged catalogue must hide every protocol option, but it must
            # not take down vitals, triage, or the board with it.
            self.protocols = None
            self.protocol_error = str(exc)
            log.error("local protocol catalogue disabled: %s", exc)
        self.db.upsert_patients(self.source.roster())
        self.source.set_baselines(
            {row["patient_id"]: row for row in self.db.baselines()}
        )
        # A week of history around each baseline, once, so the crew dashboard
        # and the personal pages have a week to show from the first launch.
        self.db.seed_week({pid: dict(p.baseline) for pid, p in self.source.patients.items()}, time.time())
        # Isolation decisions already told to the crew and to the person.
        self._messaged: set[tuple[str, str]] = set()
        # Questions waiting for the model: while one waits, the prefetch loop
        # starts nothing, so a person is never queued behind a background
        # assessment. Eddy, 24 Sep: "he replies but very slowly".
        self.questions_pending = 0
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        # What crew members say, kept apart from what the box measures. The
        # log is handed the recorder rather than importing the database, so
        # nothing in the measurement path depends on it.
        self.symptoms = SymptomLog(on_record=self.db.record_event)
        # What the station has learned from every request: a phrase book and
        # a journal, in the same database, so it survives a restart.
        self.learning = Learning(self.db.conn)
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
        # Assessments the station asked for on its own, keyed by crew member,
        # so that when the operator clicks, the answer is already there. Filled
        # by prefetch_ai(); read by the assess route; each entry carries the
        # NEWS2 total it was written against and the moment it was written.
        self.assessments: dict[str, dict] = {}
        # ACVPU and supplemental oxygen, entered by a person at the console.
        # They complete NEWS2; no instrument here can give them.
        self.observations: dict[str, dict] = self.db.observations()
        self._prefetch_wanted: list[str] = []
        self._assessing: set[str] = set()
        # The background assessment in flight, so a question can drop it:
        # the model serves one request at a time on the laptop CPU.
        self._prefetch_task: asyncio.Task | None = None
        self._prefetch_pid: str | None = None
        self._ai_lock = asyncio.Lock()

    # ---- scenario control -------------------------------------------------
    def load_scenario(self, name: str) -> scenarios.Scenario:
        sc = scenarios.load(name)
        self.source.reset()
        self.symptoms.clear()
        self.announcer.reset()
        self._messaged.clear()
        self.quarantine.reset()
        self.db.save_contacts(self.quarantine.contacts)
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
        self._messaged.clear()
        self.quarantine.reset()
        self.db.save_contacts(self.quarantine.contacts)

    def _advance_scenario(self, now: float) -> None:
        if self.scenario is None or self.scenario_t0 is None:
            return
        elapsed = time.monotonic() - self.scenario_t0
        for i, step in enumerate(self.scenario.steps):
            if i in self._fired or step.at > elapsed:
                continue
            self._fired.add(i)
            # A step that cannot run is skipped out loud, not allowed to end
            # the loop. `temperature: 39,5` is a string in YAML, float() raises
            # here, and before this guard the board stopped dead with the last
            # numbers still on it while /api/status went on answering.
            try:
                self._run_step(step, now)
            except Exception as exc:
                log.warning("scenario step at %ss skipped: %s", step.at, exc)
                # "warning", not "note": the views show warnings to the
                # operator. Scenario notes are narration and are not drawn.
                BUS.publish({"type": "event", "kind": "warning",
                             "text": f"Scenario step at {step.at:g}s skipped: {exc}"})

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
            mode = str(p.get("mode", "absolute"))
            adjustment_provenance = str(p.get("provenance", "scenario-unspecified"))
            exposure_confirmed = p.get("exposure_confirmed", False)
            if not isinstance(exposure_confirmed, bool):
                raise ValueError("exposure_confirmed must be true or false")
            self.source.afflict(
                pool,
                targets,
                float(p.get("over", 30)),
                now,
                mode=mode,
                provenance=adjustment_provenance,
                exposure_confirmed=exposure_confirmed,
            )
            self.db.record_event(
                "simulation_adjustment",
                json.dumps(
                    {
                        "patients": pool,
                        "adjustments_from_healthy_baseline": targets,
                        "duration_seconds": float(p.get("over", 30)),
                        "mode": mode,
                        "provenance": adjustment_provenance,
                        "scenario": self.scenario.name if self.scenario else None,
                        "source": "scenario_yaml",
                        "exposure_confirmed": exposure_confirmed,
                    },
                    ensure_ascii=False,
                ),
            )
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
        last_failure = ""
        while True:
            started = time.perf_counter()
            # This task IS the fast track, and an exception that escapes it
            # ends it without a word: the socket stays open, /api/status keeps
            # answering, and the board freezes on plausible numbers. So one
            # tick that fails is logged and the next tick runs anyway. Logged
            # once per distinct failure, because at ten ticks a second a
            # repeating one would bury everything else in the console.
            try:
                self._frame()
            except Exception as exc:
                if repr(exc) != last_failure:
                    last_failure = repr(exc)
                    log.exception("fast track: a tick failed; carrying on")
            self._tick += 1
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, interval - elapsed))

    def _prompt_note(self, patient_id: str) -> str:
        """What the crew member said, for the model: this session's log, or,
        after a restart, the last three persisted answers, inside the span."""
        if self.symptoms.for_patient(patient_id):
            return self.symptoms.prompt_note(patient_id)
        persisted = self.db.answers(patient_id, limit=3)
        if not persisted:
            return self.symptoms.prompt_note(patient_id)
        log = SymptomLog()
        for a in reversed(persisted):
            try:
                log.answer(patient_id, a["question"], a["answer"])
            except ValueError:
                continue
        return log.prompt_note(patient_id)

    def _message_for(self, change: dict, patient) -> None:
        """Tell the crew, and the person, once per decision: a message that
        pings the dashboards and is read out loud on « Lire »."""
        state = "confirmed" if change.get("confirmed") else "proposed"
        key = (change["patient_id"], state)
        if key in self._messaged:
            return
        self._messaged.add(key)
        text, to_crew, to_me = spoken_isolation_message(patient.name, patient.role, change)
        for recipient, spoken in (("crew", to_crew), (change["patient_id"], to_me)):
            message = self.db.add_message(recipient, f"isolation_{state}", text, spoken, change["patient_id"])
            BUS.publish({"type": "message", "message": message})

    def _frame(self) -> None:
        """One tick of the fast track. Synchronous: nothing here may wait."""
        now = time.time()
        say: list = []
        self._advance_scenario(now)

        for reading in self.source.sample(now):
            v = reading.vitals()
            seen = self.observations.get(reading.patient_id) or {}
            result = assess(
                **v,
                consciousness=seen.get("consciousness"),
                on_oxygen=seen.get("on_oxygen"),
            )
            patient = self.source.patients[reading.patient_id]
            self.latest[reading.patient_id] = {
                "patient": {
                    "id": patient.id,
                    "name": patient.name,
                    "role": patient.role,
                    "source": reading.source,
                    "baseline": dict(patient.baseline),
                    "deviation": {
                        key: round(float(value) - float(patient.baseline[key]), 2)
                        for key, value in v.items()
                        if value is not None and key in patient.baseline
                    },
                    **{k: val for k, val in v.items()},
                },
                "triage": result.to_dict(),
            }
            # One row per change of urgency: the record's history of levels.
            self.db.record_triage(reading.patient_id, now, result.to_dict())
            change = self.quarantine.evaluate(
                reading.patient_id,
                v,
                result,
                exposure_confirmed=patient.exposure_confirmed,
            )
            if change is not None:
                self.db.record_event(
                    "isolation_candidate" if not change.confirmed else "quarantine",
                    json.dumps(change.to_dict()),
                    reading.patient_id,
                )
                BUS.publish({"type": "quarantine", "change": change.to_dict()})
                self._message_for(change.to_dict(), patient)
                # Candidates too: "isolement proposé" is the line the whole
                # confirm-by-a-person design exists for.
                say.extend(self.announcer.on_quarantine(
                    change.to_dict(), self.quarantine.sealed_zones()
                ))
            if self._tick % self._persist_every == 0:
                self.db.record_reading(
                    reading.patient_id,
                    now,
                    v,
                    reading.source,
                    {
                        "model": "medbox-deterministic-simulation-v2",
                        "profile_version": BASELINE_PROFILE_VERSION,
                        "scenario": self.scenario.name if self.scenario else None,
                        "adjustment": (
                            patient.trajectory.to_dict() if patient.contaminated else None
                        ),
                        "clock": "accelerated" if self.scenario else "live-demo",
                    },
                )

        if self._tick % self._persist_every == 0:
            self.db.save_contacts(self.quarantine.contacts)
            self.db.commit()

        rows = self._board()
        self._note_prefetch_targets(rows)
        say.extend(self.announcer.drain())
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
                       "stand_in": CLIENT.stand_in, "warming": CLIENT.warming,
                       "warmed": CLIENT.warmed, "model": CLIENT.model,
                       "timing_seconds": CLIENT.last_timing},
                # Whether this machine can transcribe at all. A microphone
                # button that appears and then fails is worse than one that
                # was never offered.
                "ears": {"available": TRANSCRIBER.available,
                         "error": TRANSCRIBER.last_error},
                "scenario": self.scenario.name if self.scenario else None,
                "scenario_elapsed": (
                    max(0.0, time.monotonic() - self.scenario_t0)
                    if self.scenario and self.scenario_t0 is not None else None
                ),
                "scenario_meta": ({
                    "description": self.scenario.description,
                    "duration_seconds": self.scenario.duration,
                    "simulation": self.scenario.simulation,
                } if self.scenario else None),
                # Usually empty. Only transitions get spoken, because a
                # station announcing a HIGH band ten times a second is a
                # station whose sound gets turned off inside a minute.
                "say": [u.to_dict() for u in say],
            }
        )

    def _note_prefetch_targets(self, rows: list[dict]) -> None:
        """Who deserves an answer before anybody asks: the board's worst first.

        A crew member at medium or high whose cached assessment is missing or
        was written against a different NEWS2 total is queued. The queue is
        rebuilt every frame from the board's own order, so it always reflects
        the current ranking and never grows.
        """
        wanted = []
        for row in rows:
            triage = row["triage"]
            if triage["urgency"] not in ("medium", "high"):
                continue
            pid = row["patient"]["id"]
            held = self.assessments.get(pid)
            if held is not None and held.get("news2_at_assessment") == triage["total"]:
                continue
            if held is not None and time.time() - held.get("at", 0) < 20:
                continue  # let a fresh answer stand while the score settles
            wanted.append(pid)
        self._prefetch_wanted = wanted

    async def assess_now(self, patient_id: str, timeout: float | None = None) -> dict | None:
        """One assessment, enforced and stamped: the same for a click and a prefetch.

        Serialised: two questions at once make each one twice as slow on a
        laptop CPU, and the one the operator is waiting for would be the
        second.
        """
        entry = self.latest.get(patient_id)
        if entry is None:
            return None
        triage = entry["triage"]
        self._assessing.add(patient_id)
        try:
            async with self._ai_lock:
                result = await CLIENT.assess(
                    entry["patient"], triage, self._prompt_note(patient_id),
                    timeout=timeout,
                )
        finally:
            self._assessing.discard(patient_id)
        if result is None:
            return None
        safe = enforce(result, triage.get("urgency", ""), triage.get("params"))
        if not safe["ok"]:
            return {"ok": False, "blocked": safe["blocked"]}
        stamped = {
            **safe,
            "patient_id": patient_id,
            "news2_at_assessment": triage.get("total"),
            "urgency_at_assessment": triage.get("urgency"),
            "at": time.time(),
            "model": CLIENT.model,
            "stand_in": CLIENT.stand_in,
        }
        self.assessments[patient_id] = stamped
        return stamped

    async def prefetch_once(self) -> str | None:
        """Assess the first wanted crew member, if the assistant is free. Returns who."""
        if not CLIENT.available or CLIENT.warming or self._ai_lock.locked() or self.questions_pending:
            return None
        for pid in list(self._prefetch_wanted):
            if pid in self._assessing:
                continue
            # Nobody is waiting on this one, so it may take as long as a cold
            # load: on the demo laptop a French answer runs 18 to 25 s and the
            # operator's ceiling is 25. It runs as its own task so that a
            # question can cancel it (yield_to_question): nobody asked for
            # it, and the model serves one request at a time.
            self._prefetch_task = asyncio.create_task(self.assess_now(pid, timeout=CONFIG.ai.warmup_timeout_seconds))
            self._prefetch_pid = pid
            try:
                await self._prefetch_task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                log.info("prefetch of %s dropped for a question; it comes back", pid)
            finally:
                self._prefetch_task = None
                self._prefetch_pid = None
            return pid
        return None

    def yield_to_question(self, patient_id: str | None = None) -> None:
        """Drop the background assessment in flight so the model is free for
        a question at once. Measured 24 Sep on the defence laptop: a spoken
        question that waited behind a prefetch ran out its eight seconds and
        the station answered with its facts instead. A prefetch of the very
        member being asked about is kept: assess_or_join waits for it."""
        task = self._prefetch_task
        if task is not None and not task.done() and self._prefetch_pid != patient_id:
            task.cancel()

    async def assess_or_join(self, patient_id: str) -> dict | None:
        """The on-demand assessment: joins the prefetch of the same member if
        one is in flight, drops any other, then assesses."""
        task = self._prefetch_task
        if task is not None and not task.done() and self._prefetch_pid == patient_id:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
        self.yield_to_question(patient_id)
        return await self.assess_now(patient_id)

    async def prefetch_ai(self) -> None:
        """Slow track, on its own initiative. It can die; the board does not care."""
        while True:
            try:
                await self.prefetch_once()
            except Exception:  # never let a bad answer end the prefetcher
                log.exception("prefetch failed; carrying on")
            await asyncio.sleep(1.0)

    async def watch_ai(self) -> None:
        """Poll Ollama so the screen shows its true state within a few seconds."""
        while True:
            reachable = await CLIENT.probe()
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            if reachable:
                await CLIENT.warmup()
            # A cancel that lands while httpx is mid-request can be swallowed
            # in there: probe() returns normally, and this task, already marked
            # as cancelling, polls forever. Shutdown waits for it, so the
            # station hung at "Waiting for application shutdown" every time
            # its port was taken, because the first probe is always in flight
            # at that moment. Measured, on Windows: probe returned True with
            # cancelling() == 1, three laps running.
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            await asyncio.sleep(5.0)


STATION = MedBox()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    STATION.source.start()
    loop_task = asyncio.create_task(STATION.loop())
    ai_task = asyncio.create_task(STATION.watch_ai())
    prefetch_task = asyncio.create_task(STATION.prefetch_ai())
    log.info("MedBox %s ready on http://%s:%s", __version__, CONFIG.server.host, CONFIG.server.port)
    try:
        yield
    finally:
        for t in (loop_task, ai_task, prefetch_task):
            t.cancel()
        # Bounded. Stopping the station must not depend on every task agreeing
        # to stop; see watch_ai for the one that once did not.
        await asyncio.wait((loop_task, ai_task, prefetch_task), timeout=3.0)
        STATION.source.stop()
        STATION.db.close()


# No /docs, no /redoc. FastAPI serves both by default, and both pull Swagger or
# ReDoc from cdn.jsdelivr.net and fonts from Google: on a station sold as
# needing no internet at any point, the one page a curious juror might open
# would be the one page that is broken offline.
app = FastAPI(title="MedBox", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None)


@app.middleware("http")
async def revalidate_pages_and_scripts(request, call_next):
    """A browser that kept yesterday's crew.js showed yesterday's page after
    a rebuild (24 Sep). Pages and static files are revalidated on every
    load: with the ETag that is one cheap round trip on localhost, and a new
    bundle is always what the person sees. API routes keep their own
    no-store."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-cache, must-revalidate")
    return response


@app.get("/api/status")
async def status() -> dict:
    simulation = STATION.source.metadata()
    return {
        "version": __version__,
        "ship": CONFIG.ship.name,
        "crew": CONFIG.ship.crew_size,
        "ai": {
            "available": CLIENT.available,
            "warming": CLIENT.warming,
            "warmed": CLIENT.warmed,
            "model": CLIENT.model,
            "ollama_version": CLIENT.server_version,
            "timing_seconds": CLIENT.last_timing,
            "error": CLIENT.last_error,
            "stand_in": CLIENT.stand_in,
            "slow": getattr(CLIENT, "slow", False),
        },
        "ears": {
            "available": TRANSCRIBER.available,
            "error": TRANSCRIBER.last_error,
            "model": str(TRANSCRIBER.model_dir.name),
        },
        "mouth": {
            "available": SPEAKER.available(),
            "voice": VOICE_NAME,
            "error": SPEAKER.last_error,
            "languages": [code for code in ("fr", "en") if speaker_for(code).available()],
        },
        "scenario": STATION.scenario.name if STATION.scenario else None,
        "scenarios": scenarios.available(),
        "scenario_catalog": scenarios.catalog(),
        "screens_connected": BUS.subscriber_count,
        "assessments_ready": sorted(STATION.assessments),
        "answer_model": CONFIG.ai.answer_model or CONFIG.ai.model,
        "personal_ports": PERSONAL_PORTS,
        "personal_pages": [
            {"id": pid, "name": STATION.source.patients[pid].name, "port": PERSONAL_PORTS.get(pid)}
            for pid in sorted(STATION.source.patients)
            if pid in PERSONAL_PORTS or int(pid[2:]) <= 6
        ],
        "simulation": {
            "label": simulation["label_fr"],
            "clock": simulation["clock"],
            "model": simulation["model"],
        },
    }


@app.get("/api/provenance")
async def provenance() -> dict:
    """The exact sources, transformations and active simulation adjustments."""
    return STATION.source.metadata()


@app.get("/api/board")
async def board() -> dict:
    return {"board": STATION._board(), "quarantine": STATION.quarantine.to_dict()}


@app.get("/api/patient/{patient_id}")
async def patient(patient_id: str) -> dict:
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    isolation = STATION.quarantine.assignments.get(patient_id)
    return {
        **entry,
        "history": STATION.db.history(patient_id, limit=300, since=time.time() - 600),
        "triage_history": STATION.db.triage_history(patient_id),
        "answers": STATION.db.answers(patient_id),
        "contacts": STATION.db.contacts(patient_id),
        "reported": STATION.symptoms.for_patient(patient_id),
        "documents": STATION.db.medical_documents(patient_id),
        "isolation": isolation.to_dict() if isolation else None,
        "observations": STATION.observations.get(patient_id),
    }


@app.get("/api/sessions")
async def sessions() -> dict:
    """Every scenario run so far, with its events: the record's journal."""
    return {"sessions": STATION.db.sessions()}


@app.post("/api/patient/{patient_id}/observations")
async def set_observations(patient_id: str, body: dict) -> dict:
    """What a person observed: consciousness (ACVPU) and supplemental oxygen.

    These are the two NEWS2 parameters no instrument on this station can
    measure. Entered here they count as observed and the score becomes a
    complete NEWS2; absent, they are assumed normal and the score says it is
    a partial screen. Recorded with who entered them and when. No model.
    """
    if patient_id not in STATION.latest:
        raise HTTPException(404, f"No crew member {patient_id}")
    consciousness = body.get("consciousness")
    if consciousness is not None and not isinstance(consciousness, str):
        raise HTTPException(400, "consciousness must be a letter A, C, V, P or U")
    on_oxygen = body.get("on_oxygen")
    if on_oxygen is not None and not isinstance(on_oxygen, bool):
        raise HTTPException(400, "on_oxygen must be true, false or null")
    try:
        record = STATION.db.set_observation(patient_id, consciousness or None, on_oxygen)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    STATION.observations[patient_id] = record
    STATION.db.record_event("observation", json.dumps(record), patient_id)
    BUS.publish({"type": "event", "kind": "observation", "patient_id": patient_id, **record})
    return {"observations": record}


@app.post("/api/patient/{patient_id}/simulate")
async def simulate_patient_change(patient_id: str, body: dict) -> dict:
    """Apply auditable changes from this crew member's healthy reference.

    The operator enters deltas, never replacement measurements. The simulator
    turns those changes into a smooth, replayable sensor trajectory; the LLM
    is absent from this path.
    """
    patient = STATION.source.patients.get(patient_id)
    if patient is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    raw_changes = body.get("changes")
    if not isinstance(raw_changes, dict) or not raw_changes:
        raise HTTPException(400, "At least one vital change is required.")

    changes: dict[str, float] = {}
    for vital, value in raw_changes.items():
        if vital not in MANUAL_DELTA_LIMITS:
            raise HTTPException(400, f"Unknown vital: {vital}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"Invalid change for {vital}") from exc
        low, high = MANUAL_DELTA_LIMITS[vital]
        if not math.isfinite(number) or not low <= number <= high:
            raise HTTPException(400, f"Change for {vital} must be between {low:g} and {high:g}")
        changes[vital] = number

    try:
        over = float(body.get("over_seconds", 25.0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid transition duration") from exc
    if not math.isfinite(over) or not 1.0 <= over <= 180.0:
        raise HTTPException(400, "Transition duration must be between 1 and 180 seconds")
    reason = str(body.get("reason") or "Exercice manuel de simulation").strip()
    if not reason or len(reason) > 500:
        raise HTTPException(400, "A short simulation reason is required")
    exposure_confirmed = body.get("exposure_confirmed", False)
    if not isinstance(exposure_confirmed, bool):
        raise HTTPException(400, "exposure_confirmed must be a boolean")

    now = time.time()
    STATION.source.apply_deltas(
        [patient_id],
        changes,
        over,
        now,
        provenance="manual-interface-delta",
        exposure_confirmed=exposure_confirmed,
    )
    recorded = []
    for vital, delta in changes.items():
        recorded.append(
            STATION.db.record_manual_override(
                patient_id,
                vital,
                delta,
                reason,
                actor="operator",
                at=now,
                provenance={
                    "mode": "delta_from_personal_healthy_baseline",
                    "transition_seconds": over,
                    "exposure_confirmed": exposure_confirmed,
                },
            )
        )
    event = {
        "type": "event",
        "kind": "manual_adjustment",
        "patient_id": patient_id,
        "changes": changes,
        "exposure_confirmed": exposure_confirmed,
        "over_seconds": over,
        "text": f"Simulation manuelle appliquée à {patient.name}",
    }
    BUS.publish(event)
    return {
        "patient_id": patient_id,
        "healthy_baseline": dict(patient.baseline),
        "trajectory": patient.trajectory.to_dict(),
        "audit": recorded,
    }


def _document_type(original_name: str, media_type: str, raw: bytes) -> tuple[str, str]:
    clean_name = unquote(original_name or "").strip()
    suffix = Path(clean_name).suffix.lower()
    normalized_type = (media_type or "application/octet-stream").split(";", 1)[0].lower()
    if suffix not in ALLOWED_DOCUMENTS or normalized_type not in ALLOWED_DOCUMENTS[suffix]:
        raise HTTPException(415, "Format accepté : PDF, DOCX, PNG, JPEG ou TXT.")
    signatures = {
        ".pdf": raw.startswith(b"%PDF-"),
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".docx": raw.startswith(b"PK\x03\x04"),
    }
    if suffix in signatures and not signatures[suffix]:
        raise HTTPException(415, "Le contenu du fichier ne correspond pas à son extension.")
    if suffix == ".txt":
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "Le rapport texte doit être encodé en UTF-8.") from exc
    return clean_name, normalized_type


@app.post("/api/patient/{patient_id}/documents")
async def upload_medical_document(patient_id: str, request: Request) -> JSONResponse:
    """Store one report locally; it is never sent to the language model."""
    if patient_id not in STATION.source.patients:
        raise HTTPException(404, f"No crew member {patient_id}")
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Le fichier est vide.")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "Le rapport dépasse la limite locale de 12 Mo.")
    original_name, media_type = _document_type(
        request.headers.get("X-MedBox-Filename", ""),
        request.headers.get("Content-Type", ""),
        raw,
    )
    suffix = Path(original_name).suffix.lower()
    blob_id = f"{uuid.uuid4().hex}{suffix}"
    target = DOCUMENTS_DIR / blob_id
    try:
        await asyncio.to_thread(target.write_bytes, raw)
        metadata = STATION.db.record_medical_document(
            patient_id,
            original_name=original_name,
            media_type=media_type,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            blob_id=blob_id,
        )
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
    response = JSONResponse(content={"document": {k: v for k, v in metadata.items() if k != "blob_id"}})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/patient/{patient_id}/documents")
async def list_medical_documents(patient_id: str) -> dict:
    if patient_id not in STATION.source.patients:
        raise HTTPException(404, f"No crew member {patient_id}")
    return {"documents": STATION.db.medical_documents(patient_id)}


@app.get("/api/documents/{document_id}")
async def download_medical_document(document_id: str) -> FileResponse:
    metadata = STATION.db.medical_document(document_id)
    if metadata is None:
        raise HTTPException(404, "Document introuvable")
    target = DOCUMENTS_DIR / metadata["blob_id"]
    if not target.is_file():
        raise HTTPException(410, "Le fichier local associé est absent")
    return FileResponse(
        target,
        media_type=metadata["media_type"],
        filename=metadata["original_name"],
        headers={"Cache-Control": "no-store"},
    )


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


@app.post("/api/patient/{patient_id}/answer")
async def record_answer(patient_id: str, body: dict) -> dict:
    """The crew member's reply to one of the assistant's questions.

    It enters exactly as a reported symptom does, as a quotation: the next
    assessment sees it inside the untrusted span, the screen shows it as their
    words, and NEWS2 never reads it.
    """
    if patient_id not in STATION.latest:
        raise HTTPException(404, f"No crew member {patient_id}")
    try:
        entry = STATION.symptoms.answer(
            patient_id, body.get("question", ""), body.get("answer", "")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Persisted too (Brad): the record keeps it across restarts, and
    # the next assessment after a restart still reads it, inside the span.
    STATION.db.record_answer(patient_id, entry.text.split('"', 1)[1].rsplit('", answered', 1)[0]
                             if entry.text.startswith('Asked "') else str(body.get("question", ""))[:200],
                             str(body.get("answer", ""))[:180])
    BUS.publish({"type": "symptom", "reported": entry.to_dict()})
    BUS.publish({"type": "answer", "patient_id": patient_id})
    return {"reported": STATION.symptoms.for_patient(patient_id)}


@app.post("/api/quarantine/{patient_id}/confirm")
async def confirm_quarantine(patient_id: str) -> dict:
    """Human confirmation turns a recommendation into a berth assignment."""
    try:
        assignment = STATION.quarantine.confirm(patient_id)
    except KeyError as exc:
        raise HTTPException(404, "Aucune recommandation d'isolement pour ce membre") from exc
    detail = assignment.to_dict()
    STATION.db.record_event("quarantine_confirmed", json.dumps(detail), patient_id)
    BUS.publish({"type": "quarantine", "change": detail})
    STATION.announcer.later(detail, STATION.quarantine.sealed_zones())
    return {"assignment": detail, "quarantine": STATION.quarantine.to_dict()}


@app.post("/api/quarantine/{patient_id}/release")
async def release_quarantine(patient_id: str, body: dict) -> dict:
    """Release is always a recorded human decision, never a vital-sign side effect."""
    reason = str(body.get("reason") or "Levée manuelle par l'opérateur").strip()
    if not reason or len(reason) > 300:
        raise HTTPException(400, "Un motif court est requis")
    try:
        released = STATION.quarantine.release(patient_id, reason)
    except KeyError as exc:
        raise HTTPException(404, "Ce membre n'est pas dans le registre d'isolement") from exc
    detail = released.to_dict()
    STATION.db.record_event("quarantine_released", json.dumps(detail), patient_id)
    BUS.publish({"type": "quarantine", "change": detail})
    STATION.announcer.later({**detail, "reason": "released"}, STATION.quarantine.sealed_zones())
    return {"released": detail, "quarantine": STATION.quarantine.to_dict()}


# A few seconds of speech is well under a megabyte. The cap is not about disk,
# it is that an endpoint which accepts an unbounded upload from a browser is a
# way to wedge the machine the demo runs on.
MAX_AUDIO_BYTES = 4 * 1024 * 1024


async def _transcribe_audio(request: Request) -> tuple[str, float, str | None] | None:
    """Transcribe one short in-memory upload and always erase its temp file.

    Consent and wake-word checks must be able to hear a phrase without filing
    that phrase in a patient's chart. Keeping the upload plumbing here gives
    both endpoints the same size cap and, more importantly, the same deletion
    guarantee.
    """
    raw = await request.body()
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "That recording is too long. Keep it to a few seconds.")
    if not raw:
        raise HTTPException(400, "The recording was empty.")

    # PyAV probes the container contents, so this neutral suffix also handles
    # the Ogg or MP4 blobs browsers may produce. The UUID prevents concurrent
    # microphones from ever sharing a path.
    tmp = Path(tempfile.gettempdir()) / f"medbox-{uuid.uuid4().hex}.audio"
    try:
        tmp.write_bytes(raw)
        headers = getattr(request, "headers", None) or {}
        purpose = (headers.get("X-MedBox-Purpose") or "").lower()
        preferred = (headers.get("X-MedBox-Language") or "auto").lower()
        if purpose == "consent":
            # « J'accepte » must work as well as "I accept". A one-second clip
            # is too short for the model to guess its language, so it is heard
            # in French first, then in English, and the one that is an answer
            # wins. Seen on 24 Sep: French consent refused, English accepted.
            first = await TRANSCRIBER.listen(tmp, language="fr")
            if first is not None and consent_answer(first[0]):
                return first
            second = await TRANSCRIBER.listen(tmp, language="en")
            if second is not None and consent_answer(second[0]):
                return second
            return first or second
        if preferred in ("fr", "en"):
            return await TRANSCRIBER.listen(tmp, language=preferred)
        return await TRANSCRIBER.listen(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _nothing_heard() -> JSONResponse:
    response = JSONResponse(
        status_code=503,
        content={
            "error": "Aucune parole transcrite",
            "detail": TRANSCRIBER.last_error or "aucune parole détectée dans l’enregistrement",
            "note": "Saisissez le texte. Les constantes et la priorisation restent actives.",
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/voice/transcribe")
async def transcribe_voice(request: Request) -> JSONResponse:
    """Hear one phrase without storing it or attaching it to a patient.

    The browser uses this narrow route for consent and the ``MedBox`` wake
    phrase. Only an explicit post-consent command is later sent to the symptom
    endpoint. Audio exists only for the duration of this request, and the
    response is marked non-cacheable so consent transcripts do not linger in
    a browser cache.
    """
    heard = await _transcribe_audio(request)
    if heard is None:
        return _nothing_heard()

    text, confidence, language = heard
    response = JSONResponse(content={
        "heard": {
            "text": text,
            "confidence": confidence,
            "language": language,
        }
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/voice/sessions")
async def start_voice_session(body: dict) -> JSONResponse:
    """Start an auditable local-listening session without storing any audio."""
    requested = body.get("languages", ["fr", "en"])
    if not isinstance(requested, list):
        raise HTTPException(400, "languages must be a list")
    try:
        session_id = STATION.db.start_listening_session(
            languages=tuple(str(item) for item in requested),
            client=str(body.get("client") or "local-web"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    response = JSONResponse(content={
        "session_id": session_id,
        "policy_version": LISTENING_POLICY_VERSION,
        "audio_retained": False,
        "scope": "session_ouverte_uniquement",
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/voice/sessions/{session_id}/consent")
async def record_voice_consent(session_id: str, body: dict) -> JSONResponse:
    try:
        STATION.db.record_consent(
            session_id,
            str(body.get("decision") or ""),
            method=str(body.get("method") or "voice"),
            language=str(body.get("language") or "fr"),
            policy_version=LISTENING_POLICY_VERSION,
        )
        current = STATION.db.current_consent(session_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        # Keep database implementation details out of the public response.
        raise HTTPException(404, "Session d'écoute inconnue") from exc
    response = JSONResponse(content={"consent": current})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/voice/sessions/{session_id}/end")
async def end_voice_session(session_id: str) -> dict:
    try:
        STATION.db.end_listening_session(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ended": True}


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

    heard = await _transcribe_audio(request)

    if heard is None:
        return _nothing_heard()

    text, confidence, language = heard
    try:
        entry = STATION.symptoms.add(patient_id, text, source="voice", confidence=confidence)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    BUS.publish({"type": "symptom", "reported": entry.to_dict()})
    response = JSONResponse(content={
        "heard": {**entry.to_dict(), "language": language},
        "reported": STATION.symptoms.for_patient(patient_id),
    })
    response.headers["Cache-Control"] = "no-store"
    return response


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
    return {
        "started": sc.name,
        "description": sc.description,
        "duration": sc.duration,
        "simulation": sc.simulation,
    }


@app.post("/api/assistant/command")
async def assistant_command(body: dict) -> dict:
    """Execute one post-consent, allow-listed local command.

    Classification is deterministic and never passes control text to Ollama.
    Free speech is stored only as an explicitly reported statement for the
    selected crew member.  A doctor call is a local alert request, not a claim
    that an external person was contacted.
    """
    text = str(body.get("text") or "").strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "Une commande courte est requise")
    patient_id = str(body.get("patient_id") or "").strip() or None
    if patient_id is not None and patient_id not in STATION.latest:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    confidence = body.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Confiance vocale invalide") from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise HTTPException(400, "La confiance vocale doit être comprise entre 0 et 1")

    lang = str(body.get("lang") or "fr").lower()[:2]
    command = classify_command(text)
    command, resolved_by, learned_now = await _resolve(command, text, patient_id)
    if resolved_by == "none" and (patient_id is None or _looks_like_a_question(text)):
        # Not a command the station knows, and not a statement filed under a
        # selected member: a person is talking to the assistant. Answer them,
        # out loud. Eddy, 24 Sep: "it detected speech but did not respond".
        answer = await assistant_ask({"text": text, "patient_id": patient_id, "lang": lang,
                                      "self": bool(body.get("self"))})
        STATION.learning.record(text, command.kind, resolved_by, patient_id)
        return {
            "action": "answer",
            "reply": answer["answer"],
            "spoken": answer.get("spoken") or answer["answer"],
            "resolved_by": "ask",
            "learned": False,
            "understood_as": "question à l’assistant",
            "held_reason": answer.get("held_reason"),
            "blocked": answer.get("blocked", []),
        }
    result = _execute(command, text, patient_id, confidence)
    STATION.learning.record(text, command.kind, resolved_by, patient_id)
    result["resolved_by"] = resolved_by
    result["learned"] = learned_now
    result["understood_as"] = INTENT_LABELS_FR.get(command.kind, command.kind)
    result.setdefault("spoken", result.get("reply"))
    return result


_QUESTION_STARTS = (
    "que ", "qu’", "qu'", "quoi", "pourquoi", "comment", "est-ce", "est ce", "quel", "quelle",
    "où ", "ou est", "combien", "peux-tu", "peux tu", "pouvez", "et si", "dis-moi", "dis moi",
    "what", "why", "how", "can ", "could", "should", "is ", "are ", "do ", "does ", "tell me", "where",
)


def _looks_like_a_question(text: str) -> bool:
    low = str(text or "").strip().lower()
    return "?" in low or low.startswith(_QUESTION_STARTS)


async def _resolve(command: Command, text: str, patient_id: str | None) -> tuple[Command, str, bool]:
    """Words the allow-list did not know: the phrase book first, then the model.

    Both can only name one of the router's own actions. Whatever the model
    decides once is written to the phrase book, so the same words next time
    are resolved here with no model at all. An explicit declaration
    (« déclare : ... ») is never reinterpreted.
    """
    if command.explicit:
        return command, "allowlist", False
    known = STATION.learning.lookup(text)
    if known:
        return _as_command(known, text), "learned", False
    plausible = [i for i in intent_candidates(text) if i != "report"]
    if not plausible:
        return command, "none", False          # nothing the station does; no model
    if len(plausible) == 1:
        intent = plausible[0]                  # one plausible reading: no model either
        learned = STATION.learning.learn(text, intent, "lexicon")
        return _as_command(intent, text), "lexicon", learned
    guess = await classify_intent(text, patient_id is not None, plausible)
    if guess and guess != "report":
        learned = STATION.learning.learn(text, guess, "model")
        return _as_command(guess, text), "model", learned
    return command, "none", False


def _as_command(intent: str, text: str) -> Command:
    if intent == "report":
        return Command("report", reported_text=text)
    return Command(intent)


def _execute(command: Command, text: str, patient_id: str | None, confidence) -> dict:
    """The deterministic actions, unchanged. One entry per intent in INTENTS."""
    board = STATION._board()
    ids = [row["patient"]["id"] for row in board]

    if command.kind == "help":
        return {
            "action": "open_help",
            "reply": "J’ouvre l’aide. Les mesures et la priorité restent déterministes, même sans assistant.",
        }
    if command.kind in {"worst", "next"}:
        if not ids:
            return {"action": "none", "reply": "Aucun membre n’est encore présent sur le tableau."}
        if command.kind == "worst" or patient_id not in ids:
            target = ids[0]
        else:
            target = ids[(ids.index(patient_id) + 1) % len(ids)]
        row = next(item for item in board if item["patient"]["id"] == target)
        return {
            "action": "select",
            "patient_id": target,
            "reply": (
                f"{row['patient']['name']}, score de dépistage {row['triage']['total']}, "
                f"niveau {row['triage']['urgency']}."
            ),
        }
    if command.kind == "why":
        if patient_id is None:
            return {"action": "none", "reply": "Sélectionnez d’abord un membre d’équipage."}
        triage = STATION.latest[patient_id]["triage"]
        scored = [
            f"{item['name']} plus {item['score']}"
            for item in triage.get("params", []) if item.get("score", 0) > 0
        ]
        explanation = ", ".join(scored) if scored else "aucun point sur les paramètres mesurés"
        return {
            "action": "show_why",
            "patient_id": patient_id,
            "reply": f"Score partiel {triage['total']} : {explanation}.",
        }
    if command.kind == "isolated":
        registry = STATION.quarantine.to_dict()
        confirmed = [a for a in registry["assignments"] if a.get("confirmed")]
        return {
            "action": "show_isolation",
            "reply": (
                f"{len(confirmed)} isolement confirmé, {registry['candidates']} à confirmer, "
                f"{registry['awaiting_bed']} en attente d’une place."
            ),
        }
    if command.kind in {"assess", "ask"}:
        if patient_id is None:
            return {"action": "none", "reply": "Sélectionnez d’abord un membre d’équipage."}
        return {
            "action": "assess",
            "patient_id": patient_id,
            "reply": "Je lance une évaluation locale. Elle ne remplace pas un diagnostic médical.",
        }
    if command.kind == "pause":
        return {"action": "pause", "reply": "Écoute mise en pause."}
    if command.kind == "doctor_call":
        detail = {
            "requested_by": "voice_operator",
            "patient_id": patient_id,
            "network_contacted": False,
            "status": "local_alert_only",
        }
        STATION.db.record_event("doctor_call_requested", json.dumps(detail), patient_id)
        BUS.publish({"type": "event", "kind": "doctor_call_requested", **detail})
        return {
            "action": "doctor_call_logged",
            "patient_id": patient_id,
            "reply": (
                "Demande d’appel médical enregistrée localement. "
                "Aucun médecin externe n’a été contacté automatiquement."
            ),
        }
    if command.kind in {"report", "audible_event"}:
        if patient_id is None:
            return {
                "action": "none",
                "reply": "Sélectionnez un membre avant d’enregistrer une déclaration ou un son possible.",
            }
        reported = command.reported_text or text
        if command.kind == "audible_event":
            reported = (
                "Événement sonore possible (toux ou éternuement) détecté par transcription ; "
                "à confirmer par une personne."
            )
        try:
            entry = STATION.symptoms.add(
                patient_id, reported, source="voice", confidence=confidence
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        BUS.publish({"type": "symptom", "reported": entry.to_dict()})
        return {
            "action": "reported",
            "patient_id": patient_id,
            "reply": "Déclaration enregistrée comme propos rapporté, jamais comme mesure.",
            "reported": STATION.symptoms.for_patient(patient_id),
        }
    return {"action": "none", "reply": "Commande non reconnue. Dites « MedBox, aide »."}


@app.get("/api/assistant/learned")
async def assistant_learned() -> dict:
    """What the station has learned so far: the jury can read it on the Help panel."""
    return {
        "phrases": STATION.learning.phrases(),
        "recent": STATION.learning.recent(20),
        "stats": STATION.learning.stats(),
        "intents": {name: INTENT_LABELS_FR[name] for name in INTENTS},
    }


@app.post("/api/assistant/feedback")
async def assistant_feedback(body: dict) -> dict:
    """An operator says what a phrase meant. That outranks anything the model learned."""
    text = str(body.get("text") or "").strip()
    intent = str(body.get("intent") or "").strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "Une phrase courte est requise")
    if intent == "forget":
        return {"forgotten": STATION.learning.forget(text)}
    if intent not in INTENTS:
        raise HTTPException(400, "Action inconnue de la station")
    STATION.learning.learn(text, intent, "operator")
    STATION.db.record_event("phrase_taught", json.dumps({"text": text[:200], "intent": intent}), None)
    return {"learned": True, "intent": intent, "label_fr": INTENT_LABELS_FR[intent]}


@app.post("/api/patient/{patient_id}/protocol")
async def evaluate_local_protocol(patient_id: str, body: dict) -> JSONResponse:
    """Match a reviewed local card; the language model is never consulted."""
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    if STATION.protocols is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "catalogue_protocoles_indisponible",
                "detail": STATION.protocol_error or "catalogue local non chargé",
                "medication_options": [],
            },
        )

    extra = str(body.get("observation") or "").strip()
    if len(extra) > 500:
        raise HTTPException(400, "L’observation est limitée à 500 caractères")
    reported = STATION.symptoms.for_patient(patient_id)
    observations = {
        "utterance": extra,
        "symptoms": [str(item.get("text") or "") for item in reported[-12:]],
        "vitals": {
            key: entry["patient"].get(key)
            for key in ("temperature", "spo2", "pulse", "respiration")
        },
    }
    try:
        result = STATION.protocols.evaluate(
            observations,
            screening=body.get("screening"),
            human_validation=body.get("human_validation"),
        )
    except (ProtocolDataError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    STATION.db.record_event(
        "protocol_evaluated",
        json.dumps(
            {
                "card_id": result.get("card", {}).get("id") if result.get("card") else None,
                "medication_gate": result.get("medication_gate"),
                "mode": result.get("mode"),
            },
            ensure_ascii=False,
        ),
        patient_id,
    )
    response = JSONResponse(content=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/assess/{patient_id}")
async def ai_assess(patient_id: str, fresh: bool = False, me: bool = False) -> JSONResponse:
    """Slow track. Returns 503 when the AI is down — the board is unaffected.

    The answer is usually already there. The station assesses the worst crew
    members on its own as soon as they leave routine (prefetch_ai), so a
    click returns the held answer at once, marked cached with its age, when
    it was written against the NEWS2 total on screen now. `fresh=1` asks
    again regardless, which is what the button does the second time.
    """
    entry = STATION.latest.get(patient_id)
    if entry is None:
        raise HTTPException(404, f"No crew member {patient_id}")
    triage = entry["triage"]
    name = (entry.get("patient") or {}).get("name")
    held = STATION.assessments.get(patient_id)
    if (not fresh and held is not None and held.get("ok")
            and held.get("news2_at_assessment") == triage.get("total")
            and time.time() - held.get("at", 0) < 180):
        body = {**held, "cached": True, "age_seconds": round(time.time() - held["at"], 1)}
        return JSONResponse(content={**body, "spoken": _spoken_for(patient_id, name, body, me)})
    if held is not None and held.get("ok") and not CLIENT.available:
        # The demo's own beat: the assistant is killed on stage. What it
        # wrote before it died is still what it wrote, dated and labelled;
        # the panel says the assistant is down and the measurements go on.
        body = {
            **held, "cached": True, "age_seconds": round(time.time() - held["at"], 1),
            "held_reason": "assistant_down",
        }
        return JSONResponse(content={**body, "spoken": _spoken_for(patient_id, name, body, me)})
    result = await STATION.assess_or_join(patient_id)
    if result is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Assistant indisponible",
                "detail": CLIENT.last_error,
                "note": (
                    "Les constantes et la priorisation restent actives. "
                    "Le mode dégradé fonctionne comme prévu."
                ),
            },
        )

    # assess_now() already ran enforce(): the answer was rebuilt from the
    # schema's own keys, and anything the model invented was reported.
    safe = result
    if not safe["ok"]:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Réponse de l’assistant rejetée",
                "detail": "; ".join(safe["blocked"]) or "aucun contenu exploitable",
                "note": (
                    "Les constantes et la priorisation restent actives. Une réponse "
                    "mal formée suit le même mode dégradé qu’un assistant arrêté."
                ),
            },
        )

    # Stamped by assess_now() from what the server knows: which crew member,
    # which score and which moment, so the panel can detect a stale answer.
    # `spoken` is the one breath the voice says about it: no numbers, the
    # pattern in plain words, not a diagnosis, the question.
    body = {**safe, "cached": False, "age_seconds": 0.0}
    return JSONResponse(content={**body, "spoken": _spoken_for(patient_id, name, body, me)})


def _spoken_for(patient_id: str, name: str | None, body: dict, second_person: bool = False) -> str:
    """The voice's one breath about this member: condition, decision, question."""
    iso = STATION.quarantine.assignments.get(patient_id)
    entry = STATION.latest.get(patient_id) or {}
    urgency = (entry.get("triage") or {}).get("urgency")
    return spoken_assessment(name, body, iso.to_dict() if iso else None, urgency, second_person)


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
                "error": "Assistant indisponible",
                "detail": CLIENT.last_error,
                "note": (
                    "Le guide ci-dessus reste disponible : il appartient à la "
                    "station et ne dépend pas du modèle."
                ),
            },
        )
    return JSONResponse(content={"text": text, "stand_in": CLIENT.stand_in})


VITAL_FR = {
    "temperature": ("température", "°C"),
    "spo2": ("SpO2", "%"),
    "pulse": ("pouls", "/min"),
    "respiration": ("respiration", "/min"),
    "systolic_bp": ("tension systolique", "mmHg"),
}
URGENCY_FR = {"routine": "routine", "low": "faible", "medium": "moyenne", "high": "haute"}


def _crew_facts() -> tuple[str, str, str]:
    """What the station knows about the whole crew right now: one line for
    the model, one sentence for the screen, one for the voice (names, no
    numbers). Deterministic, so the model cannot invent who is isolated.
    Eddy's page, 24 Sep: asked « Qui est en isolement ? » with nobody
    isolated, the model answered that two members were."""
    rows = list(STATION.latest.values())
    watch: list[str] = []
    routine = 0
    for e in rows:
        if (e["triage"].get("urgency") or "routine") == "routine":
            routine += 1
        else:
            watch.append(str(e["patient"].get("name") or e["patient"].get("id")))
    confirmed: list[str] = []
    decided: list[str] = []
    for pid, a in STATION.quarantine.assignments.items():
        name = str((STATION.latest.get(pid) or {}).get("patient", {}).get("name") or pid)
        (confirmed if a.confirmed else decided).append(f"{name} (zone {a.zone})" if a.zone else name)
    facts = (
        f"Équipage : {len(rows)} membres, {routine} en routine ; à surveiller : {', '.join(watch) or 'personne'} ; "
        f"isolés : {', '.join(confirmed) or 'personne'} ; isolement à confirmer : {', '.join(decided) or 'personne'}. "
        "Ne citez que ces noms."
    )
    if not watch and not confirmed and not decided:
        screen = f"Tout l’équipage ({len(rows)} membres) est dans sa plage habituelle. Personne n’est en isolement."
        spoken = "Tout l’équipage est dans sa plage habituelle. Personne n’est en isolement."
        return facts, screen, spoken
    parts = []
    if confirmed:
        parts.append("en isolement : " + ", ".join(confirmed))
    if decided:
        parts.append("isolement décidé, à confirmer : " + ", ".join(decided))
    if watch:
        parts.append("à surveiller : " + ", ".join(watch))
    if not confirmed and not decided:
        # The question is who is isolated: say it, even when the answer is
        # nobody and the news is elsewhere.
        parts.append("personne en isolement")
    screen = f"Équipage de {len(rows)} : " + " ; ".join(parts) + "."
    spoken = " ".join(p[0].upper() + p[1:] + "." for p in parts).replace(" (zone ", ", zone ").replace(")", "")
    return facts, screen, spoken


# Questions the station answers itself, at once and from its own registers:
# who is isolated, how the crew is doing. The model phrases everything else.
ISOLATION_QUESTION = re.compile(r"isol|quarant", re.I)
CREW_QUESTION = re.compile(r"[ée]quipage|crew|tout le monde|[àa] bord|combien", re.I)


INTRO_QUESTION = re.compile(r"pr[ée]sent(e|ez)[- ]?(toi|vous)|qui (es[- ]tu|[êe]tes[- ]vous)|who are you|introduce yourself|"
                            r"c.est quoi medbox|qu.est[- ]ce que medbox|what is medbox|tu es qui|vous [êe]tes qui", re.I)
INTRO_SPOKEN = ("Je suis MedBox, le référent médical du bord. Je surveille l’équipage en continu, je décide des "
                "isolements et je réponds à vos questions. Je ne prescris aucun médicament.")


VITAL_WORDS = [
    ("pulse", re.compile(r"pouls|c[oœ]ur|cardiaque|battement", re.I)),
    ("temperature", re.compile(r"temp[ée]rature|fi[èe]vre|chaud|frisson", re.I)),
    ("spo2", re.compile(r"spo2|oxyg[èe]ne|saturation", re.I)),
    ("respiration", re.compile(r"respir|souffle|essouffl", re.I)),
    ("systolic_bp", re.compile(r"tension|pression", re.I)),
]
VITAL_TOL = {"temperature": 0.5, "spo2": 2.0, "pulse": 15.0, "respiration": 4.0, "systolic_bp": 15.0}
VITAL_UNIT_SPOKEN = {"temperature": "degrés", "spo2": "pour cent", "pulse": "par minute", "respiration": "par minute", "systolic_bp": ""}
STATUS_QUESTION = re.compile(r"vais[- ]je bien|je vais bien|comment (je vais|[çc]a va|vais[- ]je)|mon [ée]tat|suis[- ]je (malade|en forme|bien)|"
                             r"comment va\b|comment (il|elle) va|est[- ]ce qu[e’'] ?(il|elle) va bien|son [ée]tat|am i (ok|fine|well)|how (am i|is)", re.I)
SYMPTOM_STATEMENT = re.compile(r"\bj[’']ai (mal|de la fi[èe]vre|des vertiges|des nausées|la naus[ée]e|du mal|froid|chaud)|"
                               r"je (tousse|vomis|saigne|suis (fatigu|essouffl|malade|faible|pris)|me sens (mal|faible|fatigu))|"
                               r"\b(douleur|migraine|mal de t[êe]te|mal au ventre|mal à la gorge|frissons|vertige|naus[ée]e|toux)\b", re.I)


def _symptom_answer(patient_id: str, text: str, second_person: bool) -> str | None:
    """A complaint is written to the dossier as a quotation, and answered from
    the constants of the moment: the station never diagnoses a headache, it
    says what it measures and what it will do."""
    facts = _member_facts(patient_id)
    if not facts:
        return None
    try:
        entry = STATION.symptoms.add(patient_id, text.strip(), source="typed")
        BUS.publish({"type": "symptom", "reported": entry.to_dict()})
    except ValueError:
        pass
    p, t, baseline = facts
    name = p.get("name") or patient_id
    devs = _deviations(p, baseline)
    you = "vous" if second_person else name
    noted = f"Je note « {text.strip().rstrip('?').strip()} » dans {'votre' if second_person else 'son'} dossier."
    if not devs and (t.get("urgency") or "routine") == "routine":
        return (f"{noted} Pour l’instant, {'vos' if second_person else 'ses'} constantes ne montrent rien d’anormal : score {t.get('total', 0)}. "
                f"Reposez-{'vous' if second_person else 'le' if p.get('role') else 'vous'}, buvez, et redemandez-moi dans une heure ; si cela s’aggrave, dites-le-moi tout de suite.")
    urgency = URGENCY_FR.get(t.get("urgency"), t.get("urgency") or "routine")
    return (f"{noted} {'Vos' if second_person else 'Ses'} constantes montrent {', '.join(devs) if devs else 'un écart'} : score {t.get('total')}, "
            f"priorité {urgency}. Je {'vous' if second_person else 'le'} garde sous surveillance rapprochée.")


def _member_facts(patient_id: str) -> tuple[dict, dict, dict] | None:
    entry = STATION.latest.get(patient_id)
    if not entry:
        return None
    p, t = entry["patient"], entry["triage"]
    return p, t, (p.get("baseline") or {})


def _deviations(p: dict, baseline: dict) -> list[str]:
    """The vitals outside their usual range, said in words."""
    out = []
    for key, tol in VITAL_TOL.items():
        v, b = p.get(key), baseline.get(key)
        if v is None or b is None:
            continue
        if key == "spo2" and v < b - tol:
            out.append("une saturation plus basse que d’habitude")
        elif key != "spo2" and v > b + tol:
            out.append({"temperature": "de la fièvre", "pulse": "un pouls plus rapide que d’habitude",
                        "respiration": "une respiration plus rapide que d’habitude", "systolic_bp": "une tension plus haute que d’habitude"}[key])
        elif key != "spo2" and v < b - tol:
            out.append({"temperature": "une température plus basse que d’habitude", "pulse": "un pouls plus lent que d’habitude",
                        "respiration": "une respiration plus lente que d’habitude", "systolic_bp": "une tension plus basse que d’habitude"}[key])
    return out


def _status_answer(patient_id: str, second_person: bool) -> str | None:
    facts = _member_facts(patient_id)
    if not facts:
        return None
    p, t, baseline = facts
    name = p.get("name") or patient_id
    urgency = URGENCY_FR.get(t.get("urgency"), t.get("urgency") or "routine")
    iso = STATION.quarantine.assignments.get(patient_id)
    who = "Vous êtes" if second_person else f"{name} est"
    your = "vos" if second_person else "ses"
    devs = _deviations(p, baseline)
    if not devs and (t.get("urgency") or "routine") == "routine":
        return f"{who} en routine aujourd’hui : score {t.get('total', 0)}, toutes {your} constantes dans {your.replace('vos', 'votre').replace('ses', 'sa')} plage habituelle."
    seen = ", ".join(devs) if devs else "un écart dans " + your + " constantes"
    iso_text = ("" if iso is None else (" L’isolement est confirmé." if iso.confirmed else " L’isolement est décidé, à confirmer."))
    return f"{who} à surveiller : score {t.get('total')}, priorité {urgency}, avec {seen}.{iso_text}"


def _vital_answer(patient_id: str, key: str, second_person: bool) -> str | None:
    facts = _member_facts(patient_id)
    if not facts:
        return None
    p, t, baseline = facts
    v, b = p.get(key), baseline.get(key)
    if v is None:
        return None
    label = VITAL_FR[key][0]
    name = p.get("name") or patient_id
    owner = f"Votre {label}" if second_person else f"{label.capitalize()} de {name}"
    fmt = (lambda x: f"{x:.1f}") if key in ("temperature", "spo2") else (lambda x: f"{x:.0f}")
    unit = VITAL_UNIT_SPOKEN.get(key, "")
    if b is None:
        return f"{owner} est à {fmt(v)} {unit}.".replace("  ", " ")
    tol = VITAL_TOL[key]
    if abs(v - b) <= tol:
        return f"{owner} est à {fmt(v)} {unit}, dans {'votre' if second_person else 'sa'} plage habituelle (autour de {fmt(b)}). Rien d’anormal.".replace("  ", " ")
    direction = "au-dessus" if v > b else "au-dessous"
    urgency = URGENCY_FR.get(t.get("urgency"), t.get("urgency") or "routine")
    return (f"{owner} est à {fmt(v)} {unit}, {direction} de {'votre' if second_person else 'son'} habitude (autour de {fmt(b)}). "
            f"C’est ce qui pèse dans {'votre' if second_person else 'son'} score aujourd’hui : {t.get('total')}, priorité {urgency}.").replace("  ", " ")


def _named_member(text: str) -> str | None:
    """The crew member a question names, by full name or by a first name
    nobody else shares; None when the question names nobody."""
    low = text.lower()
    firsts: dict[str, list[str]] = {}
    for pid, e in STATION.latest.items():
        name = str(e["patient"].get("name") or "").strip()
        if not name:
            continue
        if re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", low):
            return pid
        firsts.setdefault(name.split()[0].lower(), []).append(pid)
    for first, pids in firsts.items():
        if len(pids) == 1 and re.search(r"(?<!\w)" + re.escape(first) + r"(?!\w)", low):
            return pids[0]
    return None


def _subject(text: str, patient_id: str | None, second_person: bool) -> tuple[str | None, bool]:
    """« Comment va Brad ? » asked from Eddy's page is about Brad: the
    member the question names is its subject, in the third person."""
    named = _named_member(text)
    if named is not None and named != patient_id:
        return named, False
    return patient_id, second_person


ACTIVITY_QUESTION = re.compile(r"sport|entra[îi]n|courir|course|effort|muscul|exercice|travailler|reprendre|sortir|activit", re.I)
REST_QUESTION = re.compile(r"dormir|sommeil|repos|me reposer|se reposer|coucher|fatigu", re.I)
WHAT_TO_DO = re.compile(r"que (dois|devrais|puis)[- ]je faire|quoi faire|que faire|qu[’']est[- ]ce que je (dois|peux) faire|conseil|recommand", re.I)


def _advice_answer(patient_id: str, text: str, second_person: bool) -> str | None:
    """Activity, rest, « que dois-je faire ? » : answered from the state the
    station holds. 24 Sep: asked about sport, the small model said « non »
    to a member with a score of 0 and every constant in its usual range."""
    facts = _member_facts(patient_id)
    if not facts:
        return None
    p, t, baseline = facts
    name = p.get("name") or patient_id
    devs = _deviations(p, baseline)
    total = t.get("total", 0) or 0
    urgency = URGENCY_FR.get(t.get("urgency"), t.get("urgency") or "routine")
    iso = STATION.quarantine.assignments.get(patient_id)
    calm = not devs and (t.get("urgency") or "routine") == "routine" and iso is None
    you, your = ("vous", "vos") if second_person else (name, "ses")
    seen = ", ".join(devs) if devs else "un écart"
    if ACTIVITY_QUESTION.search(text):
        if calm:
            return (f"Oui : score {total}, toutes {your} constantes dans {'votre' if second_person else 'sa'} plage habituelle. "
                    f"{'Allez-y' if second_person else 'Il peut y aller'}, et {'dites-moi' if second_person else 'qu’il me dise'} si quelque chose change.")
        hold = (" L’isolement est décidé, à confirmer." if iso is not None and not iso.confirmed else " L’isolement est confirmé." if iso is not None else "")
        return (f"Pas aujourd’hui : score {total}, priorité {urgency}, avec {seen}. "
                f"{'Reposez-vous' if second_person else 'Qu’il se repose'}, {'buvez' if second_person else 'boive'}, et je {'vous' if second_person else 'le'} garde sous surveillance rapprochée.{hold}")
    if REST_QUESTION.search(text):
        if calm:
            return (f"Rien ne l’impose : score {total}, {your} constantes dans {'votre' if second_person else 'sa'} plage habituelle. "
                    f"{'Dormez' if second_person else 'Qu’il dorme'} selon {'votre' if second_person else 'son'} besoin ; si la fatigue persiste, {'dites-le-moi' if second_person else 'qu’il me le dise'}.")
        return (f"Oui : score {total}, priorité {urgency}, avec {seen}. Le repos est ce qui aide le plus maintenant ; "
                f"je {'vous' if second_person else 'le'} garde sous surveillance et je {'vous' if second_person else 'le'} réveille si une constante bouge.")
    if WHAT_TO_DO.search(text):
        if calm:
            return (f"Rien de particulier : score {total}, toutes {your} constantes dans {'votre' if second_person else 'sa'} plage habituelle. "
                    f"{'Continuez vos activités' if second_person else 'Qu’il continue ses activités'} ; je mesure en continu et je {'vous' if second_person else 'le'} préviens au premier écart.")
        hold = (" Rejoignez la zone d’isolement décidée, à confirmer avec l’équipage." if second_person and iso is not None and not iso.confirmed else
                " L’isolement est décidé, à confirmer." if iso is not None and not iso.confirmed else
                (" Restez en zone d’isolement." if second_person else " Il reste en zone d’isolement.") if iso is not None else "")
        return (f"{'Reposez-vous, buvez, restez joignable' if second_person else 'Qu’il se repose, boive et reste joignable'} : score {total}, priorité {urgency}, "
                f"avec {seen}. Je mesure en continu et je {'vous' if second_person else 'le'} garde sous surveillance rapprochée.{hold}")
    return None


def _station_shortcut(text: str, patient_id: str | None, second_person: bool = False) -> dict | None:
    """An instant, deterministic answer when the station holds it: the
    introduction, the crew and isolation questions, a member's state, one
    of a member's vitals. None otherwise: the model phrases the rest."""
    def out(answer, spoken=None):
        return {"ok": True, "answer": answer, "spoken": spoken or answer, "grounded_in": "manual",
                "blocked": [], "stand_in": False, "held_reason": None, "resolved_by": "station"}
    if INTRO_QUESTION.search(text):
        # Eddy, 24 Sep: asked to present himself, the model found nothing in
        # eight seconds. The introduction is the station's own text.
        return out(deterministic_introduction(), INTRO_SPOKEN)
    patient_id, second_person = _subject(text, patient_id, second_person)
    if patient_id is not None:
        # « Est-ce que je vais bien ? », « pourquoi mon pouls monte ? » : the
        # registers hold the answer; the jury hears it in a second.
        if STATUS_QUESTION.search(text):
            answer = _status_answer(patient_id, second_person)
            return out(answer) if answer else None
        if SYMPTOM_STATEMENT.search(text):
            answer = _symptom_answer(patient_id, text, second_person)
            return out(answer) if answer else None
        if ACTIVITY_QUESTION.search(text) or REST_QUESTION.search(text) or WHAT_TO_DO.search(text):
            answer = _advice_answer(patient_id, text, second_person)
            return out(answer) if answer else None
        for key, rx in VITAL_WORDS.items() if isinstance(VITAL_WORDS, dict) else VITAL_WORDS:
            if rx.search(text):
                answer = _vital_answer(patient_id, key, second_person)
                return out(answer) if answer else None
        return None
    if not (ISOLATION_QUESTION.search(text) or CREW_QUESTION.search(text)):
        return None
    _facts, screen, spoken = _crew_facts()
    return {"ok": True, "answer": screen, "spoken": spoken, "grounded_in": "manual", "blocked": [],
            "stand_in": False, "held_reason": None, "resolved_by": "station"}


def _facts_for(patient_id: str | None, brief: bool = False) -> tuple[str, str, str]:
    """The facts the assistant may answer from, and the station's own answer.

    Deterministic, written by the station: the model reads them, it never
    supplies them. Returns (facts for the model, the sentence the station
    shows instead when the model is absent, silent or ungrounded, and the
    short form of that sentence for the voice, which carries no baselines).
    `brief` drops the capability list and the long preamble: the text mode
    pays for every token of prompt before its first word (24 Sep).
    """
    caps = " ; ".join(c["title"] for c in manifest()["capabilities"])
    crew_facts, crew_screen, crew_spoken = _crew_facts()
    lines = [
        "Faits de la station : MedBox mesure cinq constantes (température, SpO2, pouls, "
        "respiration, tension systolique) et reçoit deux observations saisies (conscience "
        "ACVPU, oxygène d’appoint). Le score est NEWS2 (Royal College of Physicians 2017), "
        "calculé sans modèle. L’assistant est le référent médical du bord : il évalue, "
        "décide des isolements, que l’équipage accuse réception, et répond aux questions ; "
        "il ne prescrit aucun médicament.",
        f"Ce que la station sait faire : {caps}.",
        crew_facts,
    ]
    if brief:
        lines = [crew_facts]
    station_answer = crew_screen
    station_spoken = crew_spoken
    entry = STATION.latest.get(patient_id) if patient_id else None
    if entry:
        p, t = entry["patient"], entry["triage"]
        baseline = p.get("baseline") or {}
        vitals = ", ".join(
            f"{VITAL_FR[k][0]} {p[k]} {VITAL_FR[k][1]} (ligne de base {baseline.get(k)})"
            for k in VITAL_FR
            if p.get(k) is not None
        )
        urgency = URGENCY_FR.get(t.get("urgency"), t.get("urgency"))
        measured = ", ".join(t.get("measured") or []) or "aucun"
        missing = ", ".join(t.get("missing_news2") or []) or "aucun"
        iso = STATION.quarantine.assignments.get(patient_id)
        if iso is None:
            iso_text = "pas d’isolement proposé"
        elif iso.confirmed:
            iso_text = f"isolement confirmé en zone {iso.zone}" if iso.zone else "isolement confirmé, en attente d’un lit"
        else:
            iso_text = "isolement proposé, à confirmer par une personne"
        said = [s.get("text", "") for s in STATION.symptoms.for_patient(patient_id)][-3:]
        said_text = " ; ".join(x for x in said if x) or "rien"
        if brief:
            # A question pays for every token the model has not seen (35 a
            # second on the defence laptop, 24 Sep): the state, the
            # isolation, the vitals out of their range with their numbers,
            # what was declared. The station itself answers questions about
            # a single vital, with the exact value.
            off = []
            for key, tol in VITAL_TOL.items():
                v, b = p.get(key), baseline.get(key)
                if v is None or b is None:
                    continue
                if (v < b - tol) if key == "spo2" else abs(v - b) > tol:
                    off.append(f"{VITAL_FR[key][0]} {v} (base {b})")
            where = ("écarts : " + ", ".join(off) + " ; le reste dans sa plage habituelle") if off else "toutes ses constantes dans sa plage habituelle"
            line = f"{p.get('name')} : NEWS2 {t.get('total')} ({urgency}), {iso_text} ; {where}."
            if said_text != "rien":
                line += f" Déclaré : {said_text}."
            # The crew line is for questions about the crew; a member's
            # question carries the member only. Any other name in the answer
            # is then not in the facts, and _ungrounded holds it back.
            lines = [line]
        else:
            lines.append(
                f"Membre sélectionné : {p.get('name')} ({p.get('role', '')}). Mesures actuelles : {vitals}. "
                f"NEWS2 {t.get('total')} ({urgency}) ; paramètres mesurés : {measured} ; non mesurés : {missing}. "
                f"{iso_text}. Déclarations récentes : {said_text}."
            )
        station_answer = f"{p.get('name')} : NEWS2 {t.get('total')} ({urgency}), {iso_text}. Mesures : {vitals}."
        station_spoken = _without_down_prefix(spoken_station_answer(p.get("name"), t.get("total"), urgency, iso_text))
    return "\n".join(lines), station_answer, station_spoken


def _without_down_prefix(spoken: str) -> str:
    """The spoken station sentence starts by saying the assistant is down;
    the text mode adds the real reason itself."""
    for prefix in ("L’assistant est arrêté ; ", "L’assistant est arrêté. ", "L’assistant est arrêté "):
        if spoken.startswith(prefix):
            return spoken[len(prefix):]
    return spoken


def _ungrounded(answer: str, facts: str) -> bool:
    """The station's own check on a plain-text answer: a crew name the facts
    do not mention, or an isolation the registers do not hold, and the
    sentence is not shown."""
    low = answer.lower()
    names = {str(e["patient"].get("name") or "") for e in STATION.latest.values()}
    facts_low = facts.lower()
    for name in names:
        if name and name.lower() in low and name.lower() not in facts_low:
            return True
    nobody_isolated = (("isolés : personne" in facts_low and "isolement à confirmer : personne" in facts_low)
                       or not STATION.quarantine.assignments)
    if nobody_isolated and ("isol" in low or "quarant" in low) and "pas d" not in low and "personne" not in low and "aucun" not in low:
        return True
    # A number the facts do not hold: 24 Sep, asked for the most important
    # vital of a member whose facts carried no number, the model answered
    # « Pouls 112 /min » for a pulse of 61.
    held = {_num(x) for x in re.findall(r"\d+(?:[.,]\d+)?", facts)}
    for x in re.findall(r"\d+(?:[.,]\d+)?", answer):
        if _num(x) not in held:
            return True
    return False


def _num(text: str) -> float:
    return float(text.replace(",", "."))


DOWN = "Le référent est arrêté ; voici ce que la station sait. "
LATE = "Le référent n’a pas répondu à temps ; voici ce que la station sait. "
UNGROUNDED = "Le référent n’a rien trouvé dans les mesures pour répondre ; voici ce que la station sait. "


@app.post("/api/assistant/ask")
async def assistant_ask(body: dict) -> dict:
    """The text mode: one typed question, answered from facts the station wrote.

    The facts are deterministic and come first; the model may only phrase an
    answer from them, inside ANSWER_SCHEMA, and the answer passes
    `enforce_answer` before anyone reads it. When the model is absent or
    silent the station answers with the facts itself and says so, exactly as
    the held assessment does.
    """
    text = str(body.get("text") or "").strip()
    if not text or len(text) > 300:
        raise HTTPException(400, "Une question courte est requise")
    patient_id = str(body.get("patient_id") or "").strip() or None
    if patient_id is not None and patient_id not in STATION.latest:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    lang = str(body.get("lang") or "fr").lower()[:2]
    second_person = bool(body.get("self"))
    patient_id, second_person = _subject(text, patient_id, second_person)
    facts, station_answer, station_spoken = _facts_for(patient_id, brief=True)
    # Fixed line first: the warm-up primed it, and only the member's line
    # and the question are read again (24 Sep: 35 tokens a second of prompt
    # on the defence laptop, 16 of answer).
    head = ANSWER_HEAD_SELF if second_person else ANSWER_HEAD_OPERATOR
    if lang == "en":
        head += " Answer in English: the person asked for English."
    facts = head + "\n" + facts
    shortcut = _station_shortcut(text, patient_id, second_person)
    if shortcut is not None:
        shortcut["lang"] = lang
        return shortcut
    if not CLIENT.available:
        return {"ok": True, "answer": DOWN + station_answer, "spoken": DOWN + station_spoken, "grounded_in": "manual",
                "blocked": [], "stand_in": False, "held_reason": "assistant_down", "lang": lang}
    STATION.questions_pending += 1
    STATION.yield_to_question()
    try:
        async with STATION._ai_lock:
            raw = await CLIENT.answer(text, facts)
    finally:
        STATION.questions_pending -= 1
    if raw is None:
        return {"ok": True, "answer": LATE + station_answer, "spoken": LATE + station_spoken, "grounded_in": "manual",
                "blocked": [], "stand_in": False, "held_reason": "assistant_silent", "detail": CLIENT.last_error,
                "lang": lang}
    out = enforce_answer(raw)
    if out["grounded_in"] != "nothing" and not out["blocked"] and _ungrounded(out["answer"], facts):
        out["grounded_in"] = "nothing"
    if out["grounded_in"] == "nothing" and not out["blocked"]:
        # The model itself says nothing in the facts supports its sentence:
        # that sentence is not shown. The station's own is.
        out["answer"] = UNGROUNDED + station_answer
        out["grounded_in"] = "manual"
        out["held_reason"] = "ungrounded"
        out["spoken"] = UNGROUNDED + station_spoken
        out["lang"] = lang
        out["stand_in"] = CLIENT.stand_in
        return out
    # Two validated sentences read as they are; the voice module says the units.
    out["spoken"] = out["answer"]
    out["lang"] = lang
    out["stand_in"] = CLIENT.stand_in
    out["held_reason"] = None
    return out


PERSONAL_PORTS: dict[str, int] = {}
for _pair in (os.environ.get("MEDBOX_PERSONAL_PORTS") or "").split(","):
    if ":" in _pair:
        _pid, _port = _pair.split(":", 1)
        try:
            PERSONAL_PORTS[_pid.strip()] = int(_port)
        except ValueError:
            pass


@app.get("/api/messages")
async def list_messages(to: str | None = None, unread: int = 0) -> dict:
    """What the referent has told the crew ("crew") or one member (their id)."""
    return {"messages": STATION.db.messages(to, bool(unread))}


@app.post("/api/messages/{message_id}/read")
async def read_message(message_id: int) -> dict:
    """Opened by a person: marked read, and returned with its spoken form so
    the page can say it."""
    message = STATION.db.mark_read(message_id)
    if message is None:
        raise HTTPException(404, "Message inconnu")
    BUS.publish({"type": "message_read", "id": message_id})
    return message


# A week does not change between two page loads: forty members' week stats
# are forty queries, five seconds on a busy CPU (measured 24 Sep). Kept for a
# minute per member; a new reading is at most a minute late on the dashboard.
_WEEK_CACHE: dict[str, tuple[float, dict]] = {}


def _week_for(pid: str, now: float) -> dict:
    hit = _WEEK_CACHE.get(pid)
    if hit and now - hit[0] < 60:
        return hit[1]
    week = STATION.db.week_stats(pid, now)
    _WEEK_CACHE[pid] = (now, week)
    return week


def _member_summary(pid: str, now: float) -> dict:
    patient = STATION.source.patients[pid]
    entry = STATION.latest.get(pid) or {}
    p = entry.get("patient") or {}
    t = entry.get("triage") or {}
    iso = STATION.quarantine.assignments.get(pid)
    return {
        "id": pid,
        "name": patient.name,
        "role": patient.role,
        "port": PERSONAL_PORTS.get(pid),
        "baseline": dict(patient.baseline),
        "vitals": {k: p.get(k) for k in ("temperature", "spo2", "pulse", "respiration", "systolic_bp")},
        "today": {"total": t.get("total"), "urgency": t.get("urgency"), "score_label": t.get("score_label"),
                  "measured": t.get("measured")},
        "week": _week_for(pid, now),
        "isolation": iso.to_dict() if iso else None,
    }


def _week_ok(week: dict, baseline: dict) -> bool:
    """Whether the week stayed within the usual range of this person."""
    tol = {"temperature": 0.6, "spo2": 2.0, "pulse": 12.0, "respiration": 4.0, "systolic_bp": 15.0}
    for key, span in tol.items():
        stats, base = (week.get("vitals") or {}).get(key), baseline.get(key)
        if not stats or base is None:
            continue
        if abs(stats["max"] - base) > span or abs(stats["min"] - base) > span:
            return False
    return True


@app.get("/api/crew/week")
async def crew_week() -> dict:
    """Everyone's week, how the crew is doing today, and what to do together."""
    now = time.time()
    members = [_member_summary(pid, now) for pid in sorted(STATION.source.patients)]
    isolated = sum(1 for m in members if m["isolation"] and m["isolation"].get("confirmed"))
    proposed = sum(1 for m in members if m["isolation"] and not m["isolation"].get("confirmed"))
    impaired = sum(1 for m in members if (m["today"]["urgency"] or "routine") != "routine")
    return {
        "at": now,
        "ship": CONFIG.ship.name,
        "summary": {"total": len(members), "fit": len(members) - impaired, "impaired": impaired,
                    "isolated": isolated, "proposed": proposed},
        "members": members,
        "champion": _champion(members),
        "zones": STATION.quarantine.to_dict().get("zones", {}),
        "activities": for_crew(now, isolated=isolated + proposed),
        "messages": STATION.db.messages("crew", limit=20),
    }


def _has_a_space(member: dict) -> bool:
    """A member with a personal page and port: the team. Same rule as the
    status route's personal_pages."""
    pid = str(member.get("id") or "")
    try:
        return pid in PERSONAL_PORTS or int(pid[2:]) <= 6
    except ValueError:
        return False


def _champion(members: list[dict]) -> dict | None:
    """The member whose week stayed closest to their own baseline, today in
    routine: the example the referent holds up to the crew, with the habits
    behind it. Deterministic, from the same numbers the table shows. The
    team, who have a face and a page, come first; the rest of the crew only
    if none of them qualifies today."""
    team = [m for m in members if _has_a_space(m)]
    return _best_of(team) or _best_of(members)


def _best_of(members: list[dict]) -> dict | None:
    span = {"temperature": 0.6, "spo2": 2.0, "pulse": 12.0, "respiration": 4.0, "systolic_bp": 15.0}
    best, best_score = None, None
    for m in members:
        if (m["today"]["urgency"] or "routine") != "routine" or m.get("isolation"):
            continue
        vitals = (m.get("week") or {}).get("vitals") or {}
        score = 0.0
        for key, tol in span.items():
            stats, base = vitals.get(key), (m.get("baseline") or {}).get(key)
            if not stats or base is None:
                score += 1.0
                continue
            score += (abs(stats["max"] - base) + abs(stats["min"] - base)) / tol
        if best_score is None or score < best_score:
            best, best_score = m, score
    if best is None:
        return None
    week = (best.get("week") or {}).get("vitals") or {}
    pulse = week.get("pulse", {}) or {}
    resp = week.get("respiration", {}) or {}
    why = (f"La semaine la plus stable de l’équipage : pouls de repos autour de {pulse.get('avg', '–')}, "
           f"respiration autour de {resp.get('avg', '–')}, tout dans sa plage habituelle.")
    return {"id": best["id"], "name": best["name"], "role": best["role"], "why": why,
            "habits": habits_for(best["id"]), "port": best.get("port")}


@app.get("/api/me/{patient_id}")
async def me(patient_id: str) -> dict:
    """One person's page: their week, their today, what the referent tells them."""
    if patient_id not in STATION.source.patients:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    now = time.time()
    summary = _member_summary(patient_id, now)
    week_ok = _week_ok(summary["week"], summary["baseline"])
    urgency = summary["today"]["urgency"]
    agent = STATION.db.agent_name(patient_id)
    intro = spoken_personal_intro(summary["name"], week_ok, urgency, summary["isolation"], agent)
    return {
        **summary,
        "agent_name": agent,
        "week_ok": week_ok,
        "observations": STATION.observations.get(patient_id),
        "reported": STATION.symptoms.for_patient(patient_id)[-5:],
        "messages": STATION.db.messages(patient_id, limit=20),
        "activities": for_member(urgency, bool(summary["isolation"]), now),
        "intro": {"text": intro, "spoken": intro},
    }


@app.post("/api/me/{patient_id}/agent")
async def set_agent(patient_id: str, body: dict) -> dict:
    """What this member calls their assistant: their own wake word. Letters,
    spaces and hyphens, two to twenty-four characters; empty resets to MedBox."""
    if patient_id not in STATION.source.patients:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    name = " ".join(str(body.get("name") or "").split())
    if name and (len(name) < 2 or len(name) > 24 or not all(ch.isalpha() or ch in " -" for ch in name)):
        raise HTTPException(400, "Un nom de deux à vingt-quatre lettres, espaces ou tirets")
    return {"agent_name": STATION.db.set_agent_name(patient_id, name)}


@app.get("/api/voice/status")
async def voice_status() -> dict:
    return {"available": SPEAKER.available(), "voice": VOICE_NAME, "error": SPEAKER.last_error}


@app.post("/api/voice/say")
async def voice_say(body: dict) -> Response:
    """Render one short French text with the bundled voice. Slow track only.

    The browser asks for this after the validator has rebuilt an answer or an
    assessment; the ship's announcements never come through here, they are
    the pre-rendered clips. Absent voice: 503, and the browser stays silent
    for free text, as before.
    """
    text = str(body.get("text") or "").strip()
    if not text or len(text) > VOICE_MAX_CHARS:
        raise HTTPException(400, "Un texte court est requis")
    speaker = speaker_for(str(body.get("lang") or "fr"))
    if not speaker.available():
        raise HTTPException(503, "Aucune voix embarquée pour cette langue : les phrases pré-enregistrées restent disponibles.")
    try:
        audio = await speaker.say(text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, f"La voix n’a pas pu lire ce texte : {exc}") from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


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


@app.get("/crew")
async def crew_page() -> FileResponse:
    return _page("crew.html")


@app.get("/me/{patient_id}")
async def me_page(patient_id: str) -> FileResponse:
    if patient_id not in STATION.source.patients:
        raise HTTPException(404, f"Membre inconnu : {patient_id}")
    return _page("me.html")
