"""Quarantine zone assignment — fast track, deterministic, no model.

The brief asks for quarantine management during the contamination crisis. The
rule we implement is deliberately simple and explainable, because on Friday
somebody will ask why a specific crew member was sealed into a specific zone
and the answer has to be one sentence.

A patient is isolated when they show a respiratory-transmissible pattern:
a fever together with either desaturation or raised respiration. Zones fill in
order and each has a capacity; when every zone is full the patient is flagged
as awaiting a bed rather than silently dropped.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .triage import TriageResult

FEVER_C = 38.0
LOW_SPO2 = 95.0
HIGH_RESP = 20.0


@dataclass
class Assignment:
    patient_id: str
    zone: str | None
    since: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "zone": self.zone,
            "since": self.since,
            "reason": self.reason,
            "awaiting_bed": self.zone is None,
        }


def needs_isolation(vitals: dict, triage: TriageResult) -> tuple[bool, str]:
    """Return (isolate, human-readable reason)."""
    temp = vitals.get("temperature")
    spo2 = vitals.get("spo2")
    resp = vitals.get("respiration")

    if temp is None or temp < FEVER_C:
        return False, "no fever"

    if spo2 is not None and spo2 < LOW_SPO2:
        return True, f"fever {temp:.1f} C with SpO2 {spo2:.0f}%"
    if resp is not None and resp > HIGH_RESP:
        return True, f"fever {temp:.1f} C with respiration {resp:.0f}/min"
    if triage.urgency.rank >= 2:
        return True, f"fever {temp:.1f} C with {triage.urgency.value} urgency"
    return False, "fever alone, monitoring"


class QuarantineRegistry:
    def __init__(self, zones: tuple[str, ...], capacity: int) -> None:
        self.zones = zones
        self.capacity = capacity
        self.assignments: dict[str, Assignment] = {}

    def occupancy(self) -> dict[str, int]:
        counts = {z: 0 for z in self.zones}
        for a in self.assignments.values():
            if a.zone in counts:
                counts[a.zone] += 1
        return counts

    def _next_zone(self) -> str | None:
        counts = self.occupancy()
        for z in self.zones:
            if counts[z] < self.capacity:
                return z
        return None

    def evaluate(self, patient_id: str, vitals: dict, triage: TriageResult) -> Assignment | None:
        """Assign or release. Returns the assignment only when it changed."""
        isolate, reason = needs_isolation(vitals, triage)
        existing = self.assignments.get(patient_id)

        if isolate and existing is None:
            a = Assignment(patient_id, self._next_zone(), time.time(), reason)
            self.assignments[patient_id] = a
            return a

        if not isolate and existing is not None:
            del self.assignments[patient_id]
            return Assignment(patient_id, None, time.time(), "released")

        # Already isolated but still waiting for a bed — retry placement.
        if isolate and existing is not None and existing.zone is None:
            zone = self._next_zone()
            if zone is not None:
                existing.zone = zone
                return existing
        return None

    def sealed_zones(self) -> list[str]:
        return [z for z, n in self.occupancy().items() if n > 0]

    def to_dict(self) -> dict:
        return {
            "zones": {
                z: {"occupied": n, "capacity": self.capacity, "sealed": n > 0}
                for z, n in self.occupancy().items()
            },
            "assignments": [a.to_dict() for a in self.assignments.values()],
            "awaiting_bed": sum(1 for a in self.assignments.values() if a.zone is None),
        }
