"""Contracts for the deterministic, evidence-anchored sensor simulator."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.sensors.synthetic import (  # noqa: E402
    HEALTHY_BASELINE_RANGES,
    TEMP_TO_PULSE_BPM_PER_C,
    TEMP_TO_RESP_PER_MIN_PER_C,
    ScenarioSource,
)
from server.db import healthy_baseline  # noqa: E402
from server.quarantine import needs_isolation  # noqa: E402
from server.scenarios import load  # noqa: E402
from server.triage import Urgency, assess  # noqa: E402


def _vitals(source: ScenarioSource, now: float) -> list[dict]:
    return [reading.vitals() for reading in source.sample(now)]


def test_personal_baselines_are_stable_distinct_and_healthy():
    first = ScenarioSource(12, seed=2080)
    replay = ScenarioSource(12, seed=2080)

    assert first.baseline_records() == replay.baseline_records()
    baselines = [record["healthy_baseline"] for record in first.baseline_records()]
    assert len({tuple(row.items()) for row in baselines}) == len(baselines)

    for baseline in baselines:
        for vital, value in baseline.items():
            low, high = HEALTHY_BASELINE_RANGES[vital]
            assert low <= value <= high
        assert assess(**baseline).urgency is Urgency.ROUTINE


def test_sensor_baselines_match_the_database_seed_profiles():
    source = ScenarioSource(5, seed=2080)
    for patient in source.patients.values():
        persisted = healthy_baseline(patient.id, patient.name, patient.role)
        assert patient.baseline == {
            vital: persisted[vital]
            for vital in ("temperature", "spo2", "pulse", "respiration", "systolic_bp")
        }


def test_persisted_baselines_can_be_reloaded_as_source_of_truth():
    source = ScenarioSource(1)
    source.set_baselines(
        {"P-01": {"temperature": 36.6, "spo2": 97.5, "pulse": 65, "respiration": 14}}
    )
    # A profile persisted before the cuff existed: the four given values are
    # the source of truth, and the pressure comes from the same deterministic
    # derivation the database uses, never from the legacy midpoint.
    patient = source.patients["P-01"]
    assert {k: patient.baseline[k] for k in ("temperature", "spo2", "pulse", "respiration")} == {
        "temperature": 36.6,
        "spo2": 97.5,
        "pulse": 65.0,
        "respiration": 14.0,
    }
    assert patient.baseline["systolic_bp"] == healthy_baseline(patient.id, patient.name, patient.role)["systolic_bp"]


def test_replay_depends_on_elapsed_simulation_time_not_wall_clock():
    early = ScenarioSource(3, seed=2080)
    late = ScenarioSource(3, seed=2080)

    early.apply_deltas(
        ["P-01"],
        {"temperature": 1.7, "spo2": -5.0, "pulse": 31, "respiration": 8},
        30,
        1_000,
    )
    late.apply_deltas(
        ["P-01"],
        {"temperature": 1.7, "spo2": -5.0, "pulse": 31, "respiration": 8},
        30,
        9_000,
    )

    assert _vitals(early, 1_000) == _vitals(late, 9_000)
    assert _vitals(early, 1_017.5) == _vitals(late, 9_017.5)
    assert _vitals(early, 1_050) == _vitals(late, 9_050)

    early.reset()
    early.apply_deltas(
        ["P-01"],
        {"temperature": 1.7, "spo2": -5.0, "pulse": 31, "respiration": 8},
        30,
        20_000,
    )
    assert _vitals(early, 20_017.5) == _vitals(late, 9_017.5)


def test_temperature_only_change_uses_documented_associations_not_spo2():
    source = ScenarioSource(1)
    patient = source.patients["P-01"]
    source.apply_deltas([patient.id], {"temperature": 1.25}, 20, 100)

    changes = patient.trajectory.adjustments
    assert changes["temperature"] == 1.25
    assert changes["pulse"] == 1.25 * TEMP_TO_PULSE_BPM_PER_C
    assert changes["respiration"] == 1.25 * TEMP_TO_RESP_PER_MIN_PER_C
    assert "spo2" not in changes


def test_one_manual_channel_change_does_not_erase_prior_changes():
    source = ScenarioSource(1)
    source.apply_deltas(["P-01"], {"temperature": 1.0}, 20, 100)
    source.apply_deltas(
        ["P-01"],
        {"spo2": -4.0},
        20,
        105,
        infer_temperature_associations=False,
    )

    changes = source.patients["P-01"].trajectory.adjustments
    assert changes == {
        "temperature": 1.0,
        "pulse": TEMP_TO_PULSE_BPM_PER_C,
        "respiration": TEMP_TO_RESP_PER_MIN_PER_C,
        "spo2": -4.0,
    }


def test_each_vital_has_an_independent_delay_and_duration():
    source = ScenarioSource(1)
    patient = source.patients["P-01"]
    source.apply_deltas(
        [patient.id],
        {"temperature": 1.0, "spo2": -4.0},
        40,
        100,
        delays={"temperature": 0, "spo2": 12},
        durations={"temperature": 10, "spo2": 20},
        infer_temperature_associations=False,
    )
    path = patient.trajectory

    assert path.delays == {"temperature": 0.0, "spo2": 12.0}
    assert path.durations == {"temperature": 10.0, "spo2": 20.0}
    assert path.value("temperature", patient.baseline["temperature"], 11) == path.targets["temperature"]
    assert path.value("spo2", patient.baseline["spo2"], 11) == path.origin["spo2"]
    assert path.value("spo2", patient.baseline["spo2"], 33) == path.targets["spo2"]


def test_legacy_absolute_target_call_still_works():
    source = ScenarioSource(1)
    source.afflict(
        ["P-01"],
        {"temperature": 38.7, "spo2": 92.0, "pulse": 110, "respiration": 24},
        10,
        100,
    )
    assert source.patients["P-01"].trajectory.targets == {
        "temperature": 38.7,
        "spo2": 92.0,
        "pulse": 110.0,
        "respiration": 24.0,
    }


def test_provenance_is_explicit_and_json_serializable():
    source = ScenarioSource(2)
    source.apply_deltas(["P-01"], {"temperature": 1.0}, 20, 100)
    metadata = source.metadata()

    assert metadata["clock"]["mode"] == "accelerated"
    assert "SIMULÉES" in metadata["label_fr"]
    assert "P-01" in metadata["active_adjustments"]
    assert any("LLM" in limit for limit in metadata["limits_fr"])
    json.dumps(metadata)


def test_shipped_scenarios_declare_delta_mode_and_no_diagnosis():
    scenario_paths = sorted((ROOT / "scenarios").glob("*.yaml"))
    assert len(scenario_paths) >= 6

    for path in scenario_paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        simulation = raw.get("simulation", {})
        assert simulation.get("clock") == "accelerated", path.name
        assert simulation.get("adjustment_mode") == "delta-from-personal-healthy-baseline", path.name
        assert simulation.get("diagnostic_claim") == "none", path.name
        for step in raw.get("timeline", []):
            if step.get("do") != "afflict":
                continue
            assert step.get("mode") == "delta", path.name
            assert step.get("provenance"), path.name
            # Temperature values in shipped scenarios are changes in Celsius,
            # not implausibly uniform absolute body temperatures.
            assert -5.0 <= float(step["temperature"]) <= 5.0, path.name


def test_main_scenario_reliably_reaches_six_isolation_candidates():
    """The 15% brief claim must survive personal baselines and sensor motion."""

    source = ScenarioSource(40, seed=2080)
    scenario = load("contamination")
    source.sample(0)
    for step in scenario.steps:
        if step.action != "afflict":
            continue
        count = int(step.payload.get("patients", 1))
        targets = {
            key: float(value)
            for key, value in step.payload.items()
            if key in ("temperature", "spo2", "pulse", "respiration")
        }
        source.afflict(
            source.healthy_ids()[:count],
            targets,
            float(step.payload.get("over", 30)),
            step.at,
        )

    affected = [
        reading
        for reading in source.sample(70)
        if source.patients[reading.patient_id].contaminated
    ]
    decisions = [
        needs_isolation(reading.vitals(), assess(**reading.vitals()))[0]
        for reading in affected
    ]
    assert len(affected) == 6
    assert decisions == [True] * 6


def _run_scenario(stem: str) -> tuple[list, list[bool]]:
    scenario = load(stem)
    source = ScenarioSource(scenario.crew, seed=2080)
    source.sample(0)
    finish = 0.0
    for step in scenario.steps:
        finish = max(finish, step.at)
        if step.action != "afflict":
            continue
        count = int(step.payload.get("patients", 1))
        targets = {
            key: float(value)
            for key, value in step.payload.items()
            if key in ("temperature", "spo2", "pulse", "respiration")
        }
        over = float(step.payload.get("over", 30))
        finish = max(finish, step.at + over + 9)
        source.afflict(
            source.healthy_ids()[:count],
            targets,
            over,
            step.at,
            mode=str(step.payload["mode"]),
            provenance=str(step.payload["provenance"]),
        )

    affected = [
        reading
        for reading in source.sample(finish + 1)
        if source.patients[reading.patient_id].contaminated
    ]
    isolation = [
        needs_isolation(reading.vitals(), assess(**reading.vitals()))[0]
        for reading in affected
    ]
    return affected, isolation


def test_every_shipped_scenario_produces_an_observable_vital_alert():
    for path in sorted((ROOT / "scenarios").glob("*.yaml")):
        affected, _ = _run_scenario(path.stem)
        assert affected, path.name
        assert any(
            assess(**reading.vitals()).urgency is not Urgency.ROUTINE
            for reading in affected
        ), f"{path.name} finishes without any visible triage change"


def test_group_hazard_scenario_proposes_three_isolations():
    affected, isolation = _run_scenario("exposition-environnementale")
    assert len(affected) == 3
    assert isolation == [True, True, True]
