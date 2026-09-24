"""What the station says out loud, and the reason it can say it offline.

Two rules hold this module up.

**The station speaks from measurements, never for the model.** Every line
below is triggered by something `triage.py` or `quarantine.py` computed, and
the text is fixed in this file. The assistant's words are never spoken. That
is not squeamishness: a spoken sentence carries far more authority than the
same sentence on screen, and the one output we cannot constrain is the one
that should never get a voice. Kill Ollama and the station keeps talking,
because nothing it says was ever the model's to say.

**The spoken surface is finite, so it is pre-rendered.** `sensors/synthetic.py`
seeds the crew with a fixed seed, so the forty names are identical on every
machine, on every run, forever. Add the fixed lines below and the complete set
of things this station can ever say is about sixty short clips. So they are
rendered once, with Piper, on a developer's machine, committed as WAVs, and
served by the static mount that already exists.

Three things fall out of that, and they are why this is the right design
rather than a shortcut:

- The demo laptop needs no speech engine, no model, no Python audio stack and
  no network. It plays audio files.
- It cannot be slow, because there is nothing to synthesise. The latency is a
  disk read.
- It solves a licence problem. piper-tts is GPL-3.0-or-later, so shipping the
  engine would make MedBox GPL-3. We never ship it: it runs offline at build
  time and what ships is audio. The LJ Speech voice is public domain.

A line is a name clip followed by a phrase clip, played with a short gap
between them. That is a composition trick — it turns forty names times twenty
phrases into forty plus twenty — but it also happens to be right. A ship's
announcement is not a smooth sentence. It is a PA system, and the small pause
after the name is what a PA sounds like.
"""
from __future__ import annotations

from dataclasses import dataclass

# Twelve words is the cap, and it is a hard one. A spoken line the operator
# cannot hold in their head while looking at a patient is worse than silence,
# and anything longer stops being an alert and becomes narration.
MAX_WORDS = 12

# The fixed phrases. The key is the filename stem under web/speech/.
# In French, because the station is presented in French and the screen is
# French: a voice in another language than the words under it is the first
# thing a jury hears. "Score d'alerte", never "NEWS2" out loud: the acronym is
# on screen for whoever wants it, and spoken it is a noise.
PHRASES: dict[str, str] = {
    # --- urgency, the only clinical thing the station ever says out loud ---
    # "de sept ou plus": without the "de" the voice ran "sept ou" together and
    # the station's own speech model heard "c'est tout plus".
    "band_high": "Score d’alerte de sept ou plus. Réponse d’urgence.",
    "band_medium": "Revue urgente. Prévenir le responsable médical.",
    "band_single_param": "Un seul paramètre à trois. Revue urgente.",
    "band_clear": "Retour dans les valeurs habituelles.",

    # --- isolation: proposed by the station, decided by a person ---
    "isolation_proposed": "Isolement proposé. Confirmation humaine requise.",
    "quarantine_assigned": "Place d’isolement attribuée.",
    "quarantine_released": "Isolement levé par l’opérateur.",
    # One per zone. Two zones closing in the same minute sounded like the same
    # announcement twice, which reads as a stuck machine rather than as the
    # outbreak spreading. Naming the zone is also simply more useful.
    "zone_a_sealed": "Zone A scellée.",
    "zone_b_sealed": "Zone B scellée.",
    "zone_c_sealed": "Zone C scellée.",
    "zone_overflow": "Isolement complet. Aucune place disponible.",

    # --- the assistant, which is the beat the demo is built around ---
    # The station announcing its own assistant's death, in its own voice, while
    # every number on screen keeps updating, is the clearest possible statement
    # of the architecture. It is also literally true.
    "ai_down": "L’assistant s’est arrêté. Les mesures continuent.",
    "ai_back": "L’assistant est de nouveau actif.",
    "ai_stand_in": "Un substitut répond. Ce n’est pas un modèle de langage.",
    "ai_blocked": "L’assistant a dépassé son rôle. La station l’a bloqué.",

    # --- the session ---
    # The first thing the voice says once someone switches it on: who it is,
    # and the one rule. Heard by Eddy on 24 Sep as a missing introduction.
    "intro": "Bonjour, je suis MedBox, l’assistant de bord.",
    "intro_rule": "Je surveille l’équipage et je prends les décisions médicales du bord.",
    # After consent, and after the wake word: the voice answers, it does not
    # only write. Eddy, 24 Sep: "he did not voice out, he just wrote text".
    "consent_ok": "Merci. Préférez-vous le français ou l’anglais ?",
    "lang_fr": "Très bien, je vous réponds en français.",
    "wake_ack": "Oui ? Que puis-je faire pour vous ?",
    "scenario_started": "Scénario en cours.",
    "scenario_stopped": "Scénario arrêté. Retour aux valeurs de base.",
    "ready": "MedBox prêt. Quarante personnes à bord.",
}

