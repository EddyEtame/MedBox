"""Real sensor head over USB serial — the ESP32 in the medical case.

BRAD OWNS THIS FILE. It is a working stub with the contract already fixed, so
the rest of the system needs no change when real hardware arrives: implement
`sample()` and the board, the triage and the AI all light up unchanged.

Expected wire format, one JSON object per line at 20 Hz:

    {"patient":"P-01","t":37.1,"spo2":97.4,"hr":78,"rr":16}

Keep it line-delimited JSON. It is trivial to debug with a serial monitor and
costs nothing at this rate.
"""
from __future__ import annotations

import json
import time

from .base import Reading


class SerialSource:
    name = "serial"

    def __init__(self, port: str, baud: int = 115200) -> None:
        self.port = port
        self.baud = baud
        self._serial = None

    def start(self) -> None:
        try:
            import serial  # pyserial — add to requirements.txt when you start this
        except ImportError as exc:  # pragma: no cover - hardware path
            raise RuntimeError(
                "pyserial is not installed. Add `pyserial==3.5` to requirements.txt "
                "and re-run setup, then plug the ESP32 in."
            ) from exc
        self._serial = serial.Serial(self.port, self.baud, timeout=0)

    def stop(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def sample(self, now: float) -> list[Reading]:
        if self._serial is None:
            return []
        out: list[Reading] = []
        while self._serial.in_waiting:
            raw = self._serial.readline().decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                # A half-written line at startup is normal. Skip it, never crash.
                continue
            out.append(
                Reading(
                    patient_id=str(d.get("patient", "P-01")),
                    at=now or time.time(),
                    temperature=d.get("t"),
                    spo2=d.get("spo2"),
                    pulse=d.get("hr"),
                    respiration=d.get("rr"),
                    source="serial",
                )
            )
        return out
