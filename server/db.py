"""Auditable local persistence for the offline MedBox station.

SQLite is deliberate here: the database is a file inside the portable MedBox
folder, so the station does not depend on a separately installed service. The
schema still keeps patients, observations, sessions and documents separate;
moving those tables to PostgreSQL later does not require changing their
meaning.

Measured and simulated facts are never blurred together. Every vital
observation has a source and machine-readable provenance, manual changes live
in their own audit table, and the observation tables are append-only.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BASELINE_PROFILE_VERSION = "healthy-adult-reference-v1"
BASELINE_RANGES = {
    # Conservative resting ranges: every generated profile remains in the
    # NEWS2 zero-score interval. These are synthetic reference anchors, not
    # claims that a particular crew member was clinically measured.
    "temperature": (36.5, 37.1),
    "spo2": (97.0, 99.0),
    "pulse": (60.0, 78.0),
    "respiration": (12.0, 17.0),
}
BASELINE_REFERENCES = (
    "https://medlineplus.gov/ency/article/002341.htm",
    "https://medlineplus.gov/lab-tests/pulse-oximetry/",
)
VITAL_UNITS = {
    "temperature": "degC",
    "spo2": "%",
    "pulse": "beats/min",
    "respiration": "breaths/min",
}
CONSENT_DECISIONS = frozenset({"accepted", "refused", "revoked"})
CONSENT_METHODS = frozenset({"voice", "button", "keyboard"})
_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BLOB_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}$")


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS healthy_baselines (
    patient_id  TEXT PRIMARY KEY REFERENCES patients(id),
    temperature REAL NOT NULL,
    spo2        REAL NOT NULL,
    pulse       REAL NOT NULL,
    respiration REAL NOT NULL,
    profile_version TEXT NOT NULL,
    derived_at  REAL NOT NULL,
    provenance  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    at          REAL NOT NULL,
    temperature REAL,
    spo2        REAL,
    pulse       REAL,
    respiration REAL,
    source      TEXT NOT NULL,
    provenance  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_readings_patient_at ON readings(patient_id, at);

CREATE TABLE IF NOT EXISTS triage_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    at          REAL NOT NULL,
    total       INTEGER NOT NULL,
    urgency     TEXT NOT NULL,
    detail      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_triage_patient_at ON triage_snapshots(patient_id, at);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    kind        TEXT NOT NULL,
    patient_id  TEXT,
    detail      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);

CREATE TABLE IF NOT EXISTS listening_sessions (
    id          TEXT PRIMARY KEY,
    started_at  REAL NOT NULL,
    ended_at    REAL,
    languages   TEXT NOT NULL,
    client      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consent_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES listening_sessions(id),
    at          REAL NOT NULL,
    decision    TEXT NOT NULL CHECK(decision IN ('accepted', 'refused', 'revoked')),
    method      TEXT NOT NULL CHECK(method IN ('voice', 'button', 'keyboard')),
    language    TEXT NOT NULL,
    policy_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consent_session_at ON consent_events(session_id, at);

CREATE TABLE IF NOT EXISTS manual_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    session_id  TEXT REFERENCES listening_sessions(id),
    at          REAL NOT NULL,
    vital       TEXT NOT NULL CHECK(vital IN ('temperature', 'spo2', 'pulse', 'respiration')),
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    reason      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    provenance  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_overrides_patient_at ON manual_overrides(patient_id, at);

CREATE TABLE IF NOT EXISTS medical_documents (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    session_id  TEXT REFERENCES listening_sessions(id),
    added_at    REAL NOT NULL,
    original_name TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL CHECK(size_bytes >= 0),
    sha256      TEXT NOT NULL,
    blob_id     TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_patient_at ON medical_documents(patient_id, added_at);

CREATE TABLE IF NOT EXISTS quarantine (
    patient_id  TEXT PRIMARY KEY REFERENCES patients(id),
    zone        TEXT NOT NULL,
    since       REAL NOT NULL,
    reason      TEXT NOT NULL
);
"""


