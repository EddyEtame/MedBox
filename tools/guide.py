"""Builds docs/USER_GUIDE.md out of the product itself.

There are two guides in this project and they must never disagree.

One is on the screen: press Help and the station renders what it can do, what
it refuses to do, and every phrase you can type at it. The other is the one a
jury can hold, print and mark. A hand-written second guide would be correct on
the day it was written and wrong by the demo, because the only thing keeping
it true would be somebody remembering.

So the paper guide is generated. Everything factual in it is read out of the
code that has to honour it:

  - what it does, will not do, and answers to   server/ai/capabilities.py
  - the crew, the zones, the port, the model     config.toml
  - the NEWS2 bands                              server/triage.py, by running it
  - the scenarios                                scenarios/*.yaml

`--check` regenerates and compares, and a test runs it. Change a capability
and forget the guide, and the suite says so before a reader does.

Standard library only, and so is everything it imports, so this runs on a bare
`python` with nothing installed. A document you cannot rebuild because the
virtual environment is broken is a document you will ship stale.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.ai.capabilities import (  # noqa: E402
    CAPABILITIES,
    REFUSALS,
    SHORTCUTS,
)
from server.ai.schemas import FIT_LEVELS, SIGN_SOURCES  # noqa: E402
from server.config import CONFIG  # noqa: E402
from server.triage import Urgency, band  # noqa: E402

OUT = ROOT / "docs" / "USER_GUIDE.md"
SCENARIO_DIR = ROOT / "scenarios"

BANNER = (
    "<!-- Généré par tools/guide.py à partir du produit. Ne pas modifier à la "
    "main : exécuter `python tools/guide.py`, sinon la prochaine génération "
    "écrasera les changements. -->"
)

BAND_LABELS = {
    "routine": "nominal",
    "low": "faible",
    "medium": "moyen",
    "high": "élevé",
}

BAND_ACTIONS = {
    "routine": "Surveillance habituelle.",
    "low": "Faire revoir la personne par un professionnel compétent.",
    "medium": "Revue urgente et escalade vers le responsable médical.",
    "high": "Réponse d’urgence et surveillance continue.",
}

SOURCE_LABELS = {
    "temperature": "température",
    "spo2": "SpO₂",
    "pulse": "pouls",
    "respiration": "fréquence respiratoire",
    "reported_by_crew_member": "déclaré par le membre, non mesuré",
}

FIT_LABELS = {
    "one measurement fits": "une mesure concorde",
    "several measurements fit": "plusieurs mesures concordent",
    "all measured parameters fit": "tous les paramètres mesurés concordent",
}


# --------------------------------------------------------------- small helpers
def cell(text: str) -> str:
    """A table cell. A stray pipe would silently split a column in two."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def band_rows() -> list[tuple[str, str, str]]:
    """The band table, derived by running band() rather than transcribed.

    Transcribing it is how a guide ends up describing thresholds the code
    stopped using. The range 0..20 covers every aggregate four parameters can
    produce and then some.
    """
    rows: list[tuple[str, str, str]] = []
    start = 0
    for total in range(21):
        here = band(total, False)
        nxt = band(total + 1, False) if total < 20 else None
        if nxt is not here:
            span = f"{start}" if start == total else f"{start}\u2013{total}"
            if total == 20:
                span = f"{start} or more"
            rows.append((span, here.value, here.response))
            start = total + 1
    return rows


def single_param_escalates_to() -> Urgency:
    """What one parameter scoring 3 does on its own, asked of the code."""
    return band(0, True)


