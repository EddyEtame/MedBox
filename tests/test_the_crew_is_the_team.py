"""The people on this ship are the team, each with a week of data, a page of
their own on their own port, and a referent who talks to them and tells the
crew when it decides something.

Eddy, 24 Sep: "we are going to be the people on this ship", "one server for
the main dashboard and other servers for the individual people", "a message
ping, a loud sound, click read and the AI starts speaking".
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402
from server.activities import for_crew, for_member  # noqa: E402
from server.db import BASELINE_PROFILE_VERSION as DB_VERSION, Database  # noqa: E402
from server.personal import personal_app  # noqa: E402
from server.sensors.synthetic import BASELINE_PROFILE_VERSION, TEAM, ScenarioSource  # noqa: E402
from server.spoken import spoken_isolation_message, spoken_personal_intro  # noqa: E402


def test_the_first_six_berths_are_the_team_and_the_rest_are_untouched():
    crew = list(ScenarioSource(40).patients.values())
    assert [(p.name, p.role) for p in crew[:6]] == TEAM
    assert crew[0].name == "Eddy" and crew[0].id == "P-01"
    # The generator's stream is untouched: the thirty-four others keep the
    # names the seed always gave them (spot check, the seventh berth).
    assert " " in crew[6].name and crew[6].name not in {n for n, _ in TEAM}
    assert len({p.name for p in crew}) == 40
    # Names in their baselines: two team members do not share one.
    assert crew[0].baseline != crew[1].baseline


def test_both_derivations_moved_to_the_same_profile_version():
    assert BASELINE_PROFILE_VERSION == DB_VERSION == "crew-roster-v3"


def test_a_week_is_seeded_once_and_summarised(tmp_path):
    db = Database(tmp_path / "crew.db")
    db.upsert_patients([("P-01", "Eddy", "Commandant de bord"), ("P-02", "Brad", "Ingénieur de vol")])
    base = {"P-01": {"temperature": 36.8, "spo2": 98.0, "pulse": 70.0, "respiration": 15.0, "systolic_bp": 120.0},
            "P-02": {"temperature": 36.6, "spo2": 97.5, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 118.0}}
    now = time.time()
    assert db.seed_week(base, now) == 2 * 7 * 4
    assert db.seed_week(base, now) == 0, "a second launch must not double the week"
    week = db.week_stats("P-01", now)
    assert week["count"] == 28 and len(week["daily"]) in (7, 8)
    t = week["vitals"]["temperature"]
    assert 36.5 <= t["min"] <= t["avg"] <= t["max"] <= 37.1
    assert all(abs(d["pulse"] - 70.0) <= 5.5 for d in week["daily"] if d["pulse"] is not None)
    # The seed is recorded as what it is, never as a measurement.
    row = db.conn.execute("SELECT source, provenance FROM readings WHERE patient_id='P-01' LIMIT 1").fetchone()
    assert row["source"] == "synthetic-week" and "weekly-seed" in row["provenance"]


def test_messages_are_written_once_pinged_and_read(tmp_path):
    db = Database(tmp_path / "msg.db")
    db.upsert_patients([("P-01", "Eddy", "Commandant de bord")])
    m = db.add_message("crew", "isolation_proposed", "Isolement décidé pour Eddy.", "Eddy présente de la fièvre.", "P-01")
    assert m["read_at"] is None and m["recipient"] == "crew"
    assert [x["id"] for x in db.messages("crew", unread_only=True)] == [m["id"]]
    assert db.messages("P-01") == []
    read = db.mark_read(m["id"])
    assert read["read_at"] is not None and read["spoken"] == "Eddy présente de la fièvre."
    assert db.messages("crew", unread_only=True) == []
    assert db.mark_read(999) is None


def test_the_referent_tells_the_crew_and_the_person_in_their_own_voice():
    change = {"patient_id": "P-02", "zone": None, "confirmed": False, "reason": "fever 38.0 C with respiration 24/min"}
    text, crew, me = spoken_isolation_message("Brad", "Ingénieur de vol", change)
    assert text.startswith("Isolement décidé pour Brad (Ingénieur de vol) : de la fièvre et une respiration rapide")
    assert crew == "Brad présente de la fièvre et une respiration rapide. J’ai décidé son isolement, zone à attribuer. Accusez réception."
    assert me.startswith("Brad, vous présentez de la fièvre et une respiration rapide. Je vous place en isolement.")
    _, crew2, me2 = spoken_isolation_message("Brad", "Ingénieur de vol", {**change, "confirmed": True, "zone": "A"})
    assert "zone A" in crew2 and ", zone A" in me2
    assert not any(ch.isdigit() for ch in crew + me)


def test_the_personal_intro_knows_who_it_is_talking_to():
    calm = spoken_personal_intro("Eddy", True, "routine", None)
    assert calm.startswith("Bonjour Eddy. Je suis MedBox, le référent médical du bord.")
    assert "plage habituelle" in calm and "tout est nominal" in calm and calm.endswith("Posez-moi vos questions.")
    ill = spoken_personal_intro("Brad", False, "high", {"confirmed": False})
    assert "des écarts" in ill and "décidé votre isolement" in ill
    assert "diagnostic" not in calm + ill


def test_activities_are_deterministic_and_keep_the_isolated_apart():
    day = 1_790_000_000.0
    assert for_crew(day) == for_crew(day) and len(for_crew(day)) == 3
    remote = for_crew(day, isolated=2)
    assert remote[0]["id"] in ("breathing", "checkin", "music")
    assert all(a["id"] in ("hydrate", "rest", "breath", "message") for a in for_member("high", True, day))
    assert len(for_member("routine", False, day)) == 2


def test_the_crew_week_and_the_personal_page_come_from_the_station():
    station.STATION._frame()
    week = asyncio.run(station.crew_week())
    assert week["summary"]["total"] == 40
    first = week["members"][0]
    assert first["id"] == "P-01" and first["name"] == "Eddy"
    assert set(first["week"]) == {"days", "count", "vitals", "daily"}
    assert len(week["activities"]) == 3
    me = asyncio.run(station.me("P-02"))
    assert me["name"] == "Brad" and me["intro"]["spoken"].startswith("Bonjour Brad.")
    assert len(me["activities"]) == 2 and "week_ok" in me
    with pytest.raises(HTTPException):
        asyncio.run(station.me("P-99"))


def test_an_isolation_decision_becomes_two_messages_once(monkeypatch):
    station.STATION._messaged.clear()
    patient = station.STATION.source.patients["P-03"]
    change = {"patient_id": "P-03", "zone": None, "confirmed": False, "reason": "fever 38.4 C with spo2 91 %",
              "requires_confirmation": True, "awaiting_bed": False, "since": time.time()}
    before = len(station.STATION.db.messages())
    station.STATION._message_for(change, patient)
    station.STATION._message_for(change, patient)
    after = station.STATION.db.messages(limit=500)
    assert len(after) == before + 2
    recipients = {m["recipient"] for m in after[:2]}
    assert recipients == {"crew", "P-03"}
    mine = [m for m in after[:2] if m["recipient"] == "P-03"][0]
    assert mine["spoken"].startswith("Davidson, vous présentez de la fièvre et un manque d’oxygène.")
    read = asyncio.run(station.read_message(mine["id"]))
    assert read["read_at"] is not None
    # The station singleton writes to the real database: leave no trace.
    with station.STATION.db.conn:
        station.STATION.db.conn.execute("DELETE FROM messages WHERE id IN (?, ?)", (after[0]["id"], after[1]["id"]))
    station.STATION._messaged.discard(("P-03", "proposed"))


def test_a_personal_server_opens_on_its_owner_and_runs_no_second_lifespan():
    app = personal_app("P-01")
    sent = []

    async def receive():
        return {"type": "lifespan.shutdown"}

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    assert sent == [{"type": "lifespan.shutdown.complete"}]
    sent.clear()
    asyncio.run(app({"type": "http", "path": "/", "method": "GET", "headers": []}, receive, send))
    assert sent[0]["status"] == 302 and (b"location", b"/me/P-01") in sent[0]["headers"]


def test_the_pages_exist_and_stay_guarded():
    for name in ("crew.html", "me.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert 'src="/static/voice.js"' in html and "voiceBtn" in html and "msgList" in html
    for name in ("crew.js", "me.js"):
        js = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "/api/messages/" in js and "AudioContext" in js, f"{name} must ping"
        lines = js.splitlines()
        for i, line in enumerate(lines):
            if "MedBox.voice." not in line and "MedBox.mic." not in line:
                continue
            same_line = "MedBox.voice)" in line or "!MedBox.voice" in line or "MedBox.mic)" in line
            # The repo's own rule (test_the_slow_track_cannot_stall_the_board):
            # a same-line test, or an early return a few lines above.
            early_return = any("!MedBox.voice" in back and "return" in back for back in lines[max(0, i - 15):i])
            assert same_line or early_return, f"{name}: {line.strip()}"
    me_js = (ROOT / "web" / "me.js").read_text(encoding="utf-8")
    assert "?me=1" in me_js and '"self": true' in me_js.replace("self: true", '"self": true')


def test_every_page_can_reach_every_other_and_each_personal_space():
    for name in ("ship.html", "index.html", "crew.html", "me.html"):
        assert 'src="/static/nav.js"' in (ROOT / "web" / name).read_text(encoding="utf-8"), name
    nav = (ROOT / "web" / "nav.js").read_text(encoding="utf-8")
    assert "/api/status" in nav and "personal_pages" in nav and "Espaces personnels" in nav
    body = asyncio.run(station.status())
    pages = body["personal_pages"]
    assert [p["name"] for p in pages] == [n for n, _ in TEAM]


def test_a_member_names_their_assistant_and_it_becomes_their_wake_word(tmp_path):
    db = Database(tmp_path / "pref.db")
    db.upsert_patients([("P-01", "Eddy", "Commandant de bord")])
    assert db.agent_name("P-01") == "MedBox"
    assert db.set_agent_name("P-01", "  Nova  ") == "Nova"
    assert db.set_agent_name("P-01", "") == "MedBox"
    out = asyncio.run(station.set_agent("P-02", {"name": "Astra"}))
    assert out["agent_name"] == "Astra"
    me = asyncio.run(station.me("P-02"))
    assert me["agent_name"] == "Astra" and "Je suis Astra, votre référent" in me["intro"]["spoken"]
    with pytest.raises(HTTPException):
        asyncio.run(station.set_agent("P-02", {"name": "x"}))
    with pytest.raises(HTTPException):
        asyncio.run(station.set_agent("P-02", {"name": "R2D2!"}))
    asyncio.run(station.set_agent("P-02", {"name": ""}))
    assert asyncio.run(station.me("P-02"))["agent_name"] == "MedBox"
    mic = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    assert "setWakeName: setWakeName" in mic and "wakePattern()" in mic
    me_js = (ROOT / "web" / "me.js").read_text(encoding="utf-8")
    assert "MedBox.mic.setWakeName(" in me_js and "/agent" in me_js
