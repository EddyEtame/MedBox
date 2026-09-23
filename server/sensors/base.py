"""The contract every sensor source implements."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Protocol


@dataclass(frozen=True)
class Reading:
    patient_id: str
    at: float
    temperature: float | None = None
    spo2: float | None = None
    pulse: float | None = None
    respiration: float | None = None
    # Systolic blood pressure, mmHg: the fifth instrument, a cuff.
    systolic_bp: float | None = None
    source: str = "synthetic"

    def vitals(self) -> dict:
        return {
            "temperature": self.temperature,
            "spo2": self.spo2,
            "pulse": self.pulse,
            "respiration": self.respiration,
            "systolic_bp": self.systolic_bp,
        }

    def to_dict(self) -> dict:
        return asdict(self)


class SensorSource(Protocol):
    """Anything that can produce readings.

    `synthetic.ScenarioSource` drives from a YAML file. `serial_head.SerialSource`
    reads a real ESP32 over USB. The server does not care which it got.
    """

    name: str

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def sample(self, now: float) -> list[Reading]: ...