def scenarios() -> list[tuple[str, str, str]]:
    """(endpoint name, title, description) for every scenario file.

    Parsed with regexes rather than PyYAML on purpose: this module is
    stdlib-only. It reads two fields out of files this repository owns, not
    arbitrary YAML, and if a file ever stops matching it falls back to the
    filename instead of failing the build of a document.
    """
    found = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        title = ""
        match = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        if match:
            title = match.group(1).strip().strip("\"'")
        description = ""
        block = re.search(r"^description:\s*(>[-+]?|\|[-+]?)?\s*\n((?:[ \t]+.*\n?)+)",
                          text, re.MULTILINE)
        if block:
            description = " ".join(line.strip() for line in block.group(2).splitlines())
        else:
            inline = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
            if inline:
                description = inline.group(1).strip().strip("\"'")
        found.append((path.stem, title or path.stem, description.strip()))
    return found


# ------------------------------------------------------------------- the guide
def build() -> str:
    """Construire le guide français depuis les contrats exécutables du produit."""
    ship, ai, server = CONFIG.ship, CONFIG.ai, CONFIG.server
    url = f"http://{server.host}:{server.port}"
    zones = ", ".join(ship.quarantine_zones)
    beds = len(ship.quarantine_zones) * ship.zone_capacity
    works = [c for c in CAPABILITIES if not c["needs_ai"]]
    needs = [c for c in CAPABILITIES if c["needs_ai"]]

    p: list[str] = []
    w = p.append

    w(BANNER)
    w("")
    w("# MedBox — guide de l’opérateur")
    w("")
    w(f"**{ship.name} · {ship.crew_size} membres · aucun médecin à bord · "
      "aucun contact avec la Terre.**")
    w("")
    w("> **MedBox est un prototype de recherche et de formation. Ce n’est pas "
      "un dispositif médical et il ne pose aucun diagnostic.** La priorité "
      "affichée est un dépistage partiel dérivé de NEWS2. L’assistant ne fait "
      "que proposer des hypothèses traçables ; il ne prescrit rien et ne peut "
      "jamais modifier le score.")
    w("")

    w("## 1. Comprendre l’architecture")
    w("")
    w("MedBox fonctionne sur deux voies séparées.")
    w("")
    w("La **voie rapide** lit les capteurs ou la simulation, compare chaque "
      "personne à sa ligne de base, calcule le score et met l’interface à jour. "
      "Aucun modèle de langage n’intervient dans ce circuit.")
    w("")
    w("La **voie lente** est l’assistant local. Il résume, suggère des "
      "hypothèses et formule des questions. Il peut être lent, indisponible ou "
      "arrêté sans interrompre les mesures.")
    w("")
    w("Si Ollama s’arrête, les constantes continuent, l’ordre de priorité reste "
      "calculé, les candidats à la quarantaine restent visibles et les "
      "isolements déjà confirmés demeurent en place. La confirmation et la "
      "levée d’un isolement restent toujours des décisions humaines.")
    w("")

    w("## 2. Démarrer la station")
    w("")
    w("Dans le paquet autonome Windows, double-cliquer sur l’exécutable du "
      "lanceur MedBox. Il démarre les composants locaux, attend que la station "
      "réponde, puis ouvre le navigateur. Fermer le lanceur arrête uniquement "
      "les processus qu’il a démarrés.")
    w("")
    w("Depuis le dépôt de développement :")
    w("")
    w("```")
    w("Windows          .\\.venv\\Scripts\\python medbox.py")
    w("Linux / macOS    .venv/bin/python medbox.py")
    w("```")
    w("")
    w(f"Ouvrir ensuite <{url}>. Le port principal est `{server.port}` ; le "
      "lanceur peut choisir un autre port si celui-ci est déjà occupé.")
    w("")
    w("| Adresse | Vue | Usage |")
    w("|---|---|---|")
    w(f"| `{url}/` | Console 3D du vaisseau | Présentation principale. |")
    w(f"| `{url}/board` | Tableau plat, sans 3D | Secours si WebGL ou le "
      "projecteur pose problème. |")
    w("")

    w("## 3. Lire la priorité NEWS2")
    w("")
    w("L’équipage est classé par score décroissant afin que les écarts les plus "
      "préoccupants restent visibles. Chaque ligne affiche les quatre "
      "constantes mesurées, le total et la bande associée.")
    w("")
    w("| Total dérivé de NEWS2 | Bande | Conduite indiquée par la bande |")
    w("|---|---|---|")
    for span, name, _response in band_rows():
        translated_span = span.replace("or more", "ou plus")
        w(f"| {cell(translated_span)} | **{BAND_LABELS[name]}** | "
          f"{BAND_ACTIONS[name]} |")
    w("")
    escalation = BAND_LABELS[single_param_escalates_to().value]
    w(f"**Règle importante :** un seul paramètre valant 3 points impose au "
      f"minimum la bande **{escalation}**, même si le total paraît plus faible.")
    w("")
    w("NEWS2 complet comporte sept paramètres. MedBox en mesure quatre : "
      "température, SpO₂, pouls et fréquence respiratoire. La pression artérielle "
      "systolique, le niveau de conscience et l’oxygène supplémentaire ne sont "
      "pas mesurés par ce prototype. L’interface affiche donc **dépistage "
      "partiel dérivé de NEWS2** et ne présente jamais ce résultat comme un "
      "NEWS2 complet.")
    w("")
    w("Les voyants indiquent la connexion de l’écran, l’état de l’assistant et "
      "le scénario en cours. Un voyant d’assistant éteint ne coupe pas la voie "
      "rapide. La mention **simulateur, pas un modèle** signifie que des règles "
      "fixes répondent à la place d’Ollama.")
    w("")

    w("## 4. Examiner une personne et simuler un écart")
    w("")
    w("Cliquer sur un membre ouvre son dossier. Le panneau détaille chaque "
      "constante, les points attribués, la ligne de base saine personnelle et "
      "la courbe récente.")
    w("")
    w("Les scénarios et les réglages manuels n’écrasent pas la ligne de base. "
      "Ils appliquent un **écart** traçable pendant une durée choisie. Le moteur "
      "calcule la trajectoire ; aucune valeur numérique n’est demandée au LLM. "
      "L’option d’exposition contagieuse est un fait de simulation saisi par "
      "l’opérateur, pas une conclusion tirée des constantes.")
    w("")
    w("Toute donnée de démonstration est étiquetée comme synthétique. Elle ne "
      "doit jamais être présentée comme une mesure captée sur une personne réelle.")
    w("")

    w("## 5. Activer l’écoute locale")
    w("")
    w("Le navigateur impose une action physique avant d’autoriser le micro. "
      "Cliquer une fois sur **Activer MedBox**, puis accepter l’autorisation du "
      "navigateur. Cette étape ne peut pas être validée à la voix.")
    w("")
    w("MedBox affiche ensuite l’avis de consentement et, si la synthèse vocale "
      "locale est disponible, le lit à haute voix. Répondre clairement "
      "**J’accepte**, **Oui**, **I accept** ou **Yes**. Une réponse négative, "
      "ambiguë ou trop peu fiable ne démarre pas l’écoute.")
    w("")
    w("Après consentement, l’écoute reste active **uniquement tant que la "
      "session et la page restent ouvertes**. Dire **MedBox**, puis la demande. "
      "Le français et l’anglais sont reconnus localement. La parole ambiante "
      "sans phrase d’appel est écartée.")
    w("")
    w("Aucun fichier audio n’est conservé. Avant consentement, même la "
      "transcription est supprimée ; seule la décision et son horodatage sont "
      "audités. Les boutons **Mettre en pause** et **Retirer mon accord** "
      "restent disponibles. Le retrait ferme immédiatement l’accès de MedBox "
      "au microphone pour cette session.")
    w("")

    w("## 6. Déclarations et assistant")
    w("")
    w("Une phrase saisie ou prononcée est enregistrée comme **déclaration**, "
      "jamais comme mesure. Elle ne change donc jamais le score.")
    w("")
    w("Après sélection d’une personne, appuyer sur **Demander à l’assistant**. "
      "La réponse peut contenir :")
    w("")
    w("- un résumé bref des mesures ;")
    w("- au maximum deux hypothèses, jamais un diagnostic ;")
    sources = ", ".join(SOURCE_LABELS.get(s, s) for s in SIGN_SOURCES)
    w(f"- la source de chaque signe : {sources} ;")
    fits = ", ".join(f"« {FIT_LABELS.get(f, f)} »" for f in FIT_LEVELS)
    w(f"- le degré de concordance ({fits}), qui n’est pas une probabilité ;")
    w("- les questions à poser et les observations à recueillir.")
    w("")
    w("Si les quatre mesures n’étayent aucune hypothèse, l’assistant doit le "
      "dire et peut rendre une liste vide. Une réponse devient périmée après "
      "une minute ou dès que le score change ; l’interface demande alors de la "
      "relancer.")
    w("")
    w("Le schéma de sortie ne contient aucun champ de diagnostic, de priorité "
      "ou de traitement. Un garde supplémentaire supprime toute liste qui "
      "contiendrait un médicament, une dose ou une voie d’administration. Le "
      "modèle libre ne prescrit jamais.")
    w("")
    w("La zone **Protocoles locaux vérifiés** suit une autre voie, entièrement "
      "déterministe. Elle cherche une carte signée, affiche ses sources "
      "officielles et n’envoie ni l’observation ni le dossier au LLM. Une option "
      "médicamenteuse issue de l’inventaire simulé reste masquée tant que "
      "l’identité, l’âge, la grossesse, les allergies, les traitements actuels, "
      "les contre-indications et les signes d’alerte ne sont pas tous vérifiés.")
    w("")
    w("La dernière ouverture exige en plus une validation récente d’un clinicien, "
      "liée à la carte exacte, ainsi qu’un lot simulé actif, non périmé et en "
      "quantité suffisante. Le résultat indique la référence et son emplacement "
      "simulés, sans dose, sans diagnostic et sans administration automatique. "
      "Il s’agit d’une démonstration de garde-fous, pas d’une prescription.")
    w("")
    w(f"Le modèle configuré est `{ai.model}`, exécuté localement par Ollama. "
      f"Une requête est abandonnée après {ai.timeout_seconds:g} secondes ; les "
      "mesures ne l’attendent jamais.")
    w("")

    w("## 7. Ajouter un rapport médical")
    w("")
    w("Dans le dossier d’un membre, la zone **Rapports médicaux locaux** accepte "
      "PDF, DOCX, PNG, JPEG et TXT, avec une limite de 12 Mo. MedBox vérifie le "
      "type, attribue un nom de stockage interne, calcule une empreinte SHA-256 "
      "et conserve les métadonnées dans la base locale.")
    w("")
    w("Le document peut être rouvert par l’opérateur, mais son contenu n’est ni "
      "interprété ni transmis à l’assistant. L’ajout d’un fichier ne modifie "
      "jamais le score NEWS2.")
    w("")

    w("## 8. Si l’assistant s’arrête")
    w("")
    w("Arrêter Ollama pendant une consultation constitue un test prévu. Le "
      "voyant IA s’éteint et une nouvelle demande signale que l’assistant est "
      "indisponible. Les mesures, les tendances, la priorisation, les "
      "simulations, les dossiers, les candidats à l’isolement et les décisions "
      "humaines continuent de fonctionner.")
    w("")
    w("Le panneau d’aide reste disponible parce qu’il est rendu à partir de "
      "données détenues par la station, et non inventé par le modèle.")
    w("")

    w("## 9. Quarantaine : confirmation et levée humaines")
    w("")
    w("Les constantes ne prouvent jamais qu’une personne est contagieuse. "
      "Dans un exercice, un drapeau d’exposition déclaré, associé à une fièvre "
      "et à une désaturation ou une respiration élevée, crée seulement un "
      "**candidat à l’isolement**.")
    w("")
    w("L’opérateur examine le dossier et appuie sur **Confirmer l’isolement**. "
      "Ce n’est qu’après cette action que MedBox affecte un lit. Un candidat non "
      "confirmé n’occupe aucune place et ne scelle aucune zone.")
    w("")
    w(f"La configuration comporte {len(ship.quarantine_zones)} zones ({zones}), "
      f"{ship.zone_capacity} lits chacune, soit {beds} places. Une zone est "
      "scellée dès le premier occupant **confirmé**. Lorsqu’elle atteint sa "
      "capacité, les nouvelles confirmations passent à la prochaine zone libre.")
    w("")
    w(f"Lorsque les {beds} places sont occupées, la personne confirmée suivante "
      "reste visible **en attente d’un lit** au lieu de disparaître du registre.")
    w("")
    w("La normalisation ultérieure des constantes ne libère personne "
      "automatiquement. L’opérateur doit vérifier la situation et choisir "
      "**Lever manuellement** ; l’action est enregistrée dans la piste d’audit.")
    w("")

    w("## 10. Capacités disponibles")
    w("")
    w("Cette liste provient de la même source que le panneau **Aide**.")
    w("")
    w("### Fonctionne même sans assistant")
    w("")
    for capability in works:
        w(f"#### {capability['title']}")
        w("")
        w(f"{capability['does']}")
        w("")
        w(f"*{capability['how']}*")
        w("")
    w("### Nécessite l’assistant")
    w("")
    for capability in needs:
        w(f"#### {capability['title']}")
        w("")
        w(f"{capability['does']}")
        w("")
        w(f"*{capability['how']}*")
        w("")
    w(f"{len(works)} des {len(CAPABILITIES)} capacités documentées ne "
      "dépendent pas du modèle. L’IA reste une couche d’explication au-dessus "
      "d’un système déterministe.")
    w("")

    w("## 11. Limites absolues de l’assistant")
    w("")
    w("Ces limites ne reposent pas uniquement sur une consigne : elles sont "
      "renforcées par le schéma de sortie et par des contrôles serveur.")
    w("")
    for refusal in REFUSALS:
        w(f"**{refusal['never']}.** {refusal['why']}")
        w("")

    w("## 12. Commandes de la console 3D")
    w("")
    w("Appuyer sur `/` pour placer le curseur dans la ligne de commande. Les "
      "commandes françaises sont prioritaires ; les anciennes formes anglaises "
      "restent des alias de compatibilité.")
    w("")
    w("| Commande française | Alias compatibles | Action | Assistant requis |")
    w("|---|---|---|---|")
    for shortcut in SHORTCUTS:
        mark = "oui" if shortcut["needs_ai"] else "non"
        aliases = ", ".join(
            f"`{cell(alias)}`" for alias in shortcut.get("aliases", [])
        ) or "—"
        w(f"| `{cell(shortcut['phrase'])}` | {aliases} | "
          f"{cell(shortcut['does'])} | {mark} |")
    w("")
    w("`déclaré` prend le reste de la ligne, par exemple : `déclaré j’ai mal à "
      "la tête depuis ce matin`. Cette phrase est enregistrée comme déclaration, "
      "pas comme mesure.")
    w("")

    w("## 13. Lancer un scénario")
    w("")
    w("Un scénario est une chronologie répétable appliquée à l’équipage "
      "synthétique. Appuyer sur **Lancer** ; **Réinitialiser** ramène les "
      "trajectoires vers les lignes de base.")
    w("")
    for stem, title, description in scenarios():
        w(f"### {title} (`{stem}`)")
        w("")
        w(description or "—")
        w("")
    w("**Pendant la soutenance, annoncer explicitement qu’il s’agit de données "
      "synthétiques.** Les scénarios démontrent la réaction du logiciel ; ils "
      "ne valident pas un capteur médical réel.")
    w("")

    w("## 14. Dépannage")
    w("")
    w("| Symptôme | Cause probable | Action |")
    w("|---|---|---|")
    w("| Tableau vide ou connexion éteinte | Le navigateur ne reçoit plus le "
      "flux | Recharger la page ; si nécessaire, relancer MedBox. |")
    w("| Voyant IA éteint | Ollama démarre encore ou n’est pas disponible | "
      "Attendre le préchauffage. Les mesures restent actives. |")
    w("| Assistant indisponible ou délai dépassé | La requête locale a échoué | "
      "Lire le motif affiché et réessayer ; ne pas interrompre la surveillance. |")
    w("| Le navigateur refuse le micro | Permission absente, page non sécurisée "
      "ou micro occupé | Présenter depuis `localhost`, vérifier le périphérique "
      "et l’autorisation du navigateur, puis réactiver MedBox. |")
    w("| L’avis de consentement n’est pas lu à haute voix | Aucun clip ou voix "
      "locale française disponible | Lire le texte affiché ; l’accord vocal "
      "reste obligatoire avant l’écoute continue. |")
    w("| Vue 3D noire | WebGL indisponible | Utiliser `/board`, qui reçoit les "
      "mêmes données. |")
    w("| Candidat détecté mais aucune zone scellée | La confirmation humaine "
      "n’a pas encore eu lieu | Vérifier le dossier puis choisir explicitement "
      "**Confirmer l’isolement**. |")
    w("| Constantes redevenues normales mais zone toujours scellée | La levée "
      "automatique est volontairement désactivée | Vérifier la situation puis "
      "choisir **Lever manuellement**. |")
    w("")

    w("## 15. Données et composants locaux")
    w("")
    w("| Composant | Configuration |")
    w("|---|---|")
    w(f"| Modèle | `{ai.model}`, exécuté localement par Ollama |")
    if ai.fallback_models:
        w(f"| Modèles de repli configurés | `{'`, `'.join(ai.fallback_models)}` |")
    w(f"| Version Ollama ciblée | {ai.required_ollama} |")
    w("| Reconnaissance vocale | Locale, français/anglais ; aucun audio conservé. |")
    w("| Alertes vocales | Clips locaux préenregistrés ; aucun service en ligne. |")
    w(f"| Base | Fichier SQLite local (`{CONFIG.database.path}`), choisi pour "
      "un paquet autonome sans serveur à administrer. |")
    w("| Rapports médicaux | Stockage local contrôlé ; jamais envoyés au LLM. |")
    w("| Réseau extérieur | Aucun appel nécessaire au fonctionnement de la "
      "station ou du modèle. |")
    w("")
    w("L’API de reconnaissance vocale du navigateur n’est pas utilisée, car "
      "elle peut transmettre l’audio à un service distant. La transcription "
      "MedBox passe uniquement par le moteur local configuré.")
    w("")
    w("---")
    w("")
    w("*Regénérer ce document avec `python tools/guide.py`. Il est construit à "
      "partir du produit afin de rester aligné sur la version démontrée.*")

    return "\n".join(p).rstrip() + "\n"


# --------------------------------------------------------------------- the cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Générer docs/USER_GUIDE.md.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="ne rien écrire ; échouer si le guide versionné n’est plus à jour",
    )
    args = parser.parse_args(argv)

    fresh = build()

    if args.check:
        if not OUT.exists():
            print(f"{OUT.relative_to(ROOT)} absent. Exécuter : python tools/guide.py")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current == fresh:
            print(f"{OUT.relative_to(ROOT)} est à jour.")
            return 0
        print(f"{OUT.relative_to(ROOT)} n’est plus à jour. Exécuter : python tools/guide.py\n")
        sys.stdout.writelines(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                fresh.splitlines(keepends=True),
                fromfile="committed",
                tofile="generated",
            )
        )
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    changed = not OUT.exists() or OUT.read_text(encoding="utf-8") != fresh
    OUT.write_text(fresh, encoding="utf-8")
    print(
        f"{'Écrit' if changed else 'Inchangé'} {OUT.relative_to(ROOT)} "
        f"({len(fresh.splitlines())} lignes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
