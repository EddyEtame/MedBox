"""Build the workshop dossier (PDF) for the local and national defences.

Structure follows the dossier format the school circulated (ARIA example,
13 sections, boxed statements, tables, a figure). Content is MedBox's real
state on the day the script runs; the numbers are read from the code where
they can be. Document tooling only: reportlab is not a runtime dependency.

    .venv\\Scripts\\python tools\\build_dossier.py [--group N]

The PDF goes to .build\\deliverables (ignored by Git); the script does not.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".build" / "deliverables"
SHOTS = OUT / "shots"

TEAM = [("Eddy", "Commandant de bord, direction du projet"),
        ("Brad", "Ingénieur de vol, dossier patient"),
        ("Davidson", "Systèmes"),
        ("Anthony", "Navigation"),
        ("Frederic", "Communications"),
        ("Merove", "Secouriste")]

NAVY = colors.HexColor("#12364a")
TEAL = colors.HexColor("#0e6b6b")
LINE = colors.HexColor("#b6c8d0")
HEAD_BG = colors.HexColor("#e0edf2")
BOX_BG = colors.HexColor("#eef6f8")
MUTED = colors.HexColor("#546875")


def count_tests() -> int:
    n = 0
    for f in (ROOT / "tests").glob("test_*.py"):
        n += len(re.findall(r"^def test_", f.read_text(encoding="utf-8", errors="replace"), re.M))
    return n


def count_scenarios() -> int:
    return len(list((ROOT / "scenarios").glob("*.yaml")))


def styles():
    ss = getSampleStyleSheet()
    body = ss["BodyText"]
    body.fontName = "Helvetica"
    body.fontSize = 9.6
    body.leading = 14
    ss.add(ParagraphStyle("Cover", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=34, leading=40, textColor=NAVY, alignment=TA_CENTER))
    ss.add(ParagraphStyle("CoverSub", parent=body, fontSize=13, leading=18, alignment=TA_CENTER, textColor=TEAL))
    ss.add(ParagraphStyle("CoverLine", parent=body, fontSize=10.5, leading=15, alignment=TA_CENTER))
    ss.add(ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=TEAL, spaceBefore=8, spaceAfter=4))
    ss.add(ParagraphStyle("BoxTitle", parent=body, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=TEAL))
    ss.add(ParagraphStyle("BoxBody", parent=body, fontSize=9.6, leading=14))
    ss.add(ParagraphStyle("Caption", parent=body, fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER))
    ss.add(ParagraphStyle("Bul", parent=body, leftIndent=12, bulletIndent=2))
    return ss


def build(group: str | None) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    date_fr = today.strftime("%d %B %Y")
    months = {"January": "janvier", "February": "février", "March": "mars", "April": "avril", "May": "mai", "June": "juin",
              "July": "juillet", "August": "août", "September": "septembre", "October": "octobre", "November": "novembre", "December": "décembre"}
    for en, fr in months.items():
        date_fr = date_fr.replace(en, fr)
    tests = count_tests()
    scenarios = count_scenarios()
    ss = styles()
    story: list = []

    def p(text, style="BodyText"):
        story.append(Paragraph(text, ss[style]))
        story.append(Spacer(1, 6))

    def h1(text):
        story.append(Paragraph(text, ss["H1"]))

    def h2(text):
        story.append(Paragraph(text, ss["H2"]))

    def bullets(items):
        for it in items:
            story.append(Paragraph(it, ss["Bul"], bulletText="•"))
        story.append(Spacer(1, 6))

    def box(title, text):
        t = Table([[Paragraph(title, ss["BoxTitle"])], [Paragraph(text, ss["BoxBody"])]], colWidths=[17 * cm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BOX_BG), ("BOX", (0, 0), (-1, -1), 0.6, TEAL),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(KeepTogether(t))
        story.append(Spacer(1, 8))

    def table(rows, widths, head=True):
        cells = [[Paragraph(str(x).replace("≤", "&lt;=").replace("≥", "&gt;="), ss["BodyText"]) for x in row] for row in rows]
        t = Table(cells, colWidths=widths, repeatRows=1 if head else 0)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                 ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
        if head:
            style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
        t.setStyle(TableStyle(style))
        story.append(t)
        story.append(Spacer(1, 8))

    def figure(name, caption, width=16 * cm):
        f = SHOTS / name
        if not f.exists():
            return
        try:
            from PIL import Image as PILImage
            w, h = PILImage.open(f).size
        except Exception:
            w, h = 1366, 768
        story.append(Image(str(f), width=width, height=width * h / w))
        story.append(Paragraph(caption, ss["Caption"]))
        story.append(Spacer(1, 8))

    # ------------------------------------------------------------ cover
    story.append(Spacer(1, 3.2 * cm))
    story.append(Paragraph("MedBox", ss["Cover"]))
    story.append(Paragraph("Mallette médicale intelligente de bord", ss["CoverSub"]))
    story.append(Paragraph("Local medical station and medical referent for a crew without a doctor", ss["CoverLine"]))
    story.append(Spacer(1, 1.2 * cm))
    box("MISSION", "Surveiller la santé de quarante membres d’équipage, décider et expliquer les isolements, parler à chacun "
        "dans sa langue et rester entièrement autonome quand la Terre ne répond plus. Un dossier de 1,6 Go qui se lance en "
        "quelques secondes sur n’importe quel PC, sans réseau.")
    story.append(Spacer(1, 0.6 * cm))
    group_label = f"Groupe {group}" if group else "Groupe : numéro non attribué"
    for line in ("Workshop National B3 — Horizon 2080", "Pilier HumanTech &amp; HealthTech Spatiales — MedBox",
                 f"Dossier technique — prototype de démonstration — {group_label}", f"{date_fr}"):
        story.append(Paragraph(line, ss["CoverLine"]))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("<b>Équipe :</b> " + ", ".join(f"{n} ({r.split(',')[0].lower()})" for n, r in TEAM), ss["CoverLine"]))
    story.append(PageBreak())

    # ------------------------------------------------------------ sommaire
    h1("Sommaire")
    toc = ["1. Présentation du projet", "2. Contexte et problématique", "3. Objectifs",
           "4. Inspiration du pilier HumanTech &amp; HealthTech", "5. Solution proposée", "6. Architecture technique",
           "7. Fonctionnement détaillé", "8. Scénarios de crise", "9. Choix technologiques et justification",
           "10. Résultats obtenus", "11. Limites et perspectives", "12. Organisation de l’équipe", "13. Conclusion",
           "14. Références documentaires"]
    for t in toc:
        story.append(Paragraph(t, ss["BodyText"]))
    story.append(Spacer(1, 8))
    box("POSITIONNEMENT", "MedBox n’est pas un chatbot médical. C’est une station de bord : elle mesure en continu, calcule "
        "une priorité par des règles explicites, décide et annonce les isolements, parle et écoute, tient le dossier de "
        "chacun et le tableau de bord de l’équipage, et tout cela sans aucun service distant.")

    h1("1. Présentation du projet")
    p("MedBox — mallette médicale intelligente de bord — est la station médicale d’un vaisseau de quarante personnes qui "
      "n’a pas de médecin. Elle s’inscrit dans le pilier HumanTech &amp; HealthTech Spatiales du Workshop Horizon 2080 et "
      "répond à sa proposition MedBox : mesurer, apprendre la ligne de base de chacun, suivre l’historique, comparer les "
      "écarts, analyser avec une IA locale, puis agir.")
    p("Dans la simulation, le référent médical du bord est l’autorité médicale : il nomme ce que les mesures montrent, "
      "décide l’isolement, le dit à la personne concernée, prévient l’équipage et lit ses messages à voix haute. Il ne "
      "prescrit aucun médicament et n’invente jamais une maladie que les mesures ne montrent pas : chaque phrase passe par "
      "un schéma et un validateur avant d’être lue.")
    bullets(["Surveillance de quarante membres, dix mesures par seconde, score NEWS2 déterministe.",
             "Référent médical local (Ollama, modèle léger, réponses contraintes) qui parle et écoute, en français et en anglais.",
             "L’équipage, c’est l’équipe : six membres réels avec une semaine de mesures en base, un espace personnel chacun sur son propre port.",
             "Tableau de bord équipage, messages sonores, cartes avec le vaisseau 3D et la zone d’isolement qui s’illumine.",
             f"Livraison autonome : un dossier portable de 1,6 Go, {tests} tests, {scenarios} scénarios reproductibles."])

    h1("2. Contexte et problématique")
    p("Dans Horizon 2080, les vaisseaux de l’ESA voyagent des décennies. La liaison avec la Terre devient inutilisable ou "
      "trop lente pour une assistance humaine immédiate. Une contamination qui touche 15 % de l’équipage doit être vue, "
      "priorisée et contenue à bord, par des personnes qui ne sont pas médecins, avec les ressources du vaisseau.")
    p("La problématique retenue : comment donner à un équipage sans médecin une station capable de surveiller chacun en "
      "continu, de décider vite et clairement qui isoler, d’expliquer sa décision à la personne et au groupe, et de rester "
      "entièrement opérationnelle sans réseau ?")
    box("CONTRAINTE MAJEURE", "Tout doit fonctionner localement : les mesures, le score, la décision, la voix, le modèle et "
        "les données. Aucune fonction essentielle ne dépend d’un service distant. Le prototype est livré comme un dossier "
        "autonome vérifié fichier par fichier.")

    h1("3. Objectifs")
    bullets(["<b>Surveiller</b> quarante membres en continu à partir de constantes (simulées aujourd’hui, capteurs demain) et d’une ligne de base personnelle.",
             "<b>Prioriser</b> avec un score explicite (NEWS2) que n’importe qui peut relire, sans modèle dans la boucle.",
             "<b>Décider et expliquer</b> : le référent nomme ce que montrent les mesures, décide l’isolement, prévient la personne et l’équipage, à l’écran et à voix haute.",
             "<b>Parler à chacun</b> : un espace personnel par membre, où le référent sait à qui il parle, et un mot de réveil vocal.",
             "<b>Rester autonome</b> : modèle, voix, données et pages embarqués ; lancement en quelques secondes sans réseau."])

    h1("4. Inspiration du pilier HumanTech &amp; HealthTech")
    p("Le cahier des charges propose PsychoSpace pour le suivi psychologique et MedBox pour l’assistance médicale, avec "
      "une logique commune : mesurer, apprendre une baseline personnelle, observer l’historique, comparer les écarts, "
      "analyser le contexte avec une IA locale puis agir. MedBox applique cette chaîne à la santé physique de l’équipage.")
    table([["Référence du workshop", "Transposition dans MedBox"],
           ["MedBox (pilier 1A)", "Mesures continues, score NEWS2, isolement décidé et annoncé, dossier patient persistant, référent médical qui parle."],
           ["Ligne de base personnelle", "Chaque membre a sa propre plage habituelle ; les scénarios sont écrits en écarts par rapport à elle, pas en valeurs absolues."],
           ["IA locale / offline", "Ollama et le modèle sont dans le dossier livré ; reconnaissance et synthèse vocales aussi. Zéro dépendance réseau."],
           ["Gestion de crise", "Scénario « contamination » : six membres sur quarante se dégradent ; décisions, messages sonores, zones d’isolement, contacts."],
           ["Capteurs / terminal", "Contrat de tête de mesure série prêt (server/sensors/serial_head.py) ; le prototype tourne sur des données synthétiques et le dit."]],
          [5 * cm, 12 * cm])
    p("Un principe de conception vient du pilier : une seule donnée inhabituelle ne suffit pas à conclure. Le score agrège "
      "plusieurs constantes, l’isolement demande une combinaison (fièvre avec désaturation ou respiration élevée), et "
      "la levée d’isolement reste une décision humaine.")

    h1("5. Solution proposée")
    table([["Brique", "Fonction"],
           ["Surveillance (chemin rapide)", "Mesures à 10 Hz, score NEWS2, proposition d’isolement, zones avec places, registre des contacts. N’importe jamais le module IA."],
           ["Référent médical (chemin lent)", "Évaluation nommée, décision, messages, réponses aux questions ; réponses contraintes par schéma JSON et validateur."],
           ["Voix, dans les deux sens", "Consentement parlé, choix de langue, mot de réveil (« MedBox » ou le nom donné à l’assistant), reconnaissance et synthèse hors ligne."],
           ["Équipage et espaces personnels", "Tableau de bord de la semaine, membre en forme et ses habitudes, activités du jour ; un espace par membre sur son port."],
           ["Messages et cartes", "Chaque décision d’isolement arrive avec un signal sonore ; « Lire » ouvre la carte de la personne, le vaisseau 3D et la zone qui s’illumine, et lit le message."],
           ["Vaisseau 3D et tableau 2D", "La même situation vue de deux façons, alimentées par le même flux ; la panne du modèle n’arrête jamais l’affichage."],
           ["Dossier portable", "Python, Ollama, modèle, voix, pages et outils dans un dossier de 1,6 Go ; lanceur, contrôle avant soutenance, arrêt et relance du modèle."]],
          [4.6 * cm, 12.4 * cm])
    figure("crew.png", "Figure 1 — Le tableau de bord de l’équipage : messages du référent, membre en forme cette semaine, activités du jour, état de chacun.")

    h1("6. Architecture technique")
    p("Quatre pages, sept serveurs, un seul processus Python : la station principale sert le vaisseau, le tableau et "
      "l’équipage ; six serveurs légers, un par membre, servent les espaces personnels sur leur propre port et délèguent "
      "tout à la même application.")
    h2("6.1 Interface — quatre pages")
    p("Vue 3D du vaisseau (`/ship`), tableau 2D (`/board`), tableau de bord équipage (`/crew`), espace personnel "
      "(`/me/{id}`, ports 8771 à 8776). HTML, CSS et JavaScript sans framework, servis par la station, revalidés à chaque "
      "chargement. Un menu de navigation commun, le micro et la voix sur chaque page.")
    h2("6.2 Backend — FastAPI, deux chemins")
    p("Le chemin de surveillance (source simulée → score déterministe et quarantaine → SQLite → WebSocket) ne dépend "
      "pas du modèle. Le chemin de conversation (question ou mesure → faits écrits par la station → Ollama sous schéma → "
      "validateur → écran et voix) ne touche jamais au score.")
    table([["Chemin de surveillance", "Chemin de conversation"],
           ["1. Source simulée (ou tête de mesure)<br/>2. NEWS2, proposition d’isolement, contacts<br/>3. SQLite et diffusion WebSocket à 10 Hz",
            "1. Faits déterministes écrits par la station<br/>2. Ollama, réponse contrainte par schéma JSON<br/>3. Validateur (ni médicament, ni dose, ni maladie inventée), écran, voix"]],
          [8.5 * cm, 8.5 * cm])
    h2("6.3 Données — SQLite")
    p("Mesures, événements, réponses du patient, historique des priorités, contacts, sessions, messages, préférences "
      "(nom de l’assistant) et une semaine de mesures par membre de l’équipe. Tout survit à un redémarrage ; les "
      "affectations d’isolement sont re-proposées au premier cycle, la confirmation reste humaine.")
    h2("6.4 IA locale — Ollama sous contrainte")
    p("Modèle `qwen2.5:1.5b-instruct` (processeur seul), appelé avec un schéma JSON qui impose la forme de la réponse. "
      "Un validateur relit chaque phrase : aucun médicament, aucune dose ; une condition ne peut être nommée que si "
      "les mesures la montrent. Les questions sur l’isolement et sur l’équipage sont répondues par la station elle-même, "
      "en quelques millisecondes, à partir de ses registres : le modèle ne peut pas inventer un isolé.")
    box("PRINCIPE DE SÉCURITÉ", "Le score, la proposition d’isolement et les faits viennent de règles explicites que "
        "n’importe qui peut relire. Le modèle contextualise et formule ; il ne décide pas du score et ne prescrit pas. "
        "La levée d’isolement est une décision humaine. Le consentement micro est parlé, révocable, et rien de l’audio "
        "n’est conservé.")
    h2("6.5 Voix — hors ligne, dans les deux sens")
    p("Reconnaissance faster-whisper (modèle base, français et anglais) ; synthèse Piper (voix fr_FR-siwis et "
      "en_US-lessac), 64 phrases pré-rendues et rendu à la demande. Le référent se présente, demande le consentement, "
      "propose la langue, s’éveille sur son nom, lit les évaluations, les réponses et les messages.")
    h2("6.6 Barème implémenté")
    table([["Paramètre", "Points attribués (server/triage.py)"],
           ["Température", "≤35 : 3 ; ≤36 : 1 ; ≤38 : 0 ; ≤39 : 1 ; au-delà : 2."],
           ["SpO2", "≤91 : 3 ; ≤93 : 2 ; ≤95 : 1 ; au-delà : 0."],
           ["Pouls", "≤40 : 3 ; ≤50 : 1 ; ≤90 : 0 ; ≤110 : 1 ; ≤130 : 2 ; au-delà : 3."],
           ["Respiration", "≤8 : 3 ; ≤11 : 1 ; ≤20 : 0 ; ≤24 : 2 ; au-delà : 3."],
           ["Priorité", "Total ≥7 : haute ; ≥5 : moyenne ; un paramètre à 3 : moyenne ; total ≥1 : faible ; sinon routine."]],
          [4 * cm, 13 * cm])
    p("Le barème décrit le code existant ; il ne constitue pas une validation indépendante de NEWS2 (Royal College of "
      "Physicians, 2017). La tension est simulée ; conscience et oxygène d’appoint sont saisis ou supposés.")
    h2("6.7 Quarantaine et contacts")
    p("Admission proposée sur fièvre associée à une désaturation, une respiration élevée ou une priorité au moins "
      "moyenne ; trois zones avec places ; registre des paires de personnes ayant partagé une zone, avec début et fin. "
      "Le registre ne prouve pas une contamination et ne couvre pas les contacts hors zones.")
    h2("6.8 Capteurs")
    p("Le contrat de la tête de mesure série est fixé et testé avec une source simulée ; le matériel n’était pas "
      "disponible pendant le workshop et aucun étalonnage n’est revendiqué.")
    figure("ship.png", "Figure 2 — La vue 3D du vaisseau : anneau d’habitation, quarante membres, zones d’isolement, commande locale et écoute.")

    h1("7. Fonctionnement détaillé")
    bullets(["1. Le dossier se lance (`MedBox.exe`) : station, six espaces personnels et modèle démarrent ; la page s’ouvre en quatre secondes.",
             "2. Le référent se présente à voix haute et demande le consentement micro ; la personne répond « j’accepte » ; il propose la langue.",
             "3. Les constantes arrivent à 10 Hz ; le score NEWS2 et la priorité sont recalculés à chaque mesure et diffusés à toutes les pages.",
             "4. Quand une combinaison d’écarts apparaît, la station propose l’isolement et une zone ; le référent nomme ce que montrent les mesures.",
             "5. Un message part vers la personne et vers le tableau de bord de l’équipage, avec un signal sonore ; « Lire » ouvre la carte, le vaisseau et la zone qui s’illumine, et lit le message.",
             "6. Une personne confirme l’isolement, ou le lève ; contacts, réponses, historique de priorité sont conservés.",
             "7. Chaque membre, sur son espace, entend son évaluation à la deuxième personne, pose ses questions au clavier ou à la voix, voit sa semaine et ses activités.",
             "8. Si le modèle tombe, tout continue : la surveillance, les décisions, les pages ; l’écran le dit, et le référent revient quand le modèle revient."])
    h2("7.1 Exemple de réponse opérationnelle")
    table([["Message d’isolement (crew, lu à voix haute)", "Réponse courte à une question (espace personnel)"],
           ["Isolement décidé pour Merove (Secouriste) : de la fièvre et une respiration rapide, exposition confirmée. Zone à attribuer. Accusez réception.",
            "« Est-ce que je dois m’inquiéter pour mon pouls ? » — Non, Eddy, votre pouls est dans votre plage habituelle. Reposez-vous et redemandez-moi dans une heure."]],
          [8.5 * cm, 8.5 * cm])
    figure("me.png", "Figure 3 — Un espace personnel : le référent salue par le nom, lit l’évaluation à la deuxième personne, répond aux questions ; la semaine, les activités, le dossier.")

    h1("8. Scénarios de crise")
    p("Les cinq situations du cahier des charges, et ce que MedBox fait dans chacune. Toutes se rejouent depuis le "
      "menu des scénarios ; les valeurs sont des écarts par rapport à la ligne de base personnelle de chacun.")
    table([["Scénario", "Ce que MedBox fait", "Priorité", "Logique"],
           ["Liaison Terre coupée 24 h", "Rien ne change : modèle, voix, données et pages sont à bord. Le dossier n’a jamais eu de réseau.", "Critique pour l’autonomie", "Aucune fonction ne dépend du cloud."],
           ["Énergie à 50 %", "Le chemin rapide (mesures, score, décisions) est léger ; le modèle peut être arrêté sans perdre la surveillance.", "Élevée", "Les fonctions vitales restent prioritaires."],
           ["Eau contaminée", "Scénario « exposition-environnementale » : plusieurs membres se dégradent, contacts tracés, zones attribuées.", "Critique", "La station n’invente pas de procédure ; elle mesure et isole."],
           ["15 % de l’équipage malade", "Scénario « contamination » : six membres sur quarante ; décisions, messages sonores, cartes, trois zones, contacts.", "Critique", "Le référent décide ; l’équipage confirme et lève."],
           ["Dérive progressive", "Scénario « slow-burn » : dégradation lente sur dix minutes ; le score monte cran par cran, l’historique montre la pente.", "À surveiller, puis préoccupant", "Une mesure isolée ne suffit pas."]],
          [3.3 * cm, 7.4 * cm, 2.8 * cm, 3.5 * cm])
    h2("8.1 Scénario central de démonstration")
    p("Au départ, l’équipage est dans sa plage habituelle ; le tableau de bord montre la semaine, le membre en forme et "
      "les activités du jour. Le scénario « contamination » démarre : six membres se dégradent ; à chaque décision, un "
      "message sonne sur le tableau de bord ; « Lire » ouvre la carte de la personne, le vaisseau 3D avec la zone qui "
      "s’illumine, et le référent lit sa décision. Sur son espace personnel, la personne entend son évaluation à la "
      "deuxième personne et peut poser une question à la voix. Enfin, le modèle est arrêté : la surveillance continue, "
      "l’écran le dit ; il est relancé, le référent revient.")
    figure("embed.png", "Figure 4 — La carte ouverte depuis un message : le vaisseau embarqué centré sur la personne, la zone d’isolement qui s’illumine.", width=12 * cm)

    h1("9. Choix technologiques et justification")
    table([["Technologie", "Rôle", "Justification"],
           ["Python + FastAPI + WebSocket", "Un seul processus : API, diffusion à 10 Hz, simulation, six serveurs personnels", "Lisible, testable, sans infrastructure ; tout tient dans un dossier."],
           ["Ollama + qwen2.5:1.5b-instruct", "Référent médical local, réponses sous schéma JSON", "Tourne sur un processeur de portable ; format imposé, validateur derrière."],
           ["faster-whisper + Piper", "Oreilles et voix hors ligne, FR + EN", "Modèles embarqués, pas d’API ; latence acceptable sur CPU."],
           ["SQLite", "Dossier patient, semaine, messages, préférences", "Un fichier, aucune installation, requêtes paramétrées."],
           ["HTML / CSS / JS, WebGL", "Quatre pages, vaisseau 3D, cartes, micro sur chaque page", "Aucun framework à installer ; servi par la station ; revalidé à chaque chargement."],
           ["Dossier portable (.NET launcher)", "Python embarqué, runtime Ollama, modèles, manifeste SHA-256", "Double-clic sur n’importe quel PC ; 3 791 fichiers vérifiés."]],
          [4.2 * cm, 6.2 * cm, 6.6 * cm])
    p("Le principe directeur : résilience et explicabilité plutôt qu’empilement. Chaque brique a un rôle compréhensible "
      "et reste remplaçable ; les règles explicites facilitent les tests hors ligne.")

    h1("10. Résultats obtenus")
    table([["Brique", "État", "Constat"],
           ["Surveillance et score", "Fonctionnelle", "40 membres à 10 Hz ; NEWS2 ; proposition d’isolement ; zones ; contacts ; tout persisté."],
           ["Référent médical local", "Fonctionnel", "Évaluations nommées, décisions, messages, réponses aux questions ; schéma + validateur ; réponses instantanées de la station sur l’isolement et l’équipage."],
           ["Voix", "Fonctionnelle", "Consentement parlé FR/EN, langue, mot de réveil, lecture des évaluations, réponses et messages."],
           ["Équipage et espaces personnels", "Fonctionnels", "Semaine en base pour les six, tableau de bord, membre en forme, activités ; un port par membre ; assistant nommé."],
           ["Cartes et vaisseau 3D", "Fonctionnels", "Carte depuis un message, vaisseau embarqué, zone qui s’illumine, lecture à voix haute."],
           ["Dossier portable", "Fonctionnel", "1,6 Go, lancement en 4 s, six ports ouverts, 3 791 fichiers vérifiés, aucun réseau."],
           ["Tests", "Verts", f"{tests} tests, dont des tests de bout en bout sur la station réelle et un test d’honnêteté du guide."],
           ["Capteurs physiques", "Prévue / simulation", "Contrat série fixé ; matériel non disponible pendant le workshop."]],
          [4.2 * cm, 3 * cm, 9.8 * cm])
    box("RÉSULTAT CLÉ", "Un équipage sans médecin dispose d’une station qui mesure, décide, explique et parle, "
        "entièrement à bord. Le modèle ne décide jamais du score, ne prescrit jamais, n’invente jamais un isolé ; "
        "s’il tombe, la surveillance continue.")
    table([["Donnée", "Valeur"],
           ["Membres simulés", "40, dont 6 = l’équipe, avec une semaine de mesures"],
           ["Pages / serveurs", "4 pages ; 7 serveurs (station + 6 espaces personnels)"],
           ["Scénarios", f"{scenarios}, écrits en écarts par rapport à la ligne de base"],
           ["Tests", f"{tests} (3 ignorés, 1 échec attendu : la levée automatique, non retenue)"],
           ["Modèle", "qwen2.5:1.5b-instruct, Ollama 0.13.1, processeur seul"],
           ["Voix", "faster-whisper base (FR + EN) ; Piper fr_FR-siwis + en_US-lessac"],
           ["Dossier portable", "1,6 Go, 3 791 fichiers SHA-256, lancement en 4 s"],
           ["Réponse du référent", "instantanée (station) ; 9 à 14 s (modèle, chaud) sur le portable de soutenance"]],
          [5 * cm, 12 * cm])

    h1("11. Limites et perspectives")
    bullets(["Toutes les mesures sont synthétiques et le disent ; aucun capteur réel, aucun étalonnage.",
             "Le modèle est léger et répond en 9 à 14 secondes quand la station ne peut pas répondre elle-même.",
             "Les contacts enregistrés ne prouvent pas une contamination ; les affectations sont re-proposées, pas rechargées, après un redémarrage.",
             "Le prototype est une simulation : il ne constitue pas un dispositif médical validé et ne doit pas servir à décider de soins réels."])
    p("La trajectoire d’évolution, dont les premières marches sont en cours pendant le workshop :")
    table([["Étape", "Évolution"],
           ["V0.9 — Soutenance (en cours)", "Attente de fin de parole avant transcription (détection de silence) ; réflexion visible et parlée (« je relève les constantes… je compare à votre ligne de base… ») ; réponses plus courtes ; vue par pièce du vaisseau."],
           ["V1.0 — Le vaisseau visité", "Vue pièce par pièce et vue vaisseau ; le référent montre les zones pendant ses briefs (« la zone A est prête, deux places ») ; ronde automatique toutes les heures avec compte rendu parlé."],
           ["V1.1 — Le briefing du bord", "Brief du matin parlé à l’équipage (état, membre en forme, activités) ; journal de bord audio des décisions ; tracé des contacts sur le vaisseau."],
           ["V1.2 — Dérive et capteurs", "Moteur de dérive sur la semaine (PsychoSpace) ; tête de mesure ESP32 (pouls, SpO2, température) sur le contrat série existant ; mode basse consommation (modèle en veille, surveillance intacte)."],
           ["Inter-piliers", "Lire l’état énergie et eau du vaisseau pour adapter les priorités ; exposer les décisions aux autres systèmes avec des règles explicites."]],
          [4.5 * cm, 12.5 * cm])

    h1("12. Organisation de l’équipe")
    table([["Responsable", "Périmètre"],
           ["Eddy", "Direction ; vues 2D/3D ; référent médical (modèle, schémas, validateur, persona) ; voix ; équipage et espaces personnels ; messages et cartes ; dossier portable ; tests ; dossier et présentation."],
           ["Brad", "Dossier patient persistant (réponses, historique de priorité, contacts, sessions) ; scénarios « slow-burn » et « false-alarm » ; règles de quarantaine ; premier dossier technique."],
           ["Davidson", "Systèmes — à compléter."],
           ["Anthony", "Navigation — à compléter."],
           ["Frederic", "Communications — à compléter."],
           ["Merove", "Secouriste — à compléter."],
           ["Intégration commune", "API, affichage partagé, non-régression (fusion du 24 septembre)."]],
          [4 * cm, 13 * cm])

    h1("13. Conclusion")
    p("MedBox répond au besoin concret du scénario : un équipage sans médecin, loin de la Terre, garde une station qui "
      "voit chacun, décide vite, explique, parle, et n’a besoin de personne d’autre que de lui-même. La séparation "
      "entre le chemin déterministe (mesures, score, décisions) et le chemin du langage (référent sous contrainte) "
      "rend la station crédible dans un environnement où l’erreur coûte cher.")
    p("Le prototype est une base réaliste : capteurs réels, vue par pièce, briefs et rondes, moteur de dérive, "
      "mode basse consommation. Il ne prétend pas être prêt pour un vol ; il démontre une architecture cohérente, "
      "autonome, vérifiée et livrée.")
    box("PHRASE DE SYNTHÈSE", "« MedBox transforme un portable sans réseau en station médicale de bord : elle mesure "
        "l’équipage, décide et explique les isolements, parle à chacun dans sa langue, et continue quand tout le reste "
        "s’arrête. »")

    h1("14. Références documentaires")
    bullets(["EPSI — Sujet de Workshop National B3, « Horizon 2080 », session septembre 2026 (contexte, piliers, contraintes offline, scénarios de crise, livrables).",
             "Royal College of Physicians — National Early Warning Score (NEWS) 2, 2017 : barème repris tel quel dans server/triage.py.",
             "Ollama (moteur d’inférence local) ; Qwen2.5-1.5B-Instruct (modèle) ; faster-whisper (reconnaissance) ; Piper (synthèse vocale).",
             "Dépôt MedBox (GitHub EddyEtame/MedBox) : README.md, docs/COMPRENDRE-MEDBOX.md, docs/USER_GUIDE.md, docs/dossier/NOTE-POUR-LE-DOSSIER.md, CLAUDE.md.",
             "Premier dossier technique de l’équipe, 23 septembre 2026 (Brad), repris et complété dans ce document."])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 28.6 * cm, "MedBox — Mallette médicale intelligente de bord")
        canvas.drawRightString(19 * cm, 28.6 * cm, f"Workshop B3 — Horizon 2080  |  Dossier technique  |  Page {doc.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(2 * cm, 28.4 * cm, 19 * cm, 28.4 * cm)
        canvas.drawString(2 * cm, 1.1 * cm, f"MedBox | Dossier technique | {date_fr}")
        canvas.restoreState()

    name = f"Workshop2026-B3-G{group}-Dossier-MedBox.pdf" if group else "Workshop2026-B3-Dossier-MedBox.pdf"
    path = OUT / name
    SimpleDocTemplate(str(path), pagesize=(21 * cm, 29.7 * cm), rightMargin=2 * cm, leftMargin=2 * cm,
                      topMargin=2.2 * cm, bottomMargin=1.8 * cm, title="MedBox — Dossier technique",
                      author="Équipe MedBox").build(story, onFirstPage=footer, onLaterPages=footer)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--group", help="Numéro de groupe, si attribué")
    args = parser.parse_args()
    if args.group and not args.group.replace("_", "").isalnum():
        parser.error("Use a group number or an alphanumeric placeholder.")
    path = build(args.group)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
