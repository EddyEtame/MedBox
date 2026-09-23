"""What the assistant can do, what it refuses to do, and how to ask.

The owner wanted the AI to explain its own help rather than shipping a static
guide. That is the right instinct, and it has one trap in it: during the demo
the model is killed live on stage. If the explanation lived inside the model,
the thing explaining the system would vanish at the exact moment the system
is proving it does not need the model.

So the manifest below is data the station owns. When the assistant is up it
narrates this in its own words. When it is dead the station renders the same
facts plainly, and the guide is still there. The model is the voice, never
the source.

Every entry says whether it needs the AI at all. Most do not, which is the
honest shape of this product: the AI is a narrator over a system that works
without it.
"""
from __future__ import annotations

# --------------------------------------------------------------- what it does
CAPABILITIES = [
    {
        "id": "triage",
        "title": "Prioriser tout l’équipage selon les mesures",
        "does": (
            "Chaque membre reçoit un dépistage partiel dérivé de NEWS2, calculé "
            "à partir des cinq constantes mesurées par MedBox et des deux observations saisies. Le tableau et "
            "le vaisseau sont ordonnés selon ce score déterministe."
        ),
        "needs_ai": False,
        "how": "Toujours actif : aucune demande à formuler.",
    },
    {
        "id": "explain_score",
        "title": "Expliquer le calcul du score d’une personne",
        "does": (
            "Après sélection d’un membre, chaque constante indique pourquoi elle "
            "a reçu ses points. MedBox distingue aussi les paramètres réellement "
            "mesurés de ceux qui sont absents ou supposés."
        ),
        "needs_ai": False,
        "how": "Cliquer sur un membre dans l’une ou l’autre vue.",
    },
    {
        "id": "quarantine",
        "title": "Proposer une quarantaine à confirmer humainement",
        "does": (
            "Une exposition déclarée par le scénario, associée à une fièvre et à "
            "une désaturation ou une respiration élevée, crée un candidat. Un "
            "humain doit confirmer l’affectation : rien n’est isolé automatiquement. "
            "Après confirmation, la zone est scellée dès son premier occupant et "
            "cesse d’accepter des arrivées quand sa capacité est atteinte. Toute "
            "personne sans place reste affichée en attente d’un lit. La levée est "
            "elle aussi manuelle."
        ),
        "needs_ai": False,
        "how": (
            "Ouvrir le dossier du candidat, vérifier le contexte, puis confirmer "
            "ou refuser. La libération exige une action humaine explicite."
        ),
    },
    {
        "id": "report",
        "title": "Enregistrer ce qu’un membre déclare",
        "does": (
            "Le texte saisi ou prononcé est conservé comme une déclaration à "
            "vérifier. Il peut être transmis à l’assistant, mais ne modifie jamais "
            "le score NEWS2 puisqu’aucun capteur ne l’a mesuré."
        ),
        "needs_ai": False,
        "how": "Sélectionner un membre, puis utiliser la zone « Déclarations ».",
    },
    {
        "id": "baselines",
        "title": "Comparer chaque personne à sa ligne de base saine",
        "does": (
            "Les constantes de référence sont personnelles, déjà enregistrées "
            "dans la base locale et accompagnées de leur provenance. Une "
            "simulation manuelle applique des écarts visibles à cette base ; "
            "elle ne demande jamais au modèle d’inventer une mesure."
        ),
        "needs_ai": False,
        "how": "Sélectionner un membre, puis choisir un scénario ou saisir un écart manuel.",
    },
    {
        "id": "documents",
        "title": "Joindre un compte rendu médical au dossier local",
        "does": (
            "MedBox accepte uniquement les formats autorisés, limite la taille, "
            "calcule une empreinte et conserve le fichier localement. Le document "
            "n’est jamais envoyé au modèle et son contenu n’est pas interprété."
        ),
        "needs_ai": False,
        "how": "Sélectionner un membre, puis utiliser la zone « Documents médicaux ».",
    },
    {
        "id": "protocols",
        "title": "Consulter une carte de protocole locale validée",
        "does": (
            "Un moteur déterministe séparé du LLM recherche une carte signée et "
            "affiche ses sources officielles. Toute option issue de l’inventaire "
            "simulé reste masquée tant que l’identité, l’âge, la grossesse, les "
            "allergies, les traitements actuels, les contre-indications et les "
            "signes d’alerte ne sont pas vérifiés, puis validés récemment par un "
            "clinicien pour cette carte précise. Aucune dose ni administration "
            "automatique n’est fournie."
        ),
        "needs_ai": False,
        "how": (
            "Sélectionner un membre, choisir « Chercher une carte », puis suivre "
            "chaque contrôle humain affiché."
        ),
    },
    {
        "id": "voice",
        "title": "Rester à l’écoute après un consentement explicite",
        "does": (
            "Après l’autorisation du navigateur et une réponse vocale explicite, "
            "MedBox écoute localement tant que la session reste ouverte. Seule la "
            "phrase d’appel « MedBox » ouvre une demande ; la parole ambiante est "
            "écartée et aucun fichier audio n’est conservé. L’écoute peut être mise "
            "en pause ou révoquée à tout moment."
        ),
        "needs_ai": False,
        "how": "Appuyer une fois sur « Activer MedBox », écouter l’avis, puis dire « J’accepte ».",
    },
    {
        "id": "hypotheses",
        "title": "Proposer des hypothèses classées pour une personne",
        "does": (
            "L’assistant lit les mesures et les déclarations de cette personne, "
            "puis propose des explications possibles. Chaque signe nomme son "
            "capteur ou reste clairement marqué comme déclaré et non mesuré. Il "
            "ne diagnostique pas, ne change jamais la priorité et doit reconnaître "
            "l’insuffisance des données au lieu d’inventer un profil."
        ),
        "needs_ai": True,
        "how": "Sélectionner un membre, puis appuyer sur « Demander à l’assistant ».",
    },
    {
        "id": "questions",
        "title": "Suggérer les prochaines questions à poser",
        "does": (
            "MedBox mesure cinq paramètres et en fait observer deux. L’assistant peut donc aider "
            "à formuler des questions brèves pour recueillir les informations qui "
            "manquent, sans les transformer en mesures."
        ),
        "needs_ai": True,
        "how": "Inclus dans chaque évaluation de l’assistant.",
    },
]