APPEND_ONLY_GUARDS = """
CREATE TRIGGER IF NOT EXISTS readings_no_update
BEFORE UPDATE ON readings BEGIN
    SELECT RAISE(ABORT, 'vital observations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS readings_no_delete
BEFORE DELETE ON readings BEGIN
    SELECT RAISE(ABORT, 'vital observations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS manual_overrides_no_update
BEFORE UPDATE ON manual_overrides BEGIN
    SELECT RAISE(ABORT, 'manual overrides are append-only');
END;
CREATE TRIGGER IF NOT EXISTS manual_overrides_no_delete
BEFORE DELETE ON manual_overrides BEGIN
    SELECT RAISE(ABORT, 'manual overrides are append-only');
END;
CREATE TRIGGER IF NOT EXISTS consent_events_no_update
BEFORE UPDATE ON consent_events BEGIN
    SELECT RAISE(ABORT, 'consent events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS consent_events_no_delete
BEFORE DELETE ON consent_events BEGIN
    SELECT RAISE(ABORT, 'consent events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS consent_only_for_active_session
BEFORE INSERT ON consent_events
WHEN NOT EXISTS (
    SELECT 1 FROM listening_sessions
    WHERE id=NEW.session_id AND ended_at IS NULL
) BEGIN
    SELECT RAISE(ABORT, 'listening session is not active');
END;
"""