# The consent notice, as it is SAID. The full notice is always on screen in
# the listening panel (web/mic.js); this is the same commitment in the words
# one says out loud, short enough to hold a room, and it is the one line here
# that is allowed past the twelve-word cap because it is a notice, not an
# alert. web/voice.js plays it as consent_fr.wav before it will hear "oui".
CONSENT_SPOKEN = (
    "Je suis MedBox, le référent médical du bord, hors ligne. "
    "J’évalue l’équipage, je décide des isolements et je réponds à vos questions. "
    "Je ne prescris aucun médicament. "
    "Avec votre accord, le microphone reste actif pendant cette session, pour "
    "entendre le mot MedBox. Aucun son n’est conservé. Vous pouvez arrêter "
    "l’écoute à tout moment. Pour accepter, dites : j’accepte."
)


@dataclass(frozen=True)
class Utterance:
    """One thing to say: an optional name clip, then a phrase clip."""

    phrase: str                     # a key of PHRASES
    patient_id: str | None = None   # whose name to say first, if anyone's
    name: str | None = None

    def to_dict(self) -> dict:
        return {
            "phrase": self.phrase,
            "patient_id": self.patient_id,
            "name": self.name,
            "text": (f"{self.name}. " if self.name else "") + PHRASES[self.phrase],
        }


def name_stem(name: str) -> str:
    """The filename for a crew member's name clip.

    Deliberately not the patient id. A stem built from the name means the
    rendered clip and the person are obviously connected when you look in
    web/speech/, and a file that has gone missing is obvious rather than
    cryptic.
    """
    return "name_" + "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