# ------------------------------------------------------ what it will not do
REFUSALS = [
    {
        "id": "diagnosis",
        "never": "Poser un diagnostic",
        "why": (
            "L’assistant propose seulement des hypothèses accompagnées de leurs "
            "signes. Le schéma de réponse ne contient aucun champ de diagnostic : "
            "il ne peut donc pas en produire, même si on le lui demande."
        ),
    },
    {
        "id": "prescription",
        "never": "Prescrire un médicament ou un traitement",
        "why": (
            "Aucun champ ne permet d’émettre un traitement. La seule liste qu’il "
            "peut remplir concerne les observations et mesures à recueillir. Si "
            "un médicament, une dose ou une voie d’administration y apparaît, "
            "MedBox supprime toute la liste et le signale. MedBox n’est pas médecin."
        ),
    },
    {
        "id": "urgency",
        "never": "Modifier la priorité d’une personne",
        "why": (
            "La priorité provient de NEWS2, calculé en Python à partir des mesures. "
            "Le modèle n’appartient pas à ce circuit et ne peut pas réécrire le score."
        ),
    },
    {
        "id": "unmeasured",
        "never": "Traiter une déclaration comme une mesure",
        "why": (
            "Les symptômes déclarés lui parviennent comme des informations non "
            "vérifiées. Chaque signe avancé doit nommer sa source."
        ),
    },
    {
        "id": "availability",
        "never": "Bloquer les mesures",
        "why": (
            "L’assistant fonctionne sur une voie lente séparée. S’il se bloque ou "
            "s’arrête, les constantes, la priorisation, les propositions de "
            "quarantaine et l’enregistrement continuent."
        ),
    },
    {
        "id": "network",
        "never": "Accéder au réseau",
        "why": "Le modèle fonctionne localement ; le vaisseau n’a aucun contact avec la Terre.",
    },
]

