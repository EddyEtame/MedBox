"""What a crew member SAYS, kept strictly apart from what the box MEASURES.

A crew member says "I have had a headache since this morning" or "I keep
coughing". That is real clinical information and the assistant should have it.
It is also, by construction, unverifiable: no instrument recorded it.

So this module exists to hold one line: a reported symptom never changes the
NEWS2 score. Not a little, not indirectly, not in an edge case. NEWS2 is
computed from measurements in `triage.py`, which does not import this module
and never will. What is reported reaches the assistant as context and reaches
the screen as a quotation, labelled as the crew member's own words.

That separation is not bureaucracy, it is the answer to the hardest question
the project can be asked. A station that let a spoken complaint move a
clinical score would be a station where anyone could talk themselves into an
emergency response, and where the score no longer means what the Royal
College says it means.

The same holds for speech recognition. A transcript is a guess about what
someone said; when it arrives from a microphone it carries its confidence and
the interface shows it, because an operator acting on a misheard symptom
should be able to see that it was misheard.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Iterable

# Keep the last few per crew member. This is a triage station during an
# incident, not a medical record system; the database holds the full history.
PER_PATIENT = 8

SOURCES = ("typed", "voice")


@dataclass(frozen=True)
class Reported:
    """One thing a crew member said, with how we came to have it."""

    patient_id: str
    text: str
    at: float
    source: str = "typed"
    # Speech recognition confidence, 0-1, when this came from a microphone.
    # None for anything typed, because typing is not a guess.
    confidence: float | None = None

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "text": self.text,
            "at": self.at,
            "source": self.source,
            "confidence": self.confidence,
            # Repeated on every single record so no consumer can lose it.
            "measured": False,
        }


@dataclass
class SymptomLog:
    """Recent reported symptoms, per crew member.

    `on_record` is how this reaches storage. It is injected rather than
    imported so that nothing in the measurement path ever needs to know this
    module exists.
    """

    on_record: Callable[[str, str, str], None] | None = None
    _by_patient: dict[str, deque] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=PER_PATIENT))
    )

    def add(
        self,
        patient_id: str,
        text: str,
        source: str = "typed",
        confidence: float | None = None,
        at: float | None = None,
    ) -> Reported:
        text = " ".join(str(text).split())[:400]
        if not text:
            raise ValueError("a reported symptom cannot be empty")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        entry = Reported(
            patient_id=patient_id,
            text=text,
            at=time.time() if at is None else at,
            source=source,
            confidence=confidence,
        )
        self._by_patient[patient_id].append(entry)
        if self.on_record is not None:
            detail = f"[{source}] {text}"
            if confidence is not None:
                detail = f"[{source} {confidence:.0%}] {text}"
            self.on_record("symptom", detail, patient_id)
        return entry

    def for_patient(self, patient_id: str) -> list[dict]:
        """Newest first, because that is the order an operator reads them."""
        return [e.to_dict() for e in reversed(self._by_patient.get(patient_id, ()))]

    def clear(self, patient_id: str | None = None) -> None:
        if patient_id is None:
            self._by_patient.clear()
        else:
            self._by_patient.pop(patient_id, None)

    def prompt_note(self, patient_id: str) -> str:
        """The block handed to the assistant.

        It states, in the prompt itself, that these are unverified. A small
        model will not infer that from a heading, so it is spelled out where
        the model cannot miss it.
        """
        entries: Iterable[Reported] = reversed(self._by_patient.get(patient_id, ()))
        lines = [f'  - "{e.text}"' for e in entries]
        if not lines:
            return ""
        return (
            "\nReported by the crew member, in their own words. No instrument "
            "recorded these and they are NOT part of the NEWS2 score. Treat them "
            "as a claim to be checked, not as a finding:\n" + "\n".join(lines) + "\n"
        )
