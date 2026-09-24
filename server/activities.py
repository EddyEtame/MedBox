"""What the crew can do together, and what one member can do alone, to stay well.

Deterministic, chosen by the day and by the state of the ship. The model
never writes these: a ship's referent proposes the same things a good crew
chief would, and the list is short enough to be honest about.
"""
from __future__ import annotations

import datetime as _dt

GROUP = [
    {"id": "sport", "title": "Séance de sport collective", "when": "30 min, module central",
     "why": "Le mouvement quotidien tient le pouls de repos et le moral."},
    {"id": "breathing", "title": "Respiration guidée en groupe", "when": "10 min après le repas",
     "why": "Ralentit la respiration de repos et fait redescendre la tension."},
    {"id": "game", "title": "Jeu de société de bord", "when": "Soirée, carré",
     "why": "Rire ensemble est la première défense contre l’isolement mental."},
    {"id": "cooking", "title": "Cuisine en équipe", "when": "Tour de rôle, deux par deux",
     "why": "Un repas préparé ensemble se mange mieux et se partage."},
    {"id": "cinema", "title": "Cinéma de bord", "when": "Un film choisi à tour de rôle",
     "why": "Une heure hors du vaisseau, sans quitter le vaisseau."},
    {"id": "walk", "title": "Marche en boucle, module vert", "when": "20 min, lumière pleine",
     "why": "Lumière et pas réguliers : sommeil et humeur en profitent."},
    {"id": "music", "title": "Musique et chant", "when": "Après le quart du soir",
     "why": "Respirer, projeter la voix, et se souvenir de la Terre."},
    {"id": "checkin", "title": "Tour de table : comment ça va", "when": "5 min, chaque matin",
     "why": "Dire où l’on en est vaut mieux qu’attendre qu’un capteur le voie."},
]

# For a member in isolation: nothing that brings people together.
PERSONAL = [
    {"id": "hydrate", "title": "Boire un verre d’eau maintenant", "why": "La fièvre et l’air sec du vaisseau déshydratent vite."},
    {"id": "rest", "title": "Vingt minutes de repos allongé", "why": "Le pouls redescend plus vite couché que debout."},
    {"id": "breath", "title": "Respiration lente, quatre secondes, six secondes", "why": "Fait baisser la fréquence respiratoire et l’inquiétude."},
    {"id": "read", "title": "Lecture ou audio, loin des écrans", "why": "Le repos mental compte autant que le repos du corps."},
    {"id": "stretch", "title": "Étirements doux, dix minutes", "why": "Garde le corps mobile sans monter le pouls."},
    {"id": "message", "title": "Écrire un message à l’équipage", "why": "L’isolement n’est pas la solitude."},
]


def _day_index(now: float | None = None) -> int:
    day = (_dt.datetime.fromtimestamp(now) if now else _dt.datetime.now()).date()
    return day.toordinal()


def for_crew(now: float | None = None, isolated: int = 0, count: int = 3) -> list[dict]:
    """Three shared activities for today; with people isolated, the remote ones first."""
    start = _day_index(now) % len(GROUP)
    picks = [GROUP[(start + i) % len(GROUP)] for i in range(count)]
    if isolated:
        remote = [a for a in GROUP if a["id"] in ("breathing", "checkin", "music")]
        picks = (remote + [a for a in picks if a not in remote])[:count]
    return picks


def for_member(urgency: str | None, isolated: bool, now: float | None = None, count: int = 2) -> list[dict]:
    """Two things one person can do now, depending on how they are."""
    if isolated or urgency in ("high", "medium"):
        pool = [a for a in PERSONAL if a["id"] in ("hydrate", "rest", "breath", "message")]
    elif urgency == "low":
        pool = [a for a in PERSONAL if a["id"] in ("hydrate", "breath", "stretch", "read")]
    else:
        pool = [a for a in PERSONAL if a["id"] in ("stretch", "read", "breath", "message")]
    start = _day_index(now) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(count)]


# What the fittest member of the week is doing right: chosen from their id,
# so the same person keeps the same habits from one day to the next.
HABITS = [
    "une marche quotidienne en boucle dans le module vert",
    "dix minutes de respiration lente le soir",
    "un sommeil régulier, sept heures, à heure fixe",
    "un verre d’eau à chaque quart",
    "des étirements au réveil",
    "un vrai repas assis, sans écran",
    "du sport collectif trois fois par semaine",
    "un tour de table chaque matin pour dire comment ça va",
]


def habits_for(patient_id: str, count: int = 3) -> list[str]:
    import hashlib

    start = int.from_bytes(hashlib.blake2b(patient_id.encode(), digest_size=2).digest(), "big") % len(HABITS)
    return [HABITS[(start + i * 3) % len(HABITS)] for i in range(count)]