class Announcer:
    """Decides what is worth saying, from state changes only.

    It holds the previous band per crew member so it can speak on the
    *transition* rather than on every frame. A station that announced a HIGH
    band ten times a second would be turned off inside a minute, and an
    operator who turns the sound off loses the one channel that works while
    they are looking at the patient instead of the screen.
    """

    # How bad each band is, for deciding whether a change is worth saying.
    RANK = {"routine": 0, "low": 1, "medium": 2, "high": 3}

    def __init__(self) -> None:
        # The WORST band announced for each crew member since they were last
        # clear, not simply the previous one. Vitals are noisy, so somebody
        # sitting on the medium boundary flaps across it, and tracking only
        # the previous band announced them again on every re-entry. On a real
        # outbreak that is the same four names over and over, which is how an
        # operator learns to ignore the thing that is meant to interrupt them.
        self._worst: dict[str, int] = {}
        self._band: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._ai_up: bool | None = None
        self._sealed: set[str] = set()
        # Isolation states already said, per crew member, so a candidate that
        # is re-evaluated every tick is proposed out loud once.
        self._isolation: dict[str, str] = {}
        # Lines queued by a route (confirm, release) for the next frame to say.
        self._pending: list[Utterance] = []

    def reset(self) -> None:
        self._band.clear()
        self._worst.clear()
        self._sealed.clear()
        self._isolation.clear()
        self._pending.clear()
        # Deliberately not clearing _ai_up: the assistant's state is a property
        # of the machine, not of the scenario, and re-announcing it because
        # somebody pressed Reset would be noise.

    def on_board(self, rows: list[dict]) -> list[Utterance]:
        """Called with each board frame. Returns what to say, usually nothing."""
        out: list[Utterance] = []
        for row in rows:
            pid = row["patient"]["id"]
            name = row["patient"]["name"]
            self._names[pid] = name
            triage = row["triage"]
            band = triage["urgency"]
            was = self._band.get(pid)
            self._band[pid] = band
            if was is None:
                # First sight. Starting the program is not forty events.
                self._worst[pid] = self.RANK.get(band, 0)
                continue

            rank = self.RANK.get(band, 0)
            worst = self._worst.get(pid, 0)

            if band == "routine" and worst >= self.RANK["medium"]:
                # Recovery, and the only thing that re-arms the alerts.
                self._worst[pid] = 0
                out.append(Utterance("band_clear", pid, name))
                continue

            # Only a NEW worst is worth saying. Sliding back down and up again
            # is the same news, and the second telling is what teaches an
            # operator to stop listening.
            if rank <= worst:
                continue
            self._worst[pid] = rank
            if band == "high":
                out.append(Utterance("band_high", pid, name))
            elif band == "medium":
                phrase = "band_single_param" if triage.get("single_param_3") else "band_medium"
                out.append(Utterance(phrase, pid, name))
        return out

    def on_quarantine(self, change: dict, sealed: list[str]) -> list[Utterance]:
        """One line per isolation STATE change: proposed, placed, waiting, lifted.

        The change dict is quarantine.Assignment.to_dict(). It used to be read
        for "assigned" and "overflow" keys it never had, so a berth was never
        announced and the overflow line was dead; and a candidate, the moment
        the whole three-state design turns on, said nothing at all.
        """
        out: list[Utterance] = []
        pid = change.get("patient_id")
        name = self._names.get(pid) if pid else None
        reason = str(change.get("reason", "")).lower()
        if reason == "released" or "lev" in reason:
            state = "released"
        elif not change.get("confirmed"):
            state = "proposed"
        elif change.get("zone") is None:
            state = "waiting"
        else:
            state = "placed"
        if pid and self._isolation.get(pid) != state:
            self._isolation[pid] = state
            if state == "proposed":
                out.append(Utterance("isolation_proposed", pid, name))
            elif state == "placed":
                out.append(Utterance("quarantine_assigned", pid, name))
            elif state == "waiting":
                out.append(Utterance("zone_overflow"))
            elif state == "released":
                out.append(Utterance("quarantine_released", pid, name))
                self._isolation.pop(pid, None)
        now_sealed = set(sealed)
        # One announcement per zone that has newly sealed, not one per frame
        # for as long as it stays sealed.
        for zone in sorted(now_sealed - self._sealed):
            key = f"zone_{zone.lower()}_sealed"
            if key in PHRASES:
                out.append(Utterance(key))
        self._sealed = now_sealed
        return out

    def later(self, change: dict, sealed: list[str]) -> None:
        """A route confirmed or released somebody: say it on the next frame."""
        self._pending.extend(self.on_quarantine(change, sealed))

    def drain(self) -> list[Utterance]:
        out, self._pending = self._pending, []
        return out

    def on_ai(self, available: bool, stand_in: bool) -> list[Utterance]:
        if self._ai_up == available:
            return []
        first = self._ai_up is None
        self._ai_up = available
        if first:
            # Say nothing on the first observation. Starting the program is not
            # an event, and announcing "the assistant has stopped" because it
            # had not finished probing yet would be a lie told at boot.
            return [Utterance("ai_stand_in")] if (available and stand_in) else []
        if not available:
            return [Utterance("ai_down")]
        return [Utterance("ai_stand_in" if stand_in else "ai_back")]


def every_clip(crew_names: list[str]) -> dict[str, str]:
    """Every clip that has to exist, as stem -> text. The renderer's whole job.

    This is also what makes "pre-render everything" checkable rather than
    hopeful: the set is computable, so a test can assert that the files on disk
    match it exactly, and a missing one is caught here rather than by silence
    on stage.
    """
    clips = dict(PHRASES)
    clips["consent_fr"] = CONSENT_SPOKEN
    for name in crew_names:
        clips[name_stem(name)] = name
    return clips
