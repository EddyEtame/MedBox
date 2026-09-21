"""SQLite persistence. Created on first run, no migration tool needed.

Everything MedBox records lands here: the crew roster, every reading, every
triage snapshot and every quarantine movement. The file is the medical history
the brief asks for, and it is what makes a session replayable afterwards.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    at          REAL NOT NULL,
    temperature REAL,
    spo2        REAL,
    pulse       REAL,
    respiration REAL,
    source      TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS quarantine (
    patient_id  TEXT PRIMARY KEY REFERENCES patients(id),
    zone        TEXT NOT NULL,
    since       REAL NOT NULL,
    reason      TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: uvicorn's threadpool may touch this.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL keeps reads from blocking the write path during the demo.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_patients(self, rows: Iterable[tuple[str, str, str]]) -> None:
        now = time.time()
        self.conn.executemany(
            "INSERT OR IGNORE INTO patients (id, name, role, created_at) VALUES (?,?,?,?)",
            [(pid, name, role, now) for pid, name, role in rows],
        )
        self.conn.commit()

    def record_reading(self, patient_id: str, at: float, vitals: dict[str, Any], source: str) -> None:
        self.conn.execute(
            "INSERT INTO readings (patient_id, at, temperature, spo2, pulse, respiration, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                patient_id,
                at,
                vitals.get("temperature"),
                vitals.get("spo2"),
                vitals.get("pulse"),
                vitals.get("respiration"),
                source,
            ),
        )

    def record_event(self, kind: str, detail: str, patient_id: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (at, kind, patient_id, detail) VALUES (?,?,?,?)",
            (time.time(), kind, patient_id, detail),
        )
        self.conn.commit()

    def history(self, patient_id: str, limit: int = 200) -> list[dict]:
        cur = self.conn.execute(
            "SELECT at, temperature, spo2, pulse, respiration FROM readings"
            " WHERE patient_id=? ORDER BY at DESC LIMIT ?",
            (patient_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        with_pending = self.conn
        with_pending.commit()
        with_pending.close()
