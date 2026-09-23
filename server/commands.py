"""Deterministic, allow-listed voice/typed command classification.

This module deliberately has no model import.  A wake-word transcript is
untrusted text: it may ask the interface to perform one of the small actions
below, or it may be filed as something a selected crew member said.  It can
never become code, a URL, a database query, or an instruction to the LLM.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    kind: str
    reported_text: str | None = None


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def classify(text: str) -> Command:
    """Classify a short post-consent phrase, failing closed to a report."""
    raw = str(text or "").strip()
    value = normalize(raw)
    if not value:
        return Command("empty")

    exact: tuple[tuple[set[str], str], ...] = (
        ({"aide", "help", "que peux tu faire", "qu est ce que tu peux faire"}, "help"),
        ({"prioritaire", "pire", "worst", "le plus urgent", "qui est prioritaire"}, "worst"),
        ({"suivant", "next", "patient suivant", "membre suivant"}, "next"),
        ({"pourquoi", "why", "explique le score", "explique ce score"}, "why"),
        ({"isoles", "isolement", "isolated", "zones d isolement"}, "isolated"),
        ({"evaluer", "evalue", "assess", "evaluation"}, "assess"),
        ({"demander", "questions", "ask", "quoi demander"}, "ask"),
        ({"pause", "mets l ecoute en pause", "suspendre l ecoute"}, "pause"),
    )
    for phrases, kind in exact:
        if value in phrases:
            return Command(kind)

    if re.search(
        r"\b(appelle|appeler|alerte|alerter|contacte|contacter)\b.*\b(medecin|docteur|medical)\b",
        value,
    ) or value in {"call doctor", "call the doctor", "medical alert"}:
        return Command("doctor_call")

    # Whisper often emits bracketed labels such as [cough].  They are only a
    # possible audible event and must still be confirmed by a person.
    if re.fullmatch(r"(?:toux|cough|atchoum|achoo|eternuement|sneeze)", value):
        return Command("audible_event", reported_text=raw)

    report = re.match(
        r"^\s*(?:déclar(?:e|é)|declare|déclaration|declaration|dit|a dit|said|reported)"
        r"\s*[:,-]?\s*(.+)$",
        raw,
        re.IGNORECASE,
    )
    if report and report.group(1).strip():
        return Command("report", reported_text=report.group(1).strip())

    # Natural statements after the wake word are patient-reported context,
    # never measurements.  The caller requires a selected patient before it
    # stores this fallback.
    return Command("report", reported_text=raw)
