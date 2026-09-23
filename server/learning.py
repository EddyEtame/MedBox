"""What the station learns from every request, and how it uses it next time.

The command router (server/commands.py) understands a fixed list of phrases.
Anything outside it used to be filed as a declaration or dropped, so a crew
member who said « MedBox, montre-moi le plus malade » instead of « prioritaire »
got nothing. Two things fix that, and this module is the deterministic half:

1. A phrase book. Every phrasing that was ever resolved to an intent, by the
   model or by an operator's correction, is stored with the intent it meant.
   The next time the same words arrive they resolve here, with no model at
   all: what was learned once is deterministic from then on, and it survives a
   restart because it lives in the station's database.
2. A journal of every request: the words, what they resolved to, how (the
   allow-list, the phrase book, the model, or nothing) and for whom. It is
   what "MedBox learns from every request" means concretely, and it is what
   the Help panel shows a jury.

Nothing here touches a measurement, and nothing here is an intent the router
does not already know: the phrase book can only map words to one of the
router's own actions. The model half (server/ai/intent.py) is bounded the
same way, by a grammar.
"""
from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from typing import Iterable

# Intents the router executes. The model may only ever choose among these,
# and "none" — it cannot name an action the station does not have.
INTENTS: tuple[str, ...] = (
    "help", "worst", "next", "why", "isolated", "assess", "ask", "pause",
    "doctor_call", "report",
)

INTENT_LABELS_FR: dict[str, str] = {
    "help": "ouvrir l’aide",
    "worst": "montrer le membre le plus urgent",
    "next": "passer au membre suivant",
    "why": "expliquer le score du membre sélectionné",
    "isolated": "résumer l’isolement",
    "assess": "demander une évaluation à l’assistant",
    "ask": "demander les questions à poser",
    "pause": "mettre l’écoute en pause",
    "doctor_call": "enregistrer une demande d’appel médical",
    "report": "enregistrer une déclaration du membre",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS learned_phrases (
    phrase      TEXT PRIMARY KEY,
    intent      TEXT NOT NULL,
    source      TEXT NOT NULL CHECK(source IN ('model', 'operator')),
    example     TEXT NOT NULL,
    learned_at  REAL NOT NULL,
    uses        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS request_journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    text        TEXT NOT NULL,
    intent      TEXT NOT NULL,
    resolved_by TEXT NOT NULL CHECK(resolved_by IN ('allowlist', 'learned', 'model', 'none')),
    patient_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_at ON request_journal(at);
"""


def normalize(text: str) -> str:
    """Accent-free, lower-case, one space, the wake word removed.

    The same words in any spelling of the moment must be one phrase, or the
    book fills with near-duplicates and learns nothing.
    """
    folded = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    plain = re.sub(r"[’']", " ", plain)
    plain = re.sub(r"[^a-z0-9]+", " ", plain).strip()
    plain = re.sub(r"^(?:med ?box[ ,]*)+", "", plain).strip()
    return plain


class Learning:
    """The phrase book and the journal, on the station's own connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- the phrase book -------------------------------------------------
    def lookup(self, text: str) -> str | None:
        key = normalize(text)
        if not key:
            return None
        row = self.conn.execute(
            "SELECT intent FROM learned_phrases WHERE phrase = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE learned_phrases SET uses = uses + 1 WHERE phrase = ?", (key,)
        )
        self.conn.commit()
        return str(row[0])

    def learn(self, text: str, intent: str, source: str) -> bool:
        """Remember that these words mean this intent. Operators outrank the model."""
        if intent not in INTENTS or source not in ("model", "operator"):
            raise ValueError(f"cannot learn {intent!r} from {source!r}")
        key = normalize(text)
        if not key or len(key) > 200:
            return False
        existing = self.conn.execute(
            "SELECT source FROM learned_phrases WHERE phrase = ?", (key,)
        ).fetchone()
        if existing is not None and existing[0] == "operator" and source == "model":
            return False  # a correction by a person is never overwritten by a guess
        self.conn.execute(
            "INSERT INTO learned_phrases (phrase, intent, source, example, learned_at, uses) "
            "VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(phrase) DO UPDATE SET intent = excluded.intent, "
            "source = excluded.source, example = excluded.example, learned_at = excluded.learned_at",
            (key, intent, source, " ".join(str(text).split())[:200], time.time()),
        )
        self.conn.commit()
        return True

    def forget(self, text: str) -> bool:
        key = normalize(text)
        cur = self.conn.execute("DELETE FROM learned_phrases WHERE phrase = ?", (key,))
        self.conn.commit()
        return cur.rowcount > 0

    def phrases(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT example, intent, source, learned_at, uses FROM learned_phrases "
            "ORDER BY learned_at DESC"
        ).fetchall()
        return [
            {"example": r[0], "intent": r[1], "label_fr": INTENT_LABELS_FR.get(r[1], r[1]),
             "source": r[2], "learned_at": r[3], "uses": r[4]}
            for r in rows
        ]

    # ---- the journal -----------------------------------------------------
    def record(self, text: str, intent: str, resolved_by: str, patient_id: str | None) -> None:
        self.conn.execute(
            "INSERT INTO request_journal (at, text, intent, resolved_by, patient_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), " ".join(str(text).split())[:500], intent, resolved_by, patient_id),
        )
        self.conn.commit()

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT at, text, intent, resolved_by, patient_id FROM request_journal "
            "ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [
            {"at": r[0], "text": r[1], "intent": r[2], "label_fr": INTENT_LABELS_FR.get(r[2], r[2]),
             "resolved_by": r[3], "patient_id": r[4]}
            for r in rows
        ]

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM request_journal").fetchone()[0]
        by = dict(self.conn.execute(
            "SELECT resolved_by, COUNT(*) FROM request_journal GROUP BY resolved_by"
        ).fetchall())
        learned = self.conn.execute("SELECT COUNT(*) FROM learned_phrases").fetchone()[0]
        return {"requests": total, "by": by, "learned_phrases": learned}
