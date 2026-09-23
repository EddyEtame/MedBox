"""SQLite persistence. Created on first run, no migration tool needed.

Everything MedBox records lands here: the crew roster, every reading, every
triage snapshot and every quarantine movement. The file is the medical history
the brief asks for, and it is what makes a session replayable afterwards.
"""
from __future__ import annotations

import sqlite3
import json
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    patient_a TEXT NOT NULL, patient_b TEXT NOT NULL, zone TEXT NOT NULL,
    since REAL NOT NULL, until REAL,
    PRIMARY KEY(patient_a, patient_b, zone, since)
);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answers_patient ON answers(patient_id, at);
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

    def history(self, patient_id: str, limit: int = 200, since: float = 0) -> list[dict]:
        cur = self.conn.execute(
            "SELECT at, temperature, spo2, pulse, respiration FROM readings"
            " WHERE patient_id=? AND at>=? ORDER BY at DESC LIMIT ?",
            (patient_id, since, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def commit(self) -> None:
        self.conn.commit()

    def record_answer(self, patient_id: str, question: str, answer: str) -> dict:
        at = time.time()
        cur = self.conn.execute(
            "INSERT INTO answers(patient_id, question, answer, at) VALUES (?,?,?,?)",
            (patient_id, question, answer, at),
        )
        self.conn.commit()
        return dict(id=cur.lastrowid, patient_id=patient_id, question=question, answer=answer, at=at)

    def answers(self, patient_id: str, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM answers WHERE patient_id=? ORDER BY id DESC LIMIT ?",
            (patient_id, limit),
        )]

    def record_triage(self, patient_id: str, at: float, result: dict) -> None:
        previous = self.conn.execute(
            "SELECT urgency FROM triage_snapshots WHERE patient_id=? ORDER BY id DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        if previous is None or previous["urgency"] != result["urgency"]:
            self.conn.execute(
                "INSERT INTO triage_snapshots(patient_id,at,total,urgency,detail) VALUES (?,?,?,?,?)",
                (patient_id, at, result["total"], result["urgency"], json.dumps(result)),
            )

    def triage_history(self, patient_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT at,total,urgency FROM triage_snapshots WHERE patient_id=? ORDER BY id DESC LIMIT 100",
            (patient_id,),
        )]

    def recent_events(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,),
        )]

    def save_contacts(self, contacts: list[dict]) -> None:
        self.conn.executemany(
            "INSERT INTO contacts VALUES (:patient_a,:patient_b,:zone,:since,:until) "
            "ON CONFLICT(patient_a,patient_b,zone,since) DO UPDATE SET until=excluded.until",
            contacts,
        )
        self.conn.commit()

    def sessions(self) -> list[dict]:
        starts = self.conn.execute(
            "SELECT * FROM events WHERE kind='scenario_start' ORDER BY id DESC LIMIT 20"
        ).fetchall()
        result = []
        next_id = 9223372036854775807
        for start in starts:
            events = self.conn.execute(
                "SELECT * FROM events WHERE id>? AND id<? AND kind IN ('scenario_stop','afflict','quarantine') ORDER BY id",
                (start['id'], next_id),
            ).fetchall()
            stop = next((e for e in events if e['kind'] == 'scenario_stop'), None)
            result.append(dict(name=start['detail'], since=start['at'],
                               until=stop['at'] if stop else None,
                               events=[dict(e) for e in events[-20:]]))
            next_id = start['id']
        return result

    def contacts(self, patient_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM contacts WHERE patient_a=? OR patient_b=? ORDER BY since DESC LIMIT 100",
            (patient_id, patient_id),
        )]

    def close(self) -> None:
        with_pending = self.conn
        with_pending.commit()
        with_pending.close()