# ------------------------------------------------------------------ shortcuts
# Short phrases that do a real thing. Most work with the model dead, which is
# deliberate: an operator should not have to learn which of their tools stop
# working when the assistant does.
SHORTCUTS = [
    {
        "phrase": "prioritaire",
        "aliases": ["pire", "worst"],
        "does": "Sélectionner le membre ayant le score NEWS2 le plus élevé.",
        "needs_ai": False,
    },
    {
        "phrase": "suivant",
        "aliases": ["next"],
        "does": "Passer au membre suivant dans l’ordre de priorité.",
        "needs_ai": False,
    },
    {
        "phrase": "pourquoi",
        "aliases": ["why"],
        "does": "Afficher le calcul du score sélectionné, paramètre par paramètre.",
        "needs_ai": False,
    },
    {
        "phrase": "isolés",
        "aliases": ["isolated"],
        "does": (
            "Afficher les candidats en attente de confirmation, les personnes "
            "confirmées en quarantaine et les zones scellées."
        ),
        "needs_ai": False,
    },
    {
        "phrase": "déclaré <mots>",
        "aliases": ["said <words>"],
        "does": "Enregistrer les mots que ce membre vient de prononcer.",
        "needs_ai": False,
    },
    {
        "phrase": "évaluer",
        "aliases": ["assess"],
        "does": "Demander des hypothèses à l’assistant pour le membre sélectionné.",
        "needs_ai": True,
    },
    {
        "phrase": "demander",
        "aliases": ["ask"],
        "does": "Lister les questions à poser ensuite à cette personne.",
        "needs_ai": True,
    },
    {
        "phrase": "aide",
        "aliases": ["help"],
        "does": "Expliquer ce que MedBox peut et ne peut pas faire, même sans IA.",
        "needs_ai": False,
    },
]


def manifest(ai_available: bool = False, stand_in: bool = False) -> dict:
    """Everything the interface needs to explain itself, model or no model."""
    return {
        "capabilities": CAPABILITIES,
        "refusals": REFUSALS,
        "shortcuts": SHORTCUTS,
        "ai_available": ai_available,
        "stand_in": stand_in,
        "without_ai": [c["id"] for c in CAPABILITIES if not c["needs_ai"]],
        "needs_ai": [c["id"] for c in CAPABILITIES if c["needs_ai"]],
    }


INTRODUCTION_CORE = (
    "Je surveille les cinq constantes mesurées, les compare aux lignes de base "
    "personnelles et signale les écarts dans le tableau, le vaisseau 3D et les "
    "dossiers locaux. Je peux proposer des hypothèses et des questions, mais jamais "
    "diagnostiquer, prescrire, modifier une priorité ou isoler quelqu’un : ces "
    "décisions restent humaines. Les comptes rendus et les cartes de protocole "
    "restent locaux et ne sont pas interprétés par le modèle."
)

INTRODUCTION_CONSENT = (
    "Après l’autorisation du navigateur, le microphone peut rester actif localement "
    "pendant cette session pour détecter « MedBox » ; l’audio n’est pas conservé et "
    "vous pouvez suspendre l’écoute ou retirer votre accord à tout moment. "
    "Acceptez-vous cette écoute locale continue ? Dites clairement « J’accepte », "
    "« oui », « I accept » ou « yes »."
)


def deterministic_introduction(greeting: str = "Bonjour, je suis MedBox.") -> str:
    """Return the complete, reviewable startup orientation.

    Ollama is allowed to provide only ``greeting``. The operational claims, medical
    limits and consent question are station-owned text, so a slow or unavailable
    model cannot omit or improvise them.
    """
    return f"{greeting.strip()} {INTRODUCTION_CORE} {INTRODUCTION_CONSENT}"


def self_explanation_prompt() -> str:
    """Ask only for a short French greeting, never for medical content.

    The complete introduction is composed by :func:`deterministic_introduction`.
    Keeping the model's job this small is both a latency boundary and a safety
    boundary: it cannot invent capabilities or weaken the consent notice.
    """
    return (
        "Écrivez une seule salutation calme en français, de 4 à 10 mots. "
        "Elle doit contenir le nom « MedBox ». Aucun conseil médical, aucune "
        "capacité, aucune liste et aucune question."
    )
