"""Isolation recommendation and berth assignment — deterministic, no model.

The brief asks for quarantine management during the contamination crisis. The
rule we implement is deliberately simple and explainable, because on Friday
somebody will ask why a specific crew member was sealed into a specific zone
and the answer has to be one sentence.

Vital signs can show deterioration; they cannot prove contagiousness. In the
interactive station a scenario/exposure flag plus a concerning pattern creates
an isolation *candidate*. A human confirms the berth assignment, and only a
human releases it. The registry can retain its legacy automatic mode for
isolated unit tests, but the MedBox application does not use that mode.
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
    confirmed: bool = True

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "zone": self.zone,
            "since": self.since,
            "reason": self.reason,
            "confirmed": self.confirmed,
            "requires_confirmation": not self.confirmed,
            "awaiting_bed": self.confirmed and self.zone is None,
        }


def needs_isolation(
    vitals: dict,
    triage: TriageResult,
    *,
    exposure_confirmed: bool = True,
) -> tuple[bool, str]:
    """Return (isolate, human-readable reason)."""
    if not exposure_confirmed:
        return False, "no confirmed scenario exposure"
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
    def __init__(
        self,
        zones: tuple[str, ...],
        capacity: int,
        *,
        require_confirmation: bool = False,
        allow_automatic_release: bool = True,
    ) -> None:
        self.zones = zones
        self.capacity = capacity
        self.require_confirmation = require_confirmation
        self.allow_automatic_release = allow_automatic_release
        self.assignments: dict[str, Assignment] = {}
        # Who shared a zone with whom, and when (Brad, Dev 2): the contact
        # trace the crew dashboard and the record show. Persisted by the
        # station every couple of seconds.
        self.contacts: list[dict] = []

    def _enter(self, patient_id: str, zone: str | None, now: float) -> None:
        if zone is None:
            return
        for other in self.assignments.values():
            if other.patient_id != patient_id and other.confirmed and other.zone == zone:
                self.contacts.append(dict(patient_a=patient_id, patient_b=other.patient_id,
                                          zone=zone, since=now, until=None))

    def _leave(self, patient_id: str, now: float) -> None:
        for contact in self.contacts:
            if contact["until"] is None and patient_id in (contact["patient_a"], contact["patient_b"]):
                contact["until"] = now

    def reset(self) -> None:
        """A scenario ends: every stay ends now, the registry empties."""
        now = time.time()
        for pid in list(self.assignments):
            self._leave(pid, now)
        self.assignments.clear()

    def occupancy(self) -> dict[str, int]:
        counts = {z: 0 for z in self.zones}
        for a in self.assignments.values():
            if a.confirmed and a.zone in counts:
                counts[a.zone] += 1
        return counts

    def _next_zone(self) -> str | None:
        counts = self.occupancy()
        for z in self.zones:
            if counts[z] < self.capacity:
                return z
        return None

    def evaluate(
        self,
        patient_id: str,
        vitals: dict,
        triage: TriageResult,
        *,
        exposure_confirmed: bool = True,
    ) -> Assignment | None:
        """Create a candidate or legacy assignment when the state changes."""
        isolate, reason = needs_isolation(
            vitals, triage, exposure_confirmed=exposure_confirmed
        )
        existing = self.assignments.get(patient_id)

        if isolate and existing is None:
            confirmed = not self.require_confirmation
            a = Assignment(
                patient_id,
                self._next_zone() if confirmed else None,
                time.time(),
                reason,
                confirmed=confirmed,
            )
            self.assignments[patient_id] = a
            return a

        if not isolate and existing is not None and self.allow_automatic_release:
            self._leave(patient_id, time.time())
            del self.assignments[patient_id]
            return Assignment(patient_id, None, time.time(), "released", confirmed=True)

        # Already isolated but still waiting for a bed — retry placement.
        if isolate and existing is not None and existing.confirmed and existing.zone is None:
            zone = self._next_zone()
            if zone is not None:
                existing.zone = zone
                self._enter(patient_id, zone, time.time())
                return existing
        return None

    def confirm(self, patient_id: str) -> Assignment:
        """Confirm a candidate and allocate the next berth if one is free."""
        existing = self.assignments.get(patient_id)
        if existing is None:
            raise KeyError(patient_id)
        if not existing.confirmed:
            existing.confirmed = True
            existing.zone = self._next_zone()
            existing.since = time.time()
            self._enter(patient_id, existing.zone, existing.since)
        return existing

    def release(self, patient_id: str, reason: str = "manual release") -> Assignment:
        """Remove a candidate/assignment only after an explicit operator action."""
        existing = self.assignments.pop(patient_id, None)
        if existing is None:
            raise KeyError(patient_id)
        self._leave(patient_id, time.time())
        return Assignment(patient_id, None, time.time(), reason, confirmed=True)

    def sealed_zones(self) -> list[str]:
        return [z for z, n in self.occupancy().items() if n > 0]

    def to_dict(self) -> dict:
        return {
            "zones": {
                z: {"occupied": n, "capacity": self.capacity, "sealed": n > 0}
                for z, n in self.occupancy().items()
            },
            "assignments": [a.to_dict() for a in self.assignments.values()],
            "candidates": sum(1 for a in self.assignments.values() if not a.confirmed),
            "awaiting_bed": sum(
                1 for a in self.assignments.values() if a.confirmed and a.zone is None
            ),
            # Release is a person's decision, never a timer's (Eddy, 23 Sep).
            "release_policy": {"manual_only": not self.allow_automatic_release, "simulation_only": True},
        }
