"""The portable database starts useful and keeps an audit trail."""
from __future__ import annotations

import json
import sqlite3

import pytest

from server.db import BASELINE_RANGES, Database
from server.sensors.synthetic import ScenarioSource


def _db(tmp_path, name="medbox.db") -> Database:
    return Database(tmp_path / name)


def test_the_forty_person_roster_gets_stable_individual_healthy_profiles(tmp_path):
    roster = ScenarioSource(40).roster()
    first = _db(tmp_path, "first.db")
    second = _db(tmp_path, "second.db")
    try:
        first.upsert_patients(roster)
        second.upsert_patients(roster)
        profiles = first.baselines()
        comparison = second.baselines()

        assert len(profiles) == 40
        assert [p["patient_id"] for p in profiles] == [f"P-{n:02d}" for n in range(1, 41)]
        measured = [
            (p["temperature"], p["spo2"], p["pulse"], p["respiration"])
            for p in profiles
        ]
        assert len(set(measured)) == 40, "the crew must not share one cloned baseline"
        assert measured == [
            (p["temperature"], p["spo2"], p["pulse"], p["respiration"])
            for p in comparison
        ], "the same roster must rehearse from the same baseline"
        for profile in profiles:
            for vital, (low, high) in BASELINE_RANGES.items():
                assert low <= profile[vital] <= high
            assert profile["provenance"]["kind"] == "simulated_healthy_reference"
            assert profile["provenance"]["references"]
    finally:
        first.close()
        second.close()


def test_vital_observations_carry_provenance_and_cannot_be_rewritten(tmp_path):
    db = _db(tmp_path)
    try:
        db.upsert_patients([("P-01", "Alba Okonkwo", "Pilot")])
        db.record_reading(
            "P-01",
            1234.5,
            {"temperature": 38.1, "spo2": 95.0, "pulse": 91.0, "respiration": 20.0},
            "manual-simulator",
            {"scenario": "respiratory-hazard", "control": "temperature-slider"},
        )
        db.commit()
        row = db.history("P-01")[0]
        assert row["source"] == "manual-simulator"
        assert row["provenance"] == {
            "control": "temperature-slider",
            "scenario": "respiratory-hazard",
            "source": "manual-simulator",
        }

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.conn.execute("UPDATE readings SET temperature=36.8 WHERE patient_id='P-01'")
        db.conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.conn.execute("DELETE FROM readings WHERE patient_id='P-01'")
        db.conn.rollback()
    finally:
        db.close()


def test_a_manual_change_is_an_override_and_an_event_not_a_sensor_claim(tmp_path):
    db = _db(tmp_path)
    try:
        db.upsert_patients([("P-01", "Alba Okonkwo", "Pilot")])
        change = db.record_manual_override(
            "P-01",
            "temperature",
            38.7,
            "Exercice de crise: syndrome respiratoire",
            actor="jury-operator",
            at=80.0,
            provenance={"scenario": "respiratory-hazard"},
        )
        assert change["unit"] == "degC"
        stored = db.conn.execute("SELECT * FROM manual_overrides").fetchone()
        assert stored["value"] == 38.7
        assert json.loads(stored["provenance"])["source"] == "manual_override"
        event = db.conn.execute("SELECT kind, detail FROM events").fetchone()
        assert event["kind"] == "manual_vital_override"
        assert json.loads(event["detail"])["override_id"] == stored["id"]
    finally:
        db.close()


def test_continuous_listening_consent_is_versioned_without_a_voice_transcript(tmp_path):
    db = _db(tmp_path)
    try:
        session_id = db.start_listening_session(
            languages=("fr", "en"), session_id="demo-session", at=10.0
        )
        db.record_consent(
            session_id,
            "accepted",
            method="voice",
            language="fr",
            policy_version="continuous-listening-v1",
            at=12.0,
        )
        assert db.current_consent(session_id) == {
            "at": 12.0,
            "decision": "accepted",
            "method": "voice",
            "language": "fr",
            "policy_version": "continuous-listening-v1",
        }
        columns = {
            row["name"] for row in db.conn.execute("PRAGMA table_info(consent_events)")
        }
        assert "transcript" not in columns and "audio" not in columns
        db.end_listening_session(session_id, at=13.0)
        with pytest.raises(ValueError, match="not active"):
            db.record_consent(
                session_id,
                "accepted",
                method="voice",
                language="fr",
                policy_version="continuous-listening-v1",
                at=14.0,
            )
    finally:
        db.close()


def test_medical_report_storage_accepts_metadata_never_a_user_path(tmp_path):
    db = _db(tmp_path)
    try:
        db.upsert_patients([("P-01", "Alba Okonkwo", "Pilot")])
        report = db.record_medical_document(
            "P-01",
            original_name="bilan-sanguin.pdf",
            media_type="application/pdf",
            size_bytes=42_000,
            sha256="a" * 64,
            blob_id="blob-01",
        )
        assert report["blob_id"] == "blob-01"
        columns = {
            row["name"] for row in db.conn.execute("PRAGMA table_info(medical_documents)")
        }
        assert "path" not in columns
        with pytest.raises(ValueError, match="must not contain a path"):
            db.record_medical_document(
                "P-01",
                original_name="..\\private\\report.pdf",
                media_type="application/pdf",
                size_bytes=2,
                sha256="b" * 64,
            )
        with pytest.raises(ValueError, match="invalid blob id"):
            db.record_medical_document(
                "P-01",
                original_name="rapport.pdf",
                media_type="application/pdf",
                size_bytes=2,
                sha256="b" * 64,
                blob_id="C:report.pdf",
            )
    finally:
        db.close()


def test_an_existing_database_gains_provenance_without_losing_its_readings(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE patients (id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                               created_at REAL NOT NULL);
        CREATE TABLE readings (id INTEGER PRIMARY KEY AUTOINCREMENT,
                               patient_id TEXT NOT NULL REFERENCES patients(id), at REAL NOT NULL,
                               temperature REAL, spo2 REAL, pulse REAL, respiration REAL,
                               source TEXT NOT NULL);
        INSERT INTO patients VALUES ('P-01', 'Alba Okonkwo', 'Pilot', 1.0);
        INSERT INTO readings (patient_id, at, temperature, source)
          VALUES ('P-01', 2.0, 36.8, 'legacy-simulator');
        """
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        row = db.history("P-01")[0]
        assert row["temperature"] == 36.8
        assert row["provenance"] == {}
    finally:
        db.close()
