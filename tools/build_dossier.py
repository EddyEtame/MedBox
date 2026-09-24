"""Build the crew's dossier (PDF): one team of six, two solutions.

The brief asks each crew for two to four projects, a technical dossier, a
deck and the code. Our crew of six built two solutions for the HumanTech &
HealthTech pillar: 1A MedBox (Eddy, Brad) for the body, 1B ARIA /
PsychoSpace (Davidson, Anthony, Frederic, Merove) for the mind. Part A is
written from MedBox's code and the day's numbers; Part B carries the 1B
team's own dossier text (ARIA, 23 September) as they wrote it.

    .venv\\Scripts\\python tools\\build_dossier.py [--group N]

Document tooling only (reportlab). The PDF goes to .build\\deliverables,
which Git ignores; page captures from .build\\deliverables\\shots are used
when present.
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

TEAM_A = [("Eddy", "commandant de bord"), ("Brad", "ingénieur de vol")]
TEAM_B = [("Davidson", "systèmes"), ("Anthony", "navigation"), ("Frederic", "communications"), ("Merove", "secouriste")]

NAVY = colors.HexColor("#12364a")
TEAL = colors.HexColor("#0e6b6b")
PLUM = colors.HexColor("#5b3a7a")
LINE = colors.HexColor("#b6c8d0")
HEAD_BG = colors.HexColor("#e0edf2")
HEAD_BG_B = colors.HexColor("#ece4f3")
BOX_BG = colors.HexColor("#eef6f8")
BOX_BG_B = colors.HexColor("#f3eef8")
MUTED = colors.HexColor("#546875")


def count_tests() -> int:
    """The number pytest reports on the last full run (the log in
    .build/logs), which counts parametrised cases; the source count is the
    fallback when no log exists."""
    logs = sorted((ROOT / ".build" / "logs").glob("pytest-*.log"), key=lambda f: f.stat().st_mtime)
    for log in reversed(logs):
        m = re.findall(r"(\d+) passed", log.read_text(encoding="utf-8", errors="replace"))
        if m:
            return int(m[-1])
    n = 0
    for f in (ROOT / "tests").glob("test_*.py"):
        n += len(re.findall(r"^\s*def test_", f.read_text(encoding="utf-8", errors="replace"), re.M))
    return n


def count_scenarios() -> int:
    return len(list((ROOT / "scenarios").glob("*.yaml")))


def french_date(d: dt.date) -> str:
    months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def styles():
    ss = getSampleStyleSheet()
    body = ss["BodyText"]
    body.fontName = "Helvetica"
    body.fontSize = 9.6
    body.leading = 14
    ss.add(ParagraphStyle("Cover", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=30, leading=36, textColor=NAVY, alignment=TA_CENTER))
    ss.add(ParagraphStyle("CoverSub", parent=body, fontSize=13, leading=18, alignment=TA_CENTER, textColor=TEAL))
    ss.add(ParagraphStyle("CoverLine", parent=body, fontSize=10.5, leading=15, alignment=TA_CENTER))
    ss.add(ParagraphStyle("Part", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=24, leading=30, textColor=NAVY, alignment=TA_CENTER, spaceBefore=40))
    ss.add(ParagraphStyle("PartB", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=24, leading=30, textColor=PLUM, alignment=TA_CENTER, spaceBefore=40))
    ss.add(ParagraphStyle("PartSub", parent=body, fontSize=12, leading=17, alignment=TA_CENTER, textColor=MUTED))
    ss.add(ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("H1B", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=PLUM, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=TEAL, spaceBefore=8, spaceAfter=4))
    ss.add(ParagraphStyle("H2B", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=PLUM, spaceBefore=8, spaceAfter=4))
    ss.add(ParagraphStyle("BoxTitle", parent=body, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=TEAL))
    ss.add(ParagraphStyle("BoxTitleB", parent=body, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=PLUM))
    ss.add(ParagraphStyle("BoxBody", parent=body, fontSize=9.6, leading=14))
    ss.add(ParagraphStyle("Caption", parent=body, fontSize=8.5, leading=11, textColor=MUTED, alignment=TA_CENTER))
    ss.add(ParagraphStyle("Bul", parent=body, leftIndent=12, bulletIndent=2))
    return ss


class Doc:
    def __init__(self, ss):
        self.ss = ss
        self.story: list = []
        self.part = "A"

    # -- primitives, coloured by part (A teal/navy, B plum)
    def p(self, text):
        self.story.append(Paragraph(text, self.ss["BodyText"]))
        self.story.append(Spacer(1, 6))

    def h1(self, text):
        self.story.append(Paragraph(text, self.ss["H1" if self.part == "A" else "H1B"]))

    def h2(self, text):
        self.story.append(Paragraph(text, self.ss["H2" if self.part == "A" else "H2B"]))

    def bullets(self, items):
        for it in items:
            self.story.append(Paragraph(it, self.ss["Bul"], bulletText="•"))
        self.story.append(Spacer(1, 6))

    def box(self, title, text):
        b = self.part == "B"
        t = Table([[Paragraph(title, self.ss["BoxTitleB" if b else "BoxTitle"])], [Paragraph(text, self.ss["BoxBody"])]], colWidths=[17 * cm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BOX_BG_B if b else BOX_BG), ("BOX", (0, 0), (-1, -1), 0.6, PLUM if b else TEAL),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        self.story.append(KeepTogether(t))
        self.story.append(Spacer(1, 8))

    def table(self, rows, widths):
        cells = [[Paragraph(str(x).replace("≤", "&lt;=").replace("≥", "&gt;="), self.ss["BodyText"]) for x in row] for row in rows]
        t = Table(cells, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                               ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG_B if self.part == "B" else HEAD_BG),
                               ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        self.story.append(t)
        self.story.append(Spacer(1, 8))

    def figure(self, name, caption, width=16 * cm):
        f = SHOTS / name
        if not f.exists():
            return
        try:
            from PIL import Image as PILImage
            w, h = PILImage.open(f).size
        except Exception:
            w, h = 1366, 768
        self.story.append(Image(str(f), width=width, height=width * h / w))
        self.story.append(Paragraph(caption, self.ss["Caption"]))
        self.story.append(Spacer(1, 8))

    def page(self):
        self.story.append(PageBreak())

    def part_page(self, title, sub, part):
        self.part = part
        self.story.append(Paragraph(title, self.ss["Part" if part == "A" else "PartB"]))
        self.story.append(Spacer(1, 10))
        self.story.append(Paragraph(sub, self.ss["PartSub"]))


# =============================================================== the crew
def crew_pages(d: Doc, group_label: str, date_fr: str, tests: int, scenarios: int):
    ss = d.ss
    d.story.append(Spacer(1, 2.4 * cm))
    d.story.append(Paragraph("Équipage Horizon 2080", ss["Cover"]))
    d.story.append(Paragraph("Deux solutions pour le vaisseau-monde", ss["CoverSub"]))
    d.story.append(Spacer(1, 0.5 * cm))
    d.story.append(Paragraph("<b>1A · MedBox</b> — mallette médicale intelligente de bord<br/>"
                             "<b>1B · ARIA / PsychoSpace</b> — assistant de bord autonome pour le bien-être de l’équipage", ss["CoverLine"]))
    d.story.append(Spacer(1, 1.0 * cm))
    d.box("MISSION", "Vous lisez le dossier d’un équipage de six qui a construit deux systèmes pour que quarante personnes "
          "restent en vie et lucides à des années de tout secours. MedBox pour le corps : elle mesure, décide, explique et "
          "parle. ARIA pour l’esprit : il observe, compare, accompagne. Tout à bord, rien dans le cloud, l’humain qui décide. "
          "Les deux tournent aujourd’hui sur un portable sans réseau ; vous pouvez les faire tourner sur le vôtre.")
    d.story.append(Spacer(1, 0.5 * cm))
    for line in ("Workshop National B3 — Horizon 2080 — EPSI", "Pilier HumanTech &amp; HealthTech Spatiales",
                 f"Dossier technique — {group_label}", date_fr):
        d.story.append(Paragraph(line, ss["CoverLine"]))
    d.story.append(Spacer(1, 0.7 * cm))
    d.story.append(Paragraph("<b>Équipe 1A (MedBox) :</b> " + ", ".join(f"{n} ({r})" for n, r in TEAM_A), ss["CoverLine"]))
    d.story.append(Paragraph("<b>Équipe 1B (ARIA / PsychoSpace) :</b> " + ", ".join(f"{n} ({r})" for n, r in TEAM_B), ss["CoverLine"]))
    d.page()

    d.h1("Sommaire")
    for t in ["L’équipage et ses deux solutions",
              "Partie A — MedBox (1A), sections A.1 à A.11 : du besoin aux perspectives",
              "Partie B — ARIA / PsychoSpace (1B), sections B.1 à B.11 : du besoin aux perspectives",
              "Organisation de l’équipage · Conclusion de l’équipage · Références documentaires"]:
        d.story.append(Paragraph(t, ss["BodyText"]))
    d.story.append(Spacer(1, 8))

    d.h1("L’équipage et ses deux solutions")
    d.p("On nous demandait deux projets. Nous avons pris le risque le plus silencieux du voyage : un équipage isolé ne "
        "s’effondre pas d’un coup, il se dégrade sans bruit, dans le corps ou dans l’esprit, et quand la Terre répond "
        "enfin, il est trop tard. Nous sommes six. Nous avons choisi le pilier HumanTech &amp; HealthTech Spatiales et "
        "ses deux propositions, MedBox et PsychoSpace, et nous les avons construites toutes les deux, en parallèle, "
        "jusqu’à ce qu’elles tournent.")
    d.box("CE QUE VOUS VERREZ", "Deux prototypes qui tournent sur un portable sans réseau, pas des maquettes. MedBox : une "
          f"station qui mesure quarante membres, décide et explique les isolements, parle et écoute ({tests} tests verts, "
          f"{scenarios} scénarios rejouables, un dossier portable vérifié fichier par fichier). ARIA : un assistant de bord "
          "qui suit le bien-être, repère une dérive progressive, consulte les procédures et propose une action.")
    d.table([["", "1A · MedBox", "1B · ARIA / PsychoSpace"],
             ["Ce qu’elle surveille", "La santé physique : cinq constantes à 10 Hz pour quarante membres, ligne de base personnelle.",
              "Le bien-être : sommeil, humeur, fatigue, stress, isolement, déclarés par check-in puis capteurs."],
             ["Ce qu’elle décide", "Un score explicite (NEWS2), une décision d’isolement, une zone ; le référent l’annonce et la lit à voix haute.",
              "Un niveau de priorité (à surveiller, préoccupant), une observation expliquée, une action proposée."],
             ["Le rôle de l’IA locale", "Le référent médical du bord : nomme ce que les mesures montrent, répond aux questions, ne prescrit jamais.",
              "ARIA : contextualise, pose des questions, consulte les procédures du vaisseau (RAG local), ne diagnostique jamais."],
             ["Ce qui est déterministe", "Score, isolement, contacts, faits donnés au modèle.", "Baseline personnelle, écarts, seuils, règles de priorité."],
             ["Sans réseau", "Tout dans un dossier de 1,6 Go : modèle, voix, données, pages.", "Ollama local, SQLite, base documentaire embarquée."],
             ["Équipe", ", ".join(n for n, _ in TEAM_A), ", ".join(n for n, _ in TEAM_B)]],
            [3.4 * cm, 6.8 * cm, 6.8 * cm])
    d.p("Les deux suivent la même logique, celle du pilier : mesurer, apprendre la ligne de base de chacun, suivre "
        "l’historique, comparer les écarts, analyser avec une IA locale, agir. Les deux tiennent le même principe : une "
        "seule donnée inhabituelle ne suffit jamais à conclure, et la décision qui pèse reste à un humain. Deux "
        "sous-équipes, un point chaque jour, et un seul vaisseau : c’est pour cela que vous les lisez ensemble.")
    d.page()


# =============================================================== part A
def part_a(d: Doc, tests: int, scenarios: int):
    d.part_page("Partie A — MedBox", "Mallette médicale intelligente de bord · projet 1A · Eddy, Brad", "A")
    d.story.append(Spacer(1, 1.0 * cm))
    d.box("MISSION", "Nous avons construit la station médicale d’un vaisseau qui n’a pas de médecin : elle surveille "
          "quarante personnes, décide et explique les isolements, parle à chacun dans sa langue, et continue quand la "
          "Terre ne répond plus.")

    d.h1("A.1 Présentation du projet")
    d.p("Imaginez quarante personnes, pas de médecin, et une contamination qui commence. MedBox est ce qui les garde en "
        "vie. Dans la simulation, le référent médical du bord est l’autorité médicale : il nomme ce que les mesures "
        "montrent, décide l’isolement, le dit à la personne concernée, prévient l’équipage et lit ses messages à voix "
        "haute. Il ne prescrit aucun médicament et n’invente jamais une maladie que les mesures ne montrent pas : chaque "
        "phrase qu’il prononce est passée par un schéma et un validateur avant d’être lue.")
    d.bullets(["Surveillance de quarante membres, dix mesures par seconde, score NEWS2 déterministe.",
               "Référent médical local (Ollama, modèle léger, réponses contraintes) qui parle et écoute, en français et en anglais.",
               "L’équipage, c’est l’équipe : six membres réels avec une semaine de mesures en base, un espace personnel chacun sur son propre port.",
               "Tableau de bord équipage, messages sonores, cartes avec le vaisseau 3D, vue par pièce et zone d’isolement qui s’illumine.",
               f"Livraison autonome : un dossier portable de 1,6 Go, {tests} tests, {scenarios} scénarios reproductibles."])
    d.box("POSITIONNEMENT", "Ne cherchez pas un chatbot médical : il n’y en a pas. MedBox est une station de bord. Elle "
          "mesure en continu, calcule une priorité par des règles que vous pouvez relire, décide et annonce les "
          "isolements, parle et écoute, tient le dossier de chacun et le tableau de bord de l’équipage, sans aucun service "
          "distant.")

    d.h1("A.2 Contexte et problématique")
    d.p("Six malades sur quarante, c’est le scénario du cahier des charges. Il faut les voir, les prioriser et les "
        "contenir à bord, avec des gens qui ne sont pas médecins et les moyens du vaisseau. Notre question tient en une "
        "ligne : comment donner à un équipage sans médecin une station qui surveille chacun en continu, décide vite et "
        "clairement qui isoler, explique sa décision à la personne et au groupe, et reste entièrement opérationnelle sans "
        "réseau ?")
    d.box("CONTRAINTE MAJEURE", "Tout fonctionne à bord : les mesures, le score, la décision, la voix, le modèle et les "
          "données. Pas une fonction ne dépend d’un service distant. Vous recevez la station comme un dossier autonome, "
          "vérifié fichier par fichier, que vous lancez d’un double-clic.")

    d.h1("A.3 Objectifs")
    d.bullets(["<b>Surveiller</b> quarante membres en continu à partir de constantes (simulées aujourd’hui, capteurs demain) et d’une ligne de base personnelle.",
               "<b>Prioriser</b> avec un score explicite (NEWS2) que n’importe qui peut relire, sans modèle dans la boucle.",
               "<b>Décider et expliquer</b> : le référent nomme ce que montrent les mesures, décide l’isolement, prévient la personne et l’équipage, à l’écran et à voix haute.",
               "<b>Parler à chacun</b> : un espace personnel par membre, où le référent sait à qui il parle, et un mot de réveil vocal.",
               "<b>Rester autonome</b> : modèle, voix, données et pages embarqués ; lancement en quelques secondes sans réseau."])

    d.h1("A.4 Inspiration du pilier HumanTech &amp; HealthTech")
    d.table([["Référence du workshop", "Transposition dans MedBox"],
             ["MedBox (pilier 1A)", "Mesures continues, score NEWS2, isolement décidé et annoncé, dossier patient persistant, référent médical qui parle."],
             ["Ligne de base personnelle", "Chaque membre a sa propre plage habituelle ; les scénarios sont écrits en écarts par rapport à elle."],
             ["IA locale / offline", "Ollama et le modèle sont dans le dossier livré ; reconnaissance et synthèse vocales aussi."],
             ["Gestion de crise", "Scénario « contamination » : six membres sur quarante se dégradent ; décisions, messages sonores, zones, contacts."],
             ["Capteurs / terminal", "Contrat de tête de mesure série prêt ; le prototype tourne sur des données synthétiques et le dit."]],
            [5 * cm, 12 * cm])

    d.h1("A.5 Solution proposée")
    d.table([["Brique", "Fonction"],
             ["Surveillance (chemin rapide)", "Mesures à 10 Hz, score NEWS2, proposition d’isolement, zones avec places, registre des contacts. N’importe jamais le module IA."],
             ["Référent médical (chemin lent)", "Évaluation nommée, décision, messages, réponses aux questions ; réponses contraintes par schéma JSON et validateur."],
             ["Voix, dans les deux sens", "Consentement parlé, choix de langue, mot de réveil (« MedBox » ou le nom donné à l’assistant), reconnaissance et synthèse hors ligne."],
             ["Équipage et espaces personnels", "Tableau de bord de la semaine, membre en forme et ses habitudes, activités du jour ; un espace par membre sur son port."],
             ["Messages et cartes", "Chaque décision d’isolement arrive avec un signal sonore ; « Lire » ouvre la carte, le vaisseau 3D et la pièce qui s’illumine, et lit le message."],
             ["Vaisseau 3D, vue par pièce", "Le vaisseau entier, chaque zone d’isolement avec ses couchettes et qui s’y trouve, l’infirmerie ; le référent fait la ronde à voix haute."],
             ["Dossier portable", "Python, Ollama, modèle, voix, pages et outils dans un dossier de 1,6 Go ; lanceur, contrôle avant soutenance, arrêt et relance du modèle."]],
            [4.6 * cm, 12.4 * cm])
    d.figure("crew.png", "Figure A1 — Le tableau de bord de l’équipage : messages du référent, membre en forme cette semaine, activités du jour, état de chacun.")

    d.h1("A.6 Architecture technique")
    d.p("Quatre pages, sept serveurs, un seul processus Python : la station principale sert le vaisseau, le tableau et "
        "l’équipage ; six serveurs légers, un par membre, servent les espaces personnels sur leur propre port.")
    d.h2("A.6.1 Interface — quatre pages")
    d.p("Vue 3D du vaisseau, tableau 2D, tableau de bord équipage, espace personnel (ports 8771 à 8776). HTML, CSS et "
        "JavaScript sans framework, servis par la station, revalidés à chaque chargement. Un menu commun, le micro et "
        "la voix sur chaque page.")
    d.h2("A.6.2 Backend — FastAPI, deux chemins")
    d.table([["Chemin de surveillance", "Chemin de conversation"],
             ["1. Source simulée (ou tête de mesure)<br/>2. NEWS2, proposition d’isolement, contacts<br/>3. SQLite et diffusion WebSocket à 10 Hz",
              "1. Faits déterministes écrits par la station<br/>2. Ollama, réponse contrainte par schéma JSON<br/>3. Validateur (ni médicament, ni dose, ni maladie inventée), écran, voix"]],
            [8.5 * cm, 8.5 * cm])
    d.h2("A.6.3 Données — SQLite")
    d.p("Mesures, événements, réponses du patient, historique des priorités, contacts, sessions, messages, préférences "
        "et une semaine de mesures par membre de l’équipe. Tout survit à un redémarrage ; les affectations d’isolement "
        "sont re-proposées au premier cycle, la confirmation reste humaine.")
    d.h2("A.6.4 IA locale — Ollama sous contrainte")
    d.p("Modèle qwen2.5:1.5b-instruct (processeur seul), appelé avec un schéma JSON qui impose la forme de la réponse. "
        "Un validateur relit chaque phrase : aucun médicament, aucune dose ; une condition ne peut être nommée que si "
        "les mesures la montrent. Les questions sur l’isolement et sur l’équipage sont répondues par la station "
        "elle-même, en quelques millisecondes, à partir de ses registres : le modèle ne peut pas inventer un isolé. "
        "Pendant qu’une réponse arrive, le référent montre ce qu’il fait (constantes, ligne de base, registres, "
        "possibilités, formulation) et le dit.")
    d.box("PRINCIPE DE SÉCURITÉ", "Le score, la proposition d’isolement et les faits viennent de règles explicites. Le "
          "modèle contextualise et formule ; il ne décide pas du score et ne prescrit pas. La levée d’isolement est une "
          "décision humaine. Le consentement micro est parlé, révocable, et rien de l’audio n’est conservé.")
    d.h2("A.6.5 Voix — hors ligne, dans les deux sens")
    d.p("Reconnaissance faster-whisper (français et anglais) qui attend la fin de la phrase avant de transcrire ; "
        "synthèse Piper (voix française et anglaise), 64 phrases pré-rendues et rendu à la demande. Le référent se "
        "présente, demande le consentement, propose la langue, s’éveille sur son nom, lit les évaluations, les réponses "
        "et les messages, et fait la ronde du vaisseau.")
    d.h2("A.6.6 Barème implémenté")
    d.table([["Paramètre", "Points attribués (server/triage.py)"],
             ["Température", "≤35 : 3 ; ≤36 : 1 ; ≤38 : 0 ; ≤39 : 1 ; au-delà : 2."],
             ["SpO2", "≤91 : 3 ; ≤93 : 2 ; ≤95 : 1 ; au-delà : 0."],
             ["Pouls", "≤40 : 3 ; ≤50 : 1 ; ≤90 : 0 ; ≤110 : 1 ; ≤130 : 2 ; au-delà : 3."],
             ["Respiration", "≤8 : 3 ; ≤11 : 1 ; ≤20 : 0 ; ≤24 : 2 ; au-delà : 3."],
             ["Priorité", "Total ≥7 : haute ; ≥5 : moyenne ; un paramètre à 3 : moyenne ; total ≥1 : faible ; sinon routine."]],
            [4 * cm, 13 * cm])
    d.p("Le barème décrit le code existant ; il ne constitue pas une validation indépendante de NEWS2 (Royal College of "
        "Physicians, 2017).")
    d.h2("A.6.7 Quarantaine, contacts, capteurs")
    d.p("Admission proposée sur fièvre associée à une désaturation, une respiration élevée ou une priorité au moins "
        "moyenne ; trois zones de quatre couchettes ; registre des paires de personnes ayant partagé une zone. Le "
        "contrat de la tête de mesure série est fixé et testé avec une source simulée ; le matériel n’était pas "
        "disponible pendant le workshop.")
    d.figure("ship.png", "Figure A2 — Le vaisseau vu de trois quarts, ouvert côté lecteur : deux ponts, quarante cabines, l’infirmerie, les trois zones d’isolement, les moteurs.")

    d.h1("A.7 Fonctionnement détaillé")
    d.bullets(["1. Le dossier se lance (MedBox.exe) : station, six espaces personnels et modèle démarrent ; la page s’ouvre en quatre secondes.",
               "2. Le référent se présente à voix haute et demande le consentement micro ; la personne répond « j’accepte » ; il propose la langue.",
               "3. Les constantes arrivent à 10 Hz ; le score et la priorité sont recalculés à chaque mesure et diffusés à toutes les pages.",
               "4. Quand une combinaison d’écarts apparaît, la station propose l’isolement et une zone ; le référent nomme ce que montrent les mesures.",
               "5. Un message part vers la personne et vers le tableau de bord, avec un signal sonore ; « Lire » ouvre la carte, la pièce et lit le message.",
               "6. Une personne confirme l’isolement, ou le lève ; contacts, réponses, historique de priorité sont conservés.",
               "7. Chaque membre, sur son espace, entend son évaluation à la deuxième personne, pose ses questions au clavier ou à la voix.",
               "8. Si le modèle tombe, tout continue : la surveillance, les décisions, les pages ; l’écran le dit."])
    d.h2("A.7.1 Exemple de réponse opérationnelle")
    d.table([["Message d’isolement (équipage, lu à voix haute)", "Réponse courte à une question (espace personnel)"],
             ["Isolement décidé pour Merove (Secouriste) : de la fièvre et une respiration rapide, exposition confirmée. Zone à attribuer. Accusez réception.",
              "« Est-ce que je dois m’inquiéter pour mon pouls ? » — Non, Eddy, votre pouls est dans votre plage habituelle."]],
            [8.5 * cm, 8.5 * cm])
    d.figure("me.png", "Figure A3 — Un espace personnel pendant la contamination : le message, l’évaluation à la deuxième personne, la semaine, le dossier.")

    d.h1("A.8 Scénarios de crise")
    d.table([["Scénario", "Ce que MedBox fait", "Priorité", "Logique"],
             ["Liaison Terre coupée 24 h", "Rien ne change : modèle, voix, données et pages sont à bord.", "Critique pour l’autonomie", "Aucune fonction ne dépend du cloud."],
             ["Énergie à 50 %", "Le chemin rapide est léger ; le modèle peut être arrêté sans perdre la surveillance.", "Élevée", "Les fonctions vitales restent prioritaires."],
             ["Eau contaminée", "Scénario « exposition-environnementale » : plusieurs membres se dégradent, contacts tracés, zones attribuées.", "Critique", "La station mesure et isole ; elle n’invente pas de procédure."],
             ["15 % de l’équipage malade", "Scénario « contamination » : six membres sur quarante ; décisions, messages sonores, cartes, zones, contacts.", "Critique", "Le référent décide ; l’équipage confirme et lève."],
             ["Dérive progressive", "Scénario « slow-burn » : dégradation lente sur dix minutes ; le score monte cran par cran.", "À surveiller, puis préoccupant", "Une mesure isolée ne suffit pas."]],
            [3.3 * cm, 7.4 * cm, 2.8 * cm, 3.5 * cm])
    d.figure("embed.png", "Figure A4 — La carte ouverte depuis un message : la caméra entre dans la zone d’isolement, le pont du dessus effacé, les quatre couchettes.", width=12 * cm)

    d.h1("A.9 Choix technologiques et justification")
    d.table([["Technologie", "Rôle", "Justification"],
             ["Python + FastAPI + WebSocket", "Un seul processus : API, diffusion à 10 Hz, simulation, six serveurs personnels", "Lisible, testable, sans infrastructure ; tout tient dans un dossier."],
             ["Ollama + qwen2.5:1.5b-instruct", "Référent médical local, réponses sous schéma JSON", "Tourne sur un processeur de portable ; format imposé, validateur derrière."],
             ["faster-whisper + Piper", "Oreilles et voix hors ligne, FR + EN", "Modèles embarqués, pas d’API."],
             ["SQLite", "Dossier patient, semaine, messages, préférences", "Un fichier, aucune installation."],
             ["HTML / CSS / JS, WebGL, three.js embarqué", "Quatre pages, vaisseau 3D, vue par pièce, cartes, micro partout", "Aucun framework à installer ; servi par la station."],
             ["Dossier portable (.NET launcher)", "Python embarqué, runtime Ollama, modèles, manifeste SHA-256", "Double-clic sur n’importe quel PC ; 3 791 fichiers vérifiés."]],
            [4.2 * cm, 6.2 * cm, 6.6 * cm])

    d.h1("A.10 Résultats obtenus")
    d.table([["Brique", "État", "Constat"],
             ["Surveillance et score", "Fonctionnelle", "40 membres à 10 Hz ; NEWS2 ; proposition d’isolement ; zones ; contacts ; tout persisté."],
             ["Référent médical local", "Fonctionnel", "Évaluations nommées, décisions, messages, réponses ; schéma + validateur ; réponses instantanées de la station sur l’isolement et l’équipage."],
             ["Voix", "Fonctionnelle", "Consentement parlé FR/EN, langue, mot de réveil, fin de phrase détectée, lecture des évaluations, réponses, messages, ronde."],
             ["Équipage et espaces personnels", "Fonctionnels", "Semaine en base pour les six, tableau de bord, membre en forme, activités ; un port par membre ; assistant nommé."],
             ["Vaisseau 3D et vue par pièce", "Fonctionnels", "Carte depuis un message, zones avec couchettes, qui est dans la pièce et sa santé, infirmerie, ronde parlée."],
             ["Dossier portable", "Fonctionnel", "1,6 Go, lancement en 4 s, six ports ouverts, 3 791 fichiers vérifiés, aucun réseau."],
             ["Tests", "Verts", f"{tests} tests, dont des tests de bout en bout sur la station réelle."],
             ["Capteurs physiques", "Prévue / simulation", "Contrat série fixé ; matériel non disponible pendant le workshop."]],
            [4.2 * cm, 3 * cm, 9.8 * cm])
    d.box("RÉSULTAT CLÉ", "Un équipage sans médecin a désormais une station qui mesure, décide, explique et parle, "
          "entièrement à bord. Le modèle ne décide jamais du score, ne prescrit jamais, n’invente jamais un isolé ; "
          "coupez-le pendant la démonstration, la surveillance continue et l’écran vous le dit.")

    d.h1("A.11 Limites et perspectives")
    d.bullets(["Toutes les mesures sont synthétiques et le disent ; aucun capteur réel, aucun étalonnage.",
               "Le modèle est léger et répond en 9 à 14 secondes quand la station ne peut pas répondre elle-même.",
               "Les contacts enregistrés ne prouvent pas une contamination.",
               "Le prototype est une simulation : il ne constitue pas un dispositif médical validé."])
    d.table([["Étape", "Évolution"],
             ["V1.0 — Le vaisseau visité", "Coque du vaisseau en 3D, vue pièce par pièce, ronde automatique horaire avec compte rendu parlé, tracé des contacts."],
             ["V1.1 — Le briefing du bord", "Brief du matin parlé à l’équipage ; journal de bord audio des décisions."],
             ["V1.2 — Dérive et capteurs", "Moteur de dérive sur la semaine (commun avec ARIA) ; tête de mesure ESP32 ; mode basse consommation."],
             ["Inter-projets", "MedBox lit les alertes de bien-être d’ARIA ; ARIA lit les isolements de MedBox : un même équipage, un même vaisseau."]],
            [4.5 * cm, 12.5 * cm])
    d.page()


# =============================================================== part B (the 1B team's own dossier, ARIA, 23 Sep)
def part_b(d: Doc):
    d.part_page("Partie B — ARIA / PsychoSpace", "Assistant Résident Interstellaire Autonome · projet 1B · Davidson, Anthony, Frederic, Merove", "B")
    d.story.append(Spacer(1, 1.0 * cm))
    d.box("MISSION", "Assister un équipage humain dans une mission interstellaire longue durée en restant autonome, local "
          "et explicable, notamment pour le suivi du bien-être et la gestion de situations de crise.")
    d.p("<i>Cette partie reprend le dossier technique rédigé par l’équipe 1B (ARIA, 23 septembre 2026).</i>")

    d.h1("B.1 Présentation du projet")
    d.p("ARIA — Assistant Résident Interstellaire Autonome — est un système logiciel d’assistance de bord destiné à un "
        "équipage humain engagé dans une mission interstellaire de très longue durée. Le projet s’inscrit dans le pilier "
        "HumanTech &amp; HealthTech du Workshop Horizon 2080 et reprend les objectifs de suivi longitudinal, "
        "d’accompagnement et d’autonomie décrits pour PsychoSpace.")
    d.p("L’idée centrale est de transformer l’IA locale en une brique opérationnelle du vaisseau. ARIA ne cherche pas à "
        "remplacer un médecin, un psychologue ou un commandant de bord. Elle sert à centraliser les informations utiles, "
        "détecter des évolutions, rappeler les procédures disponibles et proposer une réponse adaptée au contexte de mission.")
    d.bullets(["Assistance conversationnelle locale avec Ollama.",
               "Suivi des données de bien-être : sommeil, humeur, fatigue, stress et sentiment d’isolement.",
               "Historisation locale des échanges et des évaluations.",
               "Aide à l’analyse de données physiologiques et aux procédures médicales, sans diagnostic définitif.",
               "Base documentaire locale de type RAG pour exploiter les manuels et procédures du vaisseau."])
    d.box("POSITIONNEMENT", "ARIA ne se limite pas à une interface conversationnelle. Le prototype est pensé comme un système "
          "de mission local : il collecte des informations, conserve un historique, applique une logique d’analyse, "
          "consulte une base documentaire et utilise une IA locale pour formuler une assistance compréhensible.")

    d.h1("B.2 Contexte et problématique")
    d.p("Dans le scénario Horizon 2080, l’ESA développe des vaisseaux autonomes capables de voyager pendant des décennies. "
        "L’éloignement extrême de la Terre entraîne une contrainte structurante : les communications peuvent devenir "
        "inutilisables ou présenter une latence incompatible avec une assistance humaine immédiate. L’équipage doit donc "
        "continuer à fonctionner avec des ressources limitées et une capacité d’assistance embarquée.")
    d.p("Cette contrainte est particulièrement importante pour la santé et le bien-être. L’isolement prolongé, les "
        "perturbations du sommeil, la fatigue et l’évolution progressive du comportement peuvent dégrader la capacité "
        "d’un équipier à fonctionner normalement. Le système doit donc observer les tendances dans le temps plutôt que "
        "réagir uniquement à une valeur ponctuelle.")
    d.p("La problématique retenue : comment fournir à un équipage isolé une assistance locale capable de suivre son état, "
        "de repérer une dérive progressive et de proposer des actions adaptées, tout en restant résiliente lorsque le "
        "lien avec la Terre disparaît ?")
    d.box("CONTRAINTE MAJEURE", "La continuité de service doit être assurée localement. L’IA et les données indispensables "
          "au suivi ne doivent pas dépendre d’un service cloud pour les fonctions essentielles.")

    d.h1("B.3 Objectifs")
    d.bullets(["Surveiller le bien-être de l’astronaute à partir de check-ins et, à terme, de données issues de capteurs.",
               "Identifier les évolutions persistantes de sommeil, humeur, fatigue, stress, activité et isolement afin de repérer une dérive.",
               "Fournir une assistance locale claire : explication de l’observation, questions complémentaires, recommandations et niveau de priorité.",
               "Maintenir les fonctions essentielles sans Internet grâce à un modèle d’IA local et à des données stockées à bord.",
               "Faciliter la décision humaine en situation de crise sans automatiser aveuglément les décisions à fort impact."])

    d.h1("B.4 Inspiration du pilier HumanTech &amp; HealthTech")
    d.p("Le cahier des charges propose PsychoSpace pour le suivi psychologique et MedBox pour l’assistance médicale. Le "
        "document d’organisation de l’équipe précise une logique commune : mesurer, apprendre une baseline personnelle, "
        "observer l’historique, comparer les écarts, analyser le contexte avec une IA locale puis agir par une réponse "
        "ou une intervention personnalisée.")
    d.table([["Référence du workshop", "Transposition dans ARIA"],
             ["PsychoSpace", "Suivi du sommeil, de l’humeur, de la fatigue, du stress et de l’isolement ; analyse longitudinale et personnalisation."],
             ["MedBox", "Aide à l’analyse des symptômes, conservation de l’historique, formulation d’actions sûres et niveau d’urgence sans diagnostic définitif."],
             ["IA locale / offline", "Ollama exécuté à bord, sans dépendance obligatoire à Internet pour les fonctions principales."],
             ["Terminal / capteurs", "Architecture prévue pour recevoir des données ESP32 et des capteurs ; le prototype peut commencer avec des données simulées."],
             ["Gestion de crise", "Passage d’un état normal à un état à surveiller ou critique selon l’évolution des indicateurs et les procédures disponibles."]],
            [5 * cm, 12 * cm])
    d.p("Un principe de conception est particulièrement important : une seule donnée inhabituelle ne suffit pas à "
        "conclure. Le système recherche des tendances et des signaux convergents, et l’IA doit expliquer son observation "
        "afin que l’humain puisse la corriger ou la refuser.")

    d.h1("B.5 Solution proposée")
    d.p("ARIA est organisée comme une assistance de bord à plusieurs fonctions plutôt que comme un simple chatbot. La "
        "conversation constitue l’un des points d’accès au système, mais la valeur principale provient du croisement "
        "entre données, historique, règles et contexte documentaire.")
    d.table([["Brique", "Fonction"],
             ["ARIA / Conversation", "Permettre à l’astronaute de poser une question, décrire une situation ou demander une procédure."],
             ["Daily Pulse / Bien-être", "Enregistrer les indicateurs déclarés et fournir une synthèse courte et personnalisée."],
             ["Monitoring", "Suivre les données longitudinales et faire apparaître les évolutions importantes."],
             ["Drift Engine", "Comparer les nouvelles mesures à une baseline personnelle et rechercher une dérive persistante."],
             ["Base de connaissances", "Rechercher localement les passages pertinents des manuels et procédures avant génération de réponse."],
             ["Aide médicale", "Structurer l’analyse de symptômes et de constantes fournies, avec un niveau d’urgence indicatif et sans diagnostic définitif."],
             ["Console équipage", "Donner une vue synthétique des dernières alertes et priorités pour faciliter le suivi collectif."]],
            [4.6 * cm, 12.4 * cm])

    d.h1("B.6 Architecture technique")
    d.p("L’architecture vise un fonctionnement local, simple à maintenir et suffisamment modulaire pour connecter "
        "d’autres briques du vaisseau.")
    d.figure("aria-figure1.png", "Figure B1 — Architecture fonctionnelle proposée pour ARIA / PsychoSpace (dossier 1B).", width=14 * cm)
    d.h2("B.6.1 Frontend — interface de mission")
    d.p("L’interface web constitue le point de contact de l’équipage : état du système, conversations, historique, "
        "indicateurs de bien-être et alertes. Le prototype actuel est une interface web statique connectée au backend "
        "local ; l’architecture cible prévoit un frontend plus structuré avec React + Vite.")
    d.h2("B.6.2 Backend — orchestration locale")
    d.p("Le backend Python/FastAPI joue le rôle d’orchestrateur : il reçoit les requêtes, valide les entrées, interroge "
        "SQLite, prépare le contexte, appelle Ollama et enregistre les résultats. Les routes couvrent le statut du "
        "système, la conversation, l’analyse des symptômes, le suivi du bien-être, la recherche documentaire et les "
        "vues de tableau de bord.")
    d.p("<b>Frontend → FastAPI → SQLite / analyse → Ollama local → réponse → Frontend</b>")
    d.h2("B.6.3 Données locales — SQLite")
    d.p("SQLite conserve localement les conversations, les journaux médicaux, les journaux de bien-être et les fragments "
        "documentaires indexés ; une évolution vers PostgreSQL reste possible si le volume ou la concurrence l’exige.")
    d.h2("B.6.4 IA locale — Ollama")
    d.p("Ollama fournit le moteur d’inférence local. Le prototype est configuré avec un modèle léger de la famille "
        "Llama 3.2 et un modèle d’embeddings local pour le RAG. Un Modelfile définit le comportement d’ARIA : ton calme, "
        "priorité aux documents locaux, réponse structurée pour les procédures et interdiction de présenter une "
        "hypothèse médicale comme un diagnostic.")
    d.h2("B.6.5 Base de connaissances — RAG local")
    d.p("Les documents sont découpés en fragments, transformés en vecteurs par un modèle d’embeddings Ollama puis stockés "
        "dans SQLite. Lors d’une question, le backend calcule une représentation de la requête, recherche les fragments "
        "les plus proches et injecte uniquement ce contexte utile dans le prompt.")
    d.bullets(["Avantage opérationnel : les procédures peuvent évoluer sans réentraîner les poids du modèle.",
               "Avantage de traçabilité : les réponses peuvent citer les identifiants de documents utilisés.",
               "Avantage de résilience : la recherche documentaire ne dépend pas d’Internet."])
    d.h2("B.6.6 Analyse et moteur de dérive")
    d.p("Une baseline personnelle est construite à partir du fonctionnement habituel de chaque astronaute ; les nouvelles "
        "données sont comparées à cette référence afin de repérer des écarts persistants. Cette couche reste "
        "déterministe et explicable ; l’IA locale intervient ensuite pour interpréter le contexte, poser des questions "
        "et formuler l’accompagnement.")
    d.box("PRINCIPE DE SÉCURITÉ", "La détection de dérive ne doit pas reposer sur une décision opaque du modèle. Les calculs "
          "d’écart, seuils et règles de priorité restent explicites ; l’IA intervient principalement pour contextualiser "
          "et communiquer.")
    d.h2("B.6.7 Capteurs et IoT")
    d.p("L’architecture prévoit une couche ESP32 capable de transmettre des mesures au backend local : fréquence "
        "cardiaque, accéléromètre ou détection de mouvement, un bouton physique et, selon le matériel disponible, la "
        "SpO2. Dans le prototype de démonstration, ces données peuvent être simulées afin de valider le flux logiciel.")

    d.h1("B.7 Fonctionnement détaillé")
    d.bullets(["1. L’astronaute se connecte à son profil et effectue un check-in ou ouvre une conversation.",
               "2. Les données déclarées et, lorsque disponibles, les données capteurs sont validées par le backend.",
               "3. Les informations sont enregistrées localement afin de conserver un historique utilisable sur plusieurs jours.",
               "4. Le moteur d’analyse compare les nouvelles valeurs à la baseline personnelle et recherche une tendance ou plusieurs signaux convergents.",
               "5. Le backend récupère le contexte métier nécessaire : historique récent, indicateurs, procédures et documents pertinents.",
               "6. L’IA locale Ollama génère une réponse orientée mission : observation, explication, questions utiles et recommandations.",
               "7. La console présente la réponse, le niveau d’alerte et, lorsque nécessaire, une intervention ou une procédure à suivre.",
               "8. L’action humaine et les nouvelles données enrichissent l’historique pour permettre un suivi dans le temps."])
    d.h2("B.7.1 Exemple de réponse opérationnelle")
    d.table([["Réponse structurée d’ARIA"],
             ["PRIORITÉ : À SURVEILLER<br/>OBSERVATION : sommeil en baisse sur plusieurs jours + fatigue en hausse<br/>"
              "CONTEXTE : évolution différente de la baseline personnelle<br/>ACTION PROPOSÉE : effectuer le check-in complet et vérifier le contexte de mission<br/>"
              "SUIVI : recontrôle selon la procédure locale<br/>SOURCE : [DOC-...]"]],
            [17 * cm])
    d.p("L’objectif est de rendre la réponse exploitable en quelques secondes, sans masquer l’incertitude. ARIA explique "
        "ce qui a déclenché son intervention et distingue clairement une observation, une recommandation et une urgence.")

    d.h1("B.8 Scénarios de crise")
    d.table([["Scénario", "Action ARIA", "Priorité", "Logique de réponse"],
             ["Coupure de la liaison Terre pendant 24 h", "Basculer sur les ressources locales ; poursuivre le suivi, stocker les événements et maintenir les fonctions essentielles.", "Critique pour l’autonomie", "Aucune fonction critique ne doit nécessiter une réponse cloud."],
             ["Énergie disponible à 50 %", "Afficher les consommations, rappeler les priorités et proposer de réduire les charges non essentielles selon les règles embarquées.", "Élevée", "Les systèmes vitaux restent prioritaires."],
             ["Eau contaminée", "Récupérer la procédure locale, présenter les actions de confinement et rappeler les ressources restantes.", "Critique", "L’IA n’invente pas de procédure absente des documents."],
             ["15 % de l’équipage malade", "Centraliser les informations, aider à prioriser les cas, rappeler les procédures de quarantaine et conserver l’historique.", "Critique", "Le système assiste la décision humaine ; il ne remplace pas un protocole médical validé."],
             ["Dérive psychologique progressive", "Expliquer les tendances, vérifier le contexte avec l’humain et proposer une action personnalisée.", "À surveiller puis préoccupant", "Une mesure isolée ne suffit pas à conclure."]],
            [3.3 * cm, 7.0 * cm, 2.8 * cm, 3.9 * cm])
    d.h2("B.8.1 Scénario central de démonstration")
    d.p("Au départ, l’astronaute présente un fonctionnement habituel : sommeil proche de 7 h 30, activité normale, humeur "
        "haute et fatigue faible. Au fil de plusieurs jours, le sommeil baisse, la fatigue augmente et l’activité "
        "diminue ; un retrait social apparaît ensuite. L’astronaute peut alors écrire : « Ça va, je suis juste fatigué. » "
        "ARIA ne contredit pas brutalement cette perception : elle compare les données à l’historique, explique la "
        "dérive observée, demande si un événement particulier peut l’expliquer et propose une action cohérente avec "
        "les préférences connues. Détecter un changement progressif avant qu’il ne devienne une crise manifeste : "
        "c’est la valeur ajoutée du système.")

    d.h1("B.9 Choix technologiques et justification")
    d.table([["Technologie", "Rôle", "Justification"],
             ["Python + FastAPI", "Backend local, API claire, intégration simple avec les briques d’analyse et Ollama", "Bon compromis entre rapidité de développement, lisibilité et modularité."],
             ["Ollama + modèle léger", "Inférence locale sans dépendance obligatoire au cloud", "Adapté à la contrainte offline et au prototype ; permet d’expérimenter plusieurs modèles."],
             ["SQLite", "Stockage embarqué des historiques et données du prototype", "Installation minimale et fonctionnement local ; migration possible vers PostgreSQL."],
             ["RAG + embeddings locaux", "Accès aux procédures sans réentraîner le modèle", "Mise à jour des connaissances en remplaçant ou réindexant les documents."],
             ["Interface web", "Conversation, alertes, graphiques et vue équipage", "Rapide à démontrer et évolutive vers une application de cockpit."],
             ["ESP32 / capteurs", "Collecte de données physiques en local", "Rapproche le prototype du cas d’usage spatial réel, sans infrastructure distante."]],
            [4.2 * cm, 6.2 * cm, 6.6 * cm])
    d.p("Le principe directeur est de privilégier la résilience et l’explicabilité plutôt qu’un empilement de "
        "technologies spectaculaires. Chaque brique a un rôle compréhensible et reste remplaçable.")

    d.h1("B.10 Résultats obtenus")
    d.p("Le prototype permet déjà de démontrer une chaîne locale fonctionnelle autour d’Ollama et de FastAPI. La V2 "
        "ajoute une base de connaissances RAG locale et des routes dédiées au suivi médical, au bien-être, à la "
        "recherche documentaire et au tableau de bord.")
    d.table([["Brique", "État", "Constat"],
             ["IA locale", "Fonctionnelle", "Ollama est appelé depuis le backend local ; le modèle est configurable par variable d’environnement."],
             ["Conversation ARIA", "Fonctionnelle", "Historique local des échanges par équipier et par mode."],
             ["Suivi bien-être", "Fonctionnel", "Check-in avec sommeil, humeur, fatigue, stress et isolement ; analyse et niveau d’alerte stockés localement."],
             ["Aide médicale", "Fonctionnelle en démonstration", "Saisie de constantes et symptômes, interrogation de la base documentaire, réponse structurée et niveau d’urgence indicatif."],
             ["RAG local", "Fonctionnel en V2", "Indexation de documents TXT/MD/PDF et recherche sémantique avec embeddings Ollama."],
             ["Vue équipage", "Fonctionnelle en prototype", "Synthèse des derniers niveaux d’urgence et d’alerte."],
             ["Capteurs physiques", "Prévue / simulation", "Architecture documentée pour ESP32 et capteurs ; intégration matérielle non généralisée."],
             ["Moteur de dérive avancé", "Architecture cible", "La logique baseline + dérive fait partie de la conception ; son intégration complète reste à finaliser."]],
            [4.2 * cm, 3.4 * cm, 9.4 * cm])
    d.box("RÉSULTAT CLÉ", "Le prototype démontre déjà le principe essentiel : l’assistance peut rester locale, conserver son "
          "contexte et exploiter une base documentaire embarquée sans dépendre d’une API cloud.")

    d.h1("B.11 Limites et perspectives")
    d.bullets(["Les données physiques et certains scénarios sont simulés ou partiellement intégrés.",
               "Le modèle local reste volontairement léger pour tenir compte des ressources d’une machine de démonstration.",
               "Les procédures médicales restent dépendantes de documents validés ; l’IA ne doit pas être présentée comme un dispositif médical autonome.",
               "La mémoire personnalisée et le moteur de dérive peuvent encore être renforcés.",
               "La sécurité réseau, la gestion des rôles et le déploiement multi-machine doivent être approfondis pour un contexte industriel."])
    d.table([["Étape", "Évolution"],
             ["V0.5 — Prototype robuste", "Finaliser le flux check-in → stockage → analyse → IA → intervention ; consolider les scénarios de crise et la documentation."],
             ["V0.8 — Capteurs", "Connecter ESP32 et capteurs réels, fiabiliser la transmission locale et afficher les données dans le cockpit."],
             ["V0.9 — Intelligence documentaire", "Enrichir le RAG, ajouter la gestion de versions des procédures et améliorer les citations et contrôles de provenance."],
             ["V1 — Assistance embarquée", "Mémoire personnalisée, suivi longitudinal complet, sécurité des accès et déploiement résilient sur plusieurs nœuds."],
             ["Évolution inter-piliers", "Connecter ARIA à EnergyTech, FoodTech ou DeepTech pour utiliser les états d’autres systèmes du vaisseau avec des règles de priorité explicites."]],
            [4.5 * cm, 12.5 * cm])
    d.p("L’architecture est volontairement séparée en composants : interface, API, stockage, analyse, IA et base "
        "documentaire. Un composant peut être remplacé sans réécrire l’ensemble ; les données locales et les règles "
        "explicites facilitent les tests hors ligne.")
    d.page()


# =============================================================== the crew, closing
def closing(d: Doc, tests: int):
    d.part = "A"
    d.h1("Organisation de l’équipage")
    d.p("Un équipage de six, deux sous-équipes, un point quotidien. Chaque sous-équipe a porté sa solution de l’idée au "
        "prototype, au dépôt Git, au dossier et à la démonstration ; les deux se sont relues et ont aligné leurs "
        "principes (local, explicable, l’humain décide).")
    d.table([["Membre", "Sous-équipe", "Périmètre"],
             ["Eddy", "1A MedBox", "Direction ; vues 2D/3D et vue par pièce ; référent médical (modèle, schémas, validateur, persona) ; voix ; équipage et espaces personnels ; messages et cartes ; dossier portable ; tests ; dossier et présentation."],
             ["Brad", "1A MedBox", "Dossier patient persistant (réponses, historique de priorité, contacts, sessions) ; scénarios slow-burn et false-alarm ; règles de quarantaine ; premier dossier technique."],
             ["Davidson, Anthony, Frederic, Merove", "1B ARIA", "Conception et développement d’ARIA en équipe de quatre : orchestration FastAPI et stockage SQLite, base documentaire RAG avec embeddings locaux, suivi du bien-être et moteur de dérive, interface de mission et console équipage, scénarios de crise, dossier technique du 23 septembre ; dépôt Git ANTHONYSITCH/Psychospace."]],
            [2.6 * cm, 2.6 * cm, 11.8 * cm])

    d.h1("Conclusion de l’équipage")
    d.p("Deux solutions, un même vaisseau, une même conviction : loin de la Terre, ce qui sauve un équipage, c’est ce qui "
        "reste à bord et ce que chacun peut comprendre. MedBox garde le corps : elle mesure, décide et explique les "
        "isolements, parle et écoute. ARIA garde l’esprit : il observe la dérive, la nomme avant la crise et propose une "
        "action. Les deux séparent ce qui est calculé par des règles de ce qui est formulé par une IA locale, et laissent "
        "la décision qui pèse aux humains. Nous n’avons pas dessiné des écrans : nous avons livré deux systèmes qui "
        "tournent, testés, sans réseau, et nous vous les montrons.")
    d.p("La suite est déjà écrite : des capteurs réels sur le contrat série de MedBox et la couche ESP32 d’ARIA, un "
        "moteur de dérive commun sur la semaine de chacun, et les deux systèmes reliés, pour qu’un isolement décidé par "
        "MedBox devienne un suivi de bien-être pour ARIA et qu’une dérive vue par ARIA appelle une mesure de MedBox.")
    d.box("PHRASE DE SYNTHÈSE", "« Un vaisseau-monde n’a pas de médecin ni de psychologue à bord. Il a MedBox et ARIA : deux "
          "systèmes locaux qui mesurent, expliquent et accompagnent, et qui continuent quand la Terre ne répond plus. »")

    d.h1("Références documentaires")
    d.bullets(["EPSI — Sujet de Workshop National B3, « Horizon 2080 », septembre 2026.",
               "Royal College of Physicians — National Early Warning Score (NEWS) 2, 2017, repris tel quel dans MedBox.",
               "Dépôt MedBox (GitHub EddyEtame/MedBox) : README, docs/ ; dépôt PsychoSpace (GitHub ANTHONYSITCH/Psychospace) et dossier ARIA de l’équipe 1B du 23 septembre 2026, repris dans la partie B."])


def build(group: str | None) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    date_fr = french_date(dt.date.today())
    tests, scenarios = count_tests(), count_scenarios()
    d = Doc(styles())
    group_label = f"Groupe {group}" if group else "Groupe : numéro non attribué"
    crew_pages(d, group_label, date_fr, tests, scenarios)
    part_a(d, tests, scenarios)
    part_b(d)
    closing(d, tests)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 28.6 * cm, "Équipage Horizon 2080 — 1A MedBox · 1B ARIA / PsychoSpace")
        canvas.drawRightString(19 * cm, 28.6 * cm, f"Workshop B3 — Horizon 2080  |  Dossier technique  |  Page {doc.page}")
        canvas.setStrokeColor(LINE)
        canvas.line(2 * cm, 28.4 * cm, 19 * cm, 28.4 * cm)
        canvas.drawString(2 * cm, 1.1 * cm, f"Dossier technique | {date_fr}")
        canvas.restoreState()

    name = f"Workshop2026-B3-G{group}-Dossier.pdf" if group else "Workshop2026-B3-Dossier-Equipage.pdf"
    path = OUT / name
    SimpleDocTemplate(str(path), pagesize=(21 * cm, 29.7 * cm), rightMargin=2 * cm, leftMargin=2 * cm,
                      topMargin=2.2 * cm, bottomMargin=1.8 * cm, title="Horizon 2080 — Dossier technique — MedBox et ARIA",
                      author="Équipage Horizon 2080").build(d.story, onFirstPage=footer, onLaterPages=footer)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--group", help="Numéro de groupe, si attribué")
    args = parser.parse_args()
    if args.group and not args.group.replace("_", "").isalnum():
        parser.error("Use a group number or an alphanumeric placeholder.")
    print(build(args.group))
    return 0


if __name__ == "__main__":
    sys.exit(main())
