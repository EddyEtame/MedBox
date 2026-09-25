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
    from server.config import CONFIG
    assert week["summary"]["total"] == CONFIG.ship.crew_size   # six since 25 Sep: the team, one room each
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

def test_every_dashboard_listens_like_the_ship_page():
    """Eddy, 24 Sep: "All personal dashboards should be like the main one...
    there's still voice constantly on, that triggers when medbox is called".
    The crew page and each personal page load the microphone, give it the
    button the dock needs, and take the station's ears from the board frame.
    A personal page also tells the microphone the speaker is its member."""
    for name in ("crew.html", "me.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert 'src="/static/mic.js"' in html, name
        assert 'id="micBtn"' in html, name
    for name in ("crew.js", "me.js"):
        js = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "MedBox.mic.setAvailable(m.ears.available, m.ears.error)" in js, name
        assert "MedBox.mic.attach(" in js, name
    me_js = (ROOT / "web" / "me.js").read_text(encoding="utf-8")
    assert "MedBox.mic.setSelf(true)" in me_js
    mic = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    assert "self: selfMode" in mic and "setSelf: setSelf" in mic
    app = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert '"self": bool(body.get("self"))' in app

def test_the_featured_member_is_one_of_the_team_when_one_qualifies():
    """Eddy, 24 Sep: "have someone that has best health and promote people to
    follow the health strategies". The person held up has a face and a page:
    a team member, unless none of them is in routine today."""
    from server import app as station

    def member(pid, urgency="routine", spread=0.0):
        return {"id": pid, "name": pid, "role": "Équipage", "today": {"urgency": urgency}, "isolation": None,
                "baseline": {"temperature": 36.6, "spo2": 98, "pulse": 70, "respiration": 14, "systolic_bp": 120},
                "week": {"vitals": {k: {"min": v - spread, "max": v + spread, "mean": v} for k, v in
                                    {"temperature": 36.6, "spo2": 98, "pulse": 70, "respiration": 14, "systolic_bp": 120}.items()}},
                "habits": []}

    # A synthetic member with a flatter week than every teammate still loses
    # to the flattest teammate in routine.
    members = [member("P-01", spread=0.5), member("P-02", spread=0.2), member("P-18", spread=0.0)]
    assert station._champion(members)["id"] == "P-02"
    # No teammate in routine: the crew member is featured rather than nobody.
    members = [member("P-01", "high"), member("P-02", "medium"), member("P-18", spread=0.0)]
    assert station._champion(members)["id"] == "P-18"

def test_the_dock_folds_once_it_listens_and_the_featured_member_links_to_their_space():
    """The consent text covered the board, the crew table and the personal
    page at laptop size (1366 x 768, 24 Sep). The dock folds to a pill once it
    listens, opens on a wake or an error, and the corner button pins the
    person's choice. The featured member's name opens their space."""
    mic = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    assert 'id="micFoldBtn"' in mic and "function setFolded(" in mic and "function autoFold(" in mic
    assert "pinned = true; setFolded(!folded);" in mic
    assert 'code === "LISTENING" && consented' in mic
    crew = (ROOT / "web" / "crew.js").read_text(encoding="utf-8")
    assert 'title=\\"Son espace personnel\\"' in crew
    for name in ("me.html", "crew.html"):
        html = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert '<span class="mark" aria-hidden="true"></span>' in html and 'class="logo"' not in html, name

def test_the_answer_carries_its_own_reason_and_the_referent_says_un_instant():
    """The station's fallback sentence names its reason (down, late, nothing
    found), so no page appends a stale « l'assistant est arrêté » suffix;
    while a real answer is on its way the referent says so, out loud, but
    only when the answer is not immediate."""
    for name in ("app.js", "ship.js", "me.js"):
        js = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "réponse de la station" not in js, name
        assert "thinking.stop()" in js and "MedBox.thinking.start(" in js, name
    crew = (ROOT / "web" / "crew.js").read_text(encoding="utf-8")
    assert "à confirmer</small>" in crew
    ship_css = (ROOT / "web" / "ship.css").read_text(encoding="utf-8")
    assert "body.embed .hud.top" in ship_css and "body.embed .hud.legend" in ship_css
    titles = {name: (ROOT / "web" / name).read_text(encoding="utf-8") for name in ("index.html", "ship.html", "crew.html", "me.html")}
    assert "<title>Tableau · MedBox</title>" in titles["index.html"]
    assert "<title>Vaisseau · MedBox</title>" in titles["ship.html"]
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    assert "@keyframes rise" in css and "prefers-reduced-motion" in css

def test_the_embedded_ship_waits_for_a_placed_node_before_flying():
    """/ship?embed=1&focus=P-06 went black: the focus flew the camera to a
    node that had no position yet (first board frame before first render
    frame), and the camera target became NaN. flyTo waits for the frame."""
    ship = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")
    assert "if (n.sx === undefined) { requestAnimationFrame(function () { flyTo(id); }); return; }" in ship

def test_the_microphone_waits_for_the_end_of_speech_and_starts_as_a_pill():
    """Eddy, 24 Sep: "wait when speaking totally stops before you start
    transcribing (you cut speaking after a long while)". Longer, adaptive
    pauses; a hysteresis so soft syllables stay in; a 30 s ceiling that only
    cuts on a dip. And the dock starts folded, with its own « Activer », so
    the page is readable before consent."""
    mic = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    assert "var END_SILENCE_MS = 1400;" in mic and "var END_SILENCE_LONG_MS = 1900;" in mic
    assert "var MAX_UTTERANCE_MS = 30000;" in mic and "var HARD_STOP_MS = 40000;" in mic
    assert "keepThreshold" in mic and "startThreshold" in mic
    assert "(spoken >= MAX_UTTERANCE_MS && !loud)" in mic
    assert 'id="micPillArm"' in mic and "setFolded(true);" in mic
    assert "noiseSuppression: true" in mic and "echoCancellation: true" in mic

def test_the_referent_thinks_out_loud_while_an_answer_is_on_its_way():
    """Eddy, 24 Sep: "if thinking is taking a while, add things that show
    thinking is going on". thinking.js shows the honest steps (constants,
    baseline, isolation registers, possibilities, phrasing) with the seconds
    ticking, and says « un instant » once; the three asks and the three
    assessments use it."""
    js = (ROOT / "web" / "thinking.js").read_text(encoding="utf-8")
    assert "Je relève les constantes" in js and "J’examine toutes les possibilités" in js and "Je formule ma réponse" in js
    assert "Un instant, je regarde vos constantes." in js and "root.MedBox.thinking = { start: start" in js
    for name in ("index.html", "ship.html", "me.html"):
        assert 'src="/static/thinking.js"' in (ROOT / "web" / name).read_text(encoding="utf-8"), name
    for name, n in (("app.js", 2), ("ship.js", 2), ("me.js", 2)):
        src = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert src.count("MedBox.thinking.start(") == n, name
        assert src.count("thinking.stop()") >= n, name

def test_the_ship_has_rooms_the_referent_can_show():
    """Eddy, 24 Sep: "a room view and a ship view; the AI can show rooms for
    quarantine while giving briefs; see health". Berths in every zone, a
    camera that rides the ring into a zone, a room panel with each member's
    health, spoken zone briefs, a « ronde », and local view commands typed
    or spoken. The card's embedded ship opens on the room."""
    ship = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")
    for needle in ("function buildBerths(", "function buildZoneFrame(", "function viewZone(", "function viewMedbay(",
                   "function viewShip(", "function renderRoom(", "function zoneBrief(", "function shipBrief(",
                   "function tour(", "function localCommand(", "cam.follow", "state.berthOf[a.patient_id]",
                   "window.MedBox.ship = {", "if (gz >= 0) viewZone(gz);", "if (localCommand(text)) return;"):
        assert needle in ship, needle
    html = (ROOT / "web" / "ship.html").read_text(encoding="utf-8")
    for needle in ('id="roomPanel"', 'id="roomMembers"', 'id="roomBrief"', 'id="roomNext"', 'id="roomBack"', 'id="tourBtn"'):
        assert needle in html, needle
    css = (ROOT / "web" / "ship.css").read_text(encoding="utf-8")
    assert ".hud.room{" in css and "body.embed .hud.room" in css
    mic = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    assert "MedBox.ship.local(text)" in mic

def test_the_ship_page_draws_a_hull_under_its_overlay():
    """Eddy, 24 Sep: "the space ship view should look like an actual space
    ship". A vendored three.js draws the hull (ring, spokes, core, spine,
    engines, arrays) on a canvas under the overlay, with the camera ship.js
    computes; without the script, the overlay draws as before."""
    html = (ROOT / "web" / "ship.html").read_text(encoding="utf-8")
    assert '<canvas id="hull"' in html and 'src="/static/vendor/three.min.js"' in html and 'src="/static/hull.js"' in html
    assert html.index('src="/static/hull.js"') < html.index('src="/static/nav.js"')
    ship = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")
    assert "MedBox.hull.init(" in ship and "MedBox.hull.render({" in ship and "alpha: hullOn" in ship
    hull = (ROOT / "web" / "hull.js").read_text(encoding="utf-8")
    for needle in ("function buildShell(", "function buildInterior(", "ExtrudeGeometry", "clippingPlanes", "root.MedBox.hull = {"):
        assert needle in hull, needle
    assert (ROOT / "web" / "vendor" / "three.min.js").stat().st_size > 100_000


def test_the_plan_places_crew_beds_and_rooms_for_both_layers():
    """Eddy, 24 Sep: "something that actually looks like a spaceship and
    feels like people can stay in it for a long time"; "we're supposed to
    see the rooms inside". layout.js is the one plan both the overlay and the
    hull build from: forty cabins on deck 1, the infirmary and three isolation
    rooms with four beds each on deck 2, and the camera for each view."""
    lay = (ROOT / "web" / "layout.js").read_text(encoding="utf-8")
    for needle in ("function cabin(", "function zoneBox(", "function bedBox(", "function berth(", "function infirmarySlot(",
                   "function plan(", "function cameraFor(", "root.MedBox.layout = {"):
        assert needle in lay, needle
    html = (ROOT / "web" / "ship.html").read_text(encoding="utf-8")
    assert html.index('src="/static/layout.js"') < html.index('src="/static/hull.js"')
    ship = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")
    for needle in ("LAY.cabin(idx - 1)", "LAY.infirmarySlot(docked++)", "LAY.berth(zi, slot)", "LAY.plan()",
                   'LAY.cameraFor("zone", i)', 'LAY.cameraFor("medbay")', "if (!LAY) spin += dt"):
        assert needle in ship, needle

