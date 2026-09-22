"""Two bugs that would have surfaced on stage, and the guards against them.

Neither showed up in any earlier test because both live in the wiring rather
than the logic: one in the order routes are declared, one in the order rows
are sorted.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.app import app, triage_order  # noqa: E402
from server.triage import assess  # noqa: E402


def _route_for(method: str, path: str):
    """Ask the real router what it would dispatch, in declaration order."""
    scope = {"type": "http", "method": method, "path": path, "headers": [],
             "root_path": "", "query_string": b""}
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match.name == "FULL":
            return getattr(route, "endpoint", route).__name__
    return None


def test_stop_is_not_swallowed_by_the_scenario_name_route():
    """Reset used to 404.

    /api/scenario/{name} was declared before /api/scenario/stop, and Starlette
    matches in declaration order, so "stop" was read as a scenario name. The
    Reset button in both views silently failed and the scenario kept running —
    a thing that would have been discovered live, in front of the jury.
    """
    assert _route_for("POST", "/api/scenario/stop") == "stop_scenario"
    assert _route_for("POST", "/api/scenario/contamination") == "start_scenario"


def test_the_symptom_route_is_not_swallowed_either():
    assert _route_for("POST", "/api/patient/P-01/symptom") == "report_symptom"
    assert _route_for("GET", "/api/patient/P-01") == "patient"


def _row(pid: str, **vitals) -> dict:
    return {"patient": {"id": pid}, "triage": assess(**vitals).to_dict()}


def test_an_urgent_crew_member_is_not_filed_below_a_less_urgent_one():
    """The single-parameter-3 rule is why the board cannot sort on the total.

    Respiration of 25 scores 3 on its own, which NEWS2 escalates to medium —
    urgent review — on an aggregate of only 3. Someone scoring 4 spread thinly
    across parameters is banded low and needs a ward review. Sorting on the
    aggregate put the urgent one second.
    """
    urgent = _row("P-02", temperature=36.8, spo2=98.0, pulse=72.0, respiration=25.0)
    milder = _row("P-01", temperature=35.8, spo2=94.0, pulse=115.0, respiration=19.0)

    assert urgent["triage"]["urgency"] == "medium"
    assert milder["triage"]["urgency"] == "low"
    assert urgent["triage"]["total"] < milder["triage"]["total"], (
        "this test is meaningless unless the urgent crew member really does "
        "have the lower aggregate"
    )

    assert sorted([milder, urgent], key=triage_order)[0] is urgent


def test_within_a_band_the_higher_aggregate_comes_first():
    worse = _row("P-09", temperature=39.1, spo2=92.0, pulse=118.0, respiration=25.0)
    bad = _row("P-08", temperature=39.1, spo2=93.0, pulse=118.0, respiration=22.0)
    assert worse["triage"]["urgency"] == bad["triage"]["urgency"] == "high"
    assert worse["triage"]["total"] > bad["triage"]["total"]
    assert sorted([bad, worse], key=triage_order)[0] is worse


def test_ties_break_on_id_so_the_board_does_not_shuffle():
    """A board that reorders equal rows every frame is unreadable."""
    a = _row("P-05", temperature=36.8, spo2=98.0, pulse=72.0, respiration=16.0)
    b = _row("P-03", temperature=36.8, spo2=98.0, pulse=72.0, respiration=16.0)
    assert [r["patient"]["id"] for r in sorted([a, b], key=triage_order)] == ["P-03", "P-05"]


def test_nothing_served_reaches_for_the_internet():
    """FastAPI's /docs and /redoc load Swagger, ReDoc and fonts from CDNs.

    On a station whose claim is "no internet at any point", those were the
    only pages that could not work offline.
    """
    served = {getattr(r, "path", "") for r in app.routes}
    for path in ("/docs", "/redoc"):
        assert path not in served, f"{path} is still served"
