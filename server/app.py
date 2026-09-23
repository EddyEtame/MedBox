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
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, scenarios
from .ai.capabilities import manifest
from .ai.ollama import CLIENT
from .ai.validate import enforce
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
        self._ai_lock = asyncio.Lock()

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
                    entry["patient"], triage, self.symptoms.prompt_note(patient_id),
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
        if not CLIENT.available or CLIENT.warming or self._ai_lock.locked():
            return None
        for pid in list(self._prefetch_wanted):
            if pid in self._assessing:
                continue
            # Nobody is waiting on this one, so it may take as long as a cold
            # load: on the demo laptop a French answer runs 18 to 25 s and the
            # operator's ceiling is 25.
            await self.assess_now(pid, timeout=CONFIG.ai.warmup_timeout_seconds)
            return pid
        return None

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
        "scenario": STATION.scenario.name if STATION.scenario else None,
        "scenarios": scenarios.available(),
        "scenario_catalog": scenarios.catalog(),
        "screens_connected": BUS.subscriber_count,
        "assessments_ready": sorted(STATION.assessments),
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
        "history": STATION.db.history(patient_id, limit=120),
        "reported": STATION.symptoms.for_patient(patient_id),
        "documents": STATION.db.medical_documents(patient_id),
        "isolation": isolation.to_dict() if isolation else None,
        "observations": STATION.observations.get(patient_id),
    }


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
    BUS.publish({"type": "symptom", "reported": entry.to_dict()})
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

    command = classify_command(text)
    command, resolved_by, learned_now = await _resolve(command, text, patient_id)
    result = _execute(command, text, patient_id, confidence)
    STATION.learning.record(text, command.kind, resolved_by, patient_id)
    result["resolved_by"] = resolved_by
    result["learned"] = learned_now
    result["understood_as"] = INTENT_LABELS_FR.get(command.kind, command.kind)
    return result


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
async def ai_assess(patient_id: str, fresh: bool = False) -> JSONResponse:
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
    held = STATION.assessments.get(patient_id)
    if (not fresh and held is not None and held.get("ok")
            and held.get("news2_at_assessment") == triage.get("total")
            and time.time() - held.get("at", 0) < 180):
        return JSONResponse(content={
            **held, "cached": True, "age_seconds": round(time.time() - held["at"], 1),
        })
    if held is not None and held.get("ok") and not CLIENT.available:
        # The demo's own beat: the assistant is killed on stage. What it
        # wrote before it died is still what it wrote, dated and labelled;
        # the panel says the assistant is down and the measurements go on.
        return JSONResponse(content={
            **held, "cached": True, "age_seconds": round(time.time() - held["at"], 1),
            "held_reason": "assistant_down",
        })
    result = await STATION.assess_now(patient_id)
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
    return JSONResponse(content={**safe, "cached": False, "age_seconds": 0.0})


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