def _canonical_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    """Return stable JSON and reject values that cannot be audited later."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("provenance must contain JSON-compatible values") from exc


def _label(value: str, field: str, *, maximum: int = 160) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{field} is required")
    if "\x00" in clean or len(clean) > maximum:
        raise ValueError(f"invalid {field}")
    return clean


def _unit_interval(digest: bytes, offset: int) -> float:
    return int.from_bytes(digest[offset : offset + 4], "big") / 0xFFFFFFFF


def healthy_baseline(patient_id: str, name: str, role: str) -> dict[str, Any]:
    """Derive a stable, individual healthy reference profile.

    The identity fields select a point inside evidence-backed healthy ranges;
    they are not used to infer physiology from a person's name, role, sex or
    ethnicity. The same roster always yields the same rehearsal data.
    """
    identity = f"{BASELINE_PROFILE_VERSION}\0{patient_id}\0{name}\0{role}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    values: dict[str, Any] = {}
    precisions = {"temperature": 2, "spo2": 1, "pulse": 1, "respiration": 1}
    for offset, (vital, (low, high)) in enumerate(BASELINE_RANGES.items()):
        value = low + _unit_interval(digest, offset * 4) * (high - low)
        values[vital] = round(value, precisions[vital])
    values.update(
        {
            "profile_version": BASELINE_PROFILE_VERSION,
            "provenance": {
                "kind": "simulated_healthy_reference",
                "method": "deterministic_sha256_range_selection",
                "profile_version": BASELINE_PROFILE_VERSION,
                "ranges": {
                    key: {"min": bounds[0], "max": bounds[1], "unit": VITAL_UNITS[key]}
                    for key, bounds in BASELINE_RANGES.items()
                },
                "references": list(BASELINE_REFERENCES),
                "disclaimer": "Reference simulation; not a patient measurement.",
            },
        }
    )
    return values


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: uvicorn's threadpool may touch this.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        # WAL keeps reads from blocking the write path during the demo.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._migrate_existing_database()
        self.conn.executescript(APPEND_ONLY_GUARDS)
        self.conn.commit()

    def _migrate_existing_database(self) -> None:
        """Apply additive migrations to databases made by earlier demos."""
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(readings)").fetchall()
        }
        if "provenance" not in columns:
            self.conn.execute(
                "ALTER TABLE readings ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'"
            )

    def upsert_patients(self, rows: Iterable[tuple[str, str, str]]) -> None:
        """Provision the roster and one stable healthy profile per person."""
        roster = [
            (_label(pid, "patient id", maximum=64), _label(name, "name"), _label(role, "role"))
            for pid, name, role in rows
        ]
        now = time.time()
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO patients (id, name, role, created_at) VALUES (?,?,?,?)",
                [(pid, name, role, now) for pid, name, role in roster],
            )
            baseline_rows = []
            for pid, name, role in roster:
                profile = healthy_baseline(pid, name, role)
                baseline_rows.append(
                    (
                        pid,
                        profile["temperature"],
                        profile["spo2"],
                        profile["pulse"],
                        profile["respiration"],
                        profile["profile_version"],
                        now,
                        _canonical_json(profile["provenance"]),
                    )
                )
            self.conn.executemany(
                "INSERT OR IGNORE INTO healthy_baselines "
                "(patient_id, temperature, spo2, pulse, respiration, profile_version, "
                "derived_at, provenance) VALUES (?,?,?,?,?,?,?,?)",
                baseline_rows,
            )

    def baseline(self, patient_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT patient_id, temperature, spo2, pulse, respiration, profile_version, "
            "derived_at, provenance FROM healthy_baselines WHERE patient_id=?",
            (patient_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["provenance"] = json.loads(result["provenance"])
        return result

    def baselines(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT p.id AS patient_id, p.name, p.role, b.temperature, b.spo2, b.pulse, "
            "b.respiration, b.profile_version, b.derived_at, b.provenance "
            "FROM patients p JOIN healthy_baselines b ON b.patient_id=p.id ORDER BY p.id"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["provenance"] = json.loads(item["provenance"])
            result.append(item)
        return result

    def record_reading(
        self,
        patient_id: str,
        at: float,
        vitals: dict[str, Any],
        source: str,
        provenance: Mapping[str, Any] | None = None,
    ) -> None:
        source = _label(source, "reading source", maximum=64)
        evidence = dict(provenance or {})
        evidence.setdefault("source", source)
        self.conn.execute(
            "INSERT INTO readings (patient_id, at, temperature, spo2, pulse, respiration, "
            "source, provenance) VALUES (?,?,?,?,?,?,?,?)",
            (
                patient_id,
                float(at),
                vitals.get("temperature"),
                vitals.get("spo2"),
                vitals.get("pulse"),
                vitals.get("respiration"),
                source,
                _canonical_json(evidence),
            ),
        )

    def record_event(self, kind: str, detail: str, patient_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (at, kind, patient_id, detail) VALUES (?,?,?,?)",
            (time.time(), _label(kind, "event kind", maximum=64), patient_id, str(detail)),
        )
        self.conn.commit()

    def record_manual_override(
        self,
        patient_id: str,
        vital: str,
        value: float,
        reason: str,
        *,
        actor: str = "operator",
        session_id: str | None = None,
        at: float | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a manual simulation input and mirror it in the event log.

        This records an operator's requested value; it does not pretend the
        number came from a sensor and it does not itself mutate live readings.
        """
        if vital not in VITAL_UNITS:
            raise ValueError(f"unknown vital: {vital}")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("override value must be finite")
        when = float(at if at is not None else time.time())
        reason = _label(reason, "override reason", maximum=500)
        actor = _label(actor, "override actor", maximum=80)
        evidence = dict(provenance or {})
        evidence.update({"source": "manual_override", "actor": actor})
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO manual_overrides (patient_id, session_id, at, vital, value, unit, "
                "reason, actor, provenance) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    patient_id,
                    session_id,
                    when,
                    vital,
                    numeric,
                    VITAL_UNITS[vital],
                    reason,
                    actor,
                    _canonical_json(evidence),
                ),
            )
            override_id = int(cur.lastrowid)
            detail = {
                "override_id": override_id,
                "vital": vital,
                "value": numeric,
                "unit": VITAL_UNITS[vital],
                "reason": reason,
                "actor": actor,
                "session_id": session_id,
            }
            self.conn.execute(
                "INSERT INTO events (at, kind, patient_id, detail) VALUES (?,?,?,?)",
                (when, "manual_vital_override", patient_id, _canonical_json(detail)),
            )
        return {"id": override_id, "patient_id": patient_id, "at": when, **detail}

    def start_listening_session(
        self,
        *,
        languages: Sequence[str] = ("fr", "en"),
        client: str = "local-web",
        session_id: str | None = None,
        at: float | None = None,
    ) -> str:
        session_id = session_id or uuid.uuid4().hex
        if not _SESSION_TOKEN.fullmatch(session_id):
            raise ValueError("invalid session id")
        normalized_languages = []
        for language in languages:
            code = _label(language, "language", maximum=16).lower()
            if code not in normalized_languages:
                normalized_languages.append(code)
        if not normalized_languages:
            raise ValueError("at least one language is required")
        self.conn.execute(
            "INSERT INTO listening_sessions (id, started_at, ended_at, languages, client) "
            "VALUES (?,?,NULL,?,?)",
            (
                session_id,
                float(at if at is not None else time.time()),
                _canonical_json(normalized_languages),
                _label(client, "session client", maximum=80),
            ),
        )
        self.conn.commit()
        return session_id

    def record_consent(
        self,
        session_id: str,
        decision: str,
        *,
        method: str,
        language: str,
        policy_version: str,
        at: float | None = None,
    ) -> int:
        """Record consent intent without storing audio or a raw transcript."""
        if decision not in CONSENT_DECISIONS:
            raise ValueError(f"invalid consent decision: {decision}")
        if method not in CONSENT_METHODS:
            raise ValueError(f"invalid consent method: {method}")
        active = self.conn.execute(
            "SELECT 1 FROM listening_sessions WHERE id=? AND ended_at IS NULL",
            (session_id,),
        ).fetchone()
        if active is None:
            raise ValueError("listening session is not active")
        cur = self.conn.execute(
            "INSERT INTO consent_events (session_id, at, decision, method, language, "
            "policy_version) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                float(at if at is not None else time.time()),
                decision,
                method,
                _label(language, "consent language", maximum=16).lower(),
                _label(policy_version, "policy version", maximum=80),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def current_consent(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT at, decision, method, language, policy_version FROM consent_events "
            "WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def end_listening_session(self, session_id: str, *, at: float | None = None) -> None:
        cur = self.conn.execute(
            "UPDATE listening_sessions SET ended_at=? WHERE id=? AND ended_at IS NULL",
            (float(at if at is not None else time.time()), session_id),
        )
        if cur.rowcount != 1:
            self.conn.rollback()
            raise ValueError("unknown or already-ended session")
        self.conn.commit()

    def record_medical_document(
        self,
        patient_id: str,
        *,
        original_name: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        session_id: str | None = None,
        source: str = "operator_upload",
        blob_id: str | None = None,
        at: float | None = None,
    ) -> dict[str, Any]:
        """Store report metadata only; this method never receives a file path."""
        name = _label(original_name, "document name", maximum=240)
        if (
            name in {".", ".."}
            or "/" in name
            or "\\" in name
            or ":" in name
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("document name must not contain a path")
        media_type = _label(media_type, "media type", maximum=129).lower()
        if not _MEDIA_TYPE.fullmatch(media_type):
            raise ValueError("invalid media type")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise ValueError("document size must be a non-negative integer")
        size = size_bytes
        digest = str(sha256).lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError("sha256 must be 64 hexadecimal characters")
        blob_id = blob_id or uuid.uuid4().hex
        if not _BLOB_TOKEN.fullmatch(blob_id) or ".." in blob_id:
            raise ValueError("invalid blob id")
        document_id = uuid.uuid4().hex
        when = float(at if at is not None else time.time())
        source = _label(source, "document source", maximum=64)
        self.conn.execute(
            "INSERT INTO medical_documents (id, patient_id, session_id, added_at, "
            "original_name, media_type, size_bytes, sha256, blob_id, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                patient_id,
                session_id,
                when,
                name,
                media_type,
                size,
                digest,
                blob_id,
                source,
            ),
        )
        self.conn.commit()
        return {
            "id": document_id,
            "patient_id": patient_id,
            "session_id": session_id,
            "added_at": when,
            "original_name": name,
            "media_type": media_type,
            "size_bytes": size,
            "sha256": digest,
            "blob_id": blob_id,
            "source": source,
        }

    def medical_documents(self, patient_id: str) -> list[dict[str, Any]]:
        """Return document metadata without exposing filesystem paths."""
        rows = self.conn.execute(
            "SELECT id, patient_id, session_id, added_at, original_name, media_type, "
            "size_bytes, sha256, source FROM medical_documents "
            "WHERE patient_id=? ORDER BY added_at DESC, id DESC",
            (patient_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def medical_document(self, document_id: str) -> dict[str, Any] | None:
        """Resolve one opaque document id for the controlled blob store."""
        row = self.conn.execute(
            "SELECT id, patient_id, session_id, added_at, original_name, media_type, "
            "size_bytes, sha256, blob_id, source FROM medical_documents WHERE id=?",
            (document_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def history(self, patient_id: str, limit: int = 200) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT at, temperature, spo2, pulse, respiration, source, provenance FROM readings"
            " WHERE patient_id=? ORDER BY at DESC, id DESC LIMIT ?",
            (patient_id, max(1, min(int(limit), 10_000))),
        )
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            item["provenance"] = json.loads(item["provenance"])
            rows.append(item)
        return rows

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        with_pending = self.conn
        with_pending.commit()
        with_pending.close()
