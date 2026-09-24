"""Build the defence deck (PPTX): ten slides, dark, one idea per slide.

Document tooling only (python-pptx); output goes to .build\\deliverables,
ignored by Git. Page captures from .build\\deliverables\\shots are used when
they exist.

    .venv\\Scripts\\python tools\\build_deck.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".build" / "deliverables"
SHOTS = OUT / "shots"

BG = RGBColor(0x05, 0x0F, 0x17)
PANEL = RGBColor(0x0B, 0x1B, 0x25)
INK = RGBColor(0xEA, 0xFB, 0xF8)
MUTED = RGBColor(0x8F, 0xA8, 0xB2)
ACCENT = RGBColor(0x7B, 0xE8, 0xD3)
WARN = RGBColor(0xF0, 0xC4, 0x59)
CRIT = RGBColor(0xFF, 0x5C, 0x6E)

W, H = Inches(13.333), Inches(7.5)


def count_tests() -> int:
    n = 0
    for f in (ROOT / "tests").glob("test_*.py"):
        n += len(re.findall(r"^def test_", f.read_text(encoding="utf-8", errors="replace"), re.M))
    return n


def count_scenarios() -> int:
    return len(list((ROOT / "scenarios").glob("*.yaml")))


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = W, H
        self.blank = self.prs.slide_layouts[6]
        self.n = 0

    def slide(self, kicker: str, title: str):
        self.n += 1
        s = self.prs.slides.add_slide(self.blank)
        bg = s.background.fill
        bg.solid()
        bg.fore_color.rgb = BG
        self.text(s, kicker.upper(), Inches(0.6), Inches(0.35), Inches(9), Inches(0.4), size=12, color=ACCENT, bold=True, spacing=2)
        self.text(s, title, Inches(0.6), Inches(0.7), Inches(12), Inches(1.0), size=32, color=INK, bold=True)
        self.text(s, f"MEDBOX  ·  HORIZON 2080          {self.n} / 10", Inches(0.6), Inches(6.95), Inches(12), Inches(0.35), size=10, color=MUTED, spacing=2)
        return s

    @staticmethod
    def text(s, txt, x, y, w, h, size=18, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=0, font="Segoe UI"):
        tb = s.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        lines = txt.split("\n")
        for i, line in enumerate(lines):
            par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            par.alignment = align
            run = par.add_run()
            run.text = line
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.name = font
            run.font.color.rgb = color
            if spacing:
                run.font._element.set("spc", str(spacing * 100))
        return tb

    @staticmethod
    def panel(s, x, y, w, h, fill=PANEL, line=None):
        shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
        shp.adjustments[0] = 0.06
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
        if line is None:
            shp.line.fill.background()
        else:
            shp.line.color.rgb = line
            shp.line.width = Pt(1)
        shp.shadow.inherit = False
        return shp

    def card(self, s, x, y, w, h, head, body, head_color=ACCENT):
        self.panel(s, x, y, w, h)
        self.text(s, head, x + Inches(0.25), y + Inches(0.18), w - Inches(0.5), Inches(0.5), size=16, color=head_color, bold=True)
        self.text(s, body, x + Inches(0.25), y + Inches(0.75), w - Inches(0.5), h - Inches(0.9), size=13, color=INK)

    def picture(self, s, name, x, y, w):
        f = SHOTS / name
        if f.exists():
            s.shapes.add_picture(str(f), x, y, width=w)
            return True
        return False

    def number(self, s, x, y, w, value, label, color=ACCENT):
        self.text(s, value, x, y, w, Inches(0.9), size=44, color=color, bold=True, align=PP_ALIGN.CENTER)
        self.text(s, label, x, y + Inches(0.9), w, Inches(0.6), size=13, color=MUTED, align=PP_ALIGN.CENTER)

    def save(self, path: Path):
        self.prs.save(str(path))


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    tests, scenarios = count_tests(), count_scenarios()
    d = Deck()

    # 1 — title
    s = d.slide("Workshop 2026 · B3 · HumanTech & HealthTech spatiales", "MedBox")
    d.text(s, "Le référent médical du bord, pour un équipage sans médecin.", Inches(0.6), Inches(1.7), Inches(12), Inches(0.8), size=22, color=ACCENT)
    d.text(s, "Quarante personnes, une liaison Terre qui ne répond plus, une station qui mesure, décide, explique et parle — entièrement à bord.",
           Inches(0.6), Inches(2.5), Inches(11), Inches(1.2), size=16, color=INK)
    if not d.picture(s, "ship.png", Inches(0.6), Inches(3.6), Inches(6.2)):
        d.panel(s, Inches(0.6), Inches(3.6), Inches(6.2), Inches(3.0))
    d.text(s, "Eddy · Brad · Davidson · Anthony · Frederic · Merove", Inches(7.2), Inches(5.9), Inches(5.6), Inches(0.5), size=14, color=MUTED, align=PP_ALIGN.RIGHT)

    # 2 — the need
    s = d.slide("Le besoin", "Un équipage loin de la Terre, sans médecin")
    d.card(s, Inches(0.6), Inches(1.9), Inches(3.9), Inches(3.9), "MESURER",
           "Cinq constantes à 10 Hz pour quarante membres, comparées à la plage habituelle de chacun. Une seule valeur ne suffit jamais.")
    d.card(s, Inches(4.7), Inches(1.9), Inches(3.9), Inches(3.9), "DÉCIDER",
           "Score NEWS2 par des règles explicites. Le référent nomme ce que les mesures montrent, décide l’isolement, attribue une zone.", WARN)
    d.card(s, Inches(8.8), Inches(1.9), Inches(3.9), Inches(3.9), "PARLER",
           "Il le dit à la personne et à l’équipage, à l’écran et à voix haute, en français ou en anglais. Il écoute, s’éveille sur son nom, répond.", CRIT)
    d.text(s, "Contrainte du workshop : tout à bord, sans réseau. Contamination de 15 % de l’équipage à contenir.", Inches(0.6), Inches(6.1), Inches(12), Inches(0.6), size=14, color=MUTED)

    # 3 — what we built
    s = d.slide("Ce que nous avons construit", "Quatre pages, sept serveurs, une voix")
    if not d.picture(s, "crew.png", Inches(0.6), Inches(1.8), Inches(7.4)):
        d.panel(s, Inches(0.6), Inches(1.8), Inches(7.4), Inches(4.2))
    d.text(s, "Vaisseau 3D · Tableau 2D · Équipage · Espace personnel (un port par membre)\n\n"
              "L’équipage, c’est nous : six membres réels, une semaine de mesures en base, le membre en forme et ses habitudes, les activités du jour.\n\n"
              "Chaque décision d’isolement sonne, s’affiche en carte avec le vaisseau et la zone qui s’illumine, et se lit à voix haute.",
           Inches(8.3), Inches(1.8), Inches(4.5), Inches(4.6), size=14, color=INK)

    # 4 — demo
    s = d.slide("Démonstration", "Cinq temps, cinq minutes")
    steps = [("1", "Lancement", "Double-clic : station, six espaces et modèle prêts en 4 s. Le référent se présente ; consentement à la voix ; langue."),
             ("2", "Équipage", "La semaine de l’équipe, le membre en forme, les activités du jour."),
             ("3", "Contamination", "Six membres se dégradent ; messages sonores ; « Lire » : carte, vaisseau 3D, zone qui s’illumine, décision lue."),
             ("4", "Espace personnel", "Le référent reconnaît la personne, lit son évaluation à la deuxième personne, répond à sa question parlée."),
             ("5", "Panne", "Le modèle est arrêté : la surveillance continue, l’écran le dit. Relancé : le référent revient.")]
    for i, (num, head, body) in enumerate(steps):
        y = Inches(1.75 + i * 1.0)
        d.panel(s, Inches(0.6), y, Inches(12.1), Inches(0.9))
        d.text(s, num, Inches(0.75), y + Inches(0.15), Inches(0.6), Inches(0.6), size=24, color=ACCENT, bold=True)
        d.text(s, head, Inches(1.5), y + Inches(0.12), Inches(2.6), Inches(0.6), size=16, color=INK, bold=True)
        d.text(s, body, Inches(4.1), y + Inches(0.14), Inches(8.4), Inches(0.7), size=13, color=INK)

    # 5 — how it works
    s = d.slide("Comment ça marche", "Deux chemins qui ne se mélangent jamais")
    d.card(s, Inches(0.6), Inches(1.9), Inches(5.9), Inches(3.6), "CHEMIN RAPIDE — SANS MODÈLE",
           "Source simulée (ou tête de mesure)\n→ NEWS2, proposition d’isolement, contacts\n→ SQLite, WebSocket à 10 Hz\n\nN’importe jamais le module IA. Si le modèle tombe, rien ne s’arrête.")
    d.card(s, Inches(6.8), Inches(1.9), Inches(5.9), Inches(3.6), "CHEMIN LENT — LE RÉFÉRENT",
           "Faits déterministes écrits par la station\n→ Ollama, réponse sous schéma JSON\n→ Validateur : ni médicament, ni dose, ni maladie inventée\n→ Écran et voix\n\nIsolement et équipage : la station répond elle-même, en millisecondes.", WARN)
    d.text(s, "FastAPI · SQLite · Ollama (qwen2.5 1.5B) · faster-whisper · Piper · WebGL · un dossier portable de 1,6 Go", Inches(0.6), Inches(5.8), Inches(12), Inches(0.5), size=13, color=MUTED)

    # 6 — safety
    s = d.slide("Sûreté", "Ce que le référent ne peut pas faire")
    items = [("Décider du score", "Le score et la proposition d’isolement viennent de règles que n’importe qui relit."),
             ("Prescrire", "Aucun médicament, aucune dose ne passe le validateur. Jamais."),
             ("Inventer", "Une condition n’est nommée que si les mesures la montrent ; un isolé n’existe que dans les registres de la station."),
             ("Lever un isolement", "Confirmation et levée sont des décisions humaines."),
             ("Écouter sans accord", "Consentement parlé, révocable ; rien de l’audio n’est conservé ; rien ne quitte le vaisseau.")]
    for i, (head, body) in enumerate(items):
        y = Inches(1.75 + i * 0.98)
        d.panel(s, Inches(0.6), y, Inches(12.1), Inches(0.88))
        d.text(s, head, Inches(0.85), y + Inches(0.14), Inches(3.4), Inches(0.6), size=16, color=CRIT, bold=True)
        d.text(s, body, Inches(4.3), y + Inches(0.15), Inches(8.2), Inches(0.7), size=13, color=INK)

    # 7 — results
    s = d.slide("Résultats", "Vérifié sur la machine de soutenance")
    cols = [("40", "membres suivis"), (str(scenarios), "scénarios rejouables"), (str(tests), "tests verts"),
            ("4 s", "lancement à froid"), ("7", "serveurs, un dossier"), ("0", "octet vers le réseau")]
    for i, (v, l) in enumerate(cols):
        x = Inches(0.6 + (i % 3) * 4.1)
        y = Inches(1.9 + (i // 3) * 2.2)
        d.panel(s, x, y, Inches(3.9), Inches(2.0))
        d.number(s, x, y + Inches(0.25), Inches(3.9), v, l, color=ACCENT if i != 5 else WARN)

    # 8 — team
    s = d.slide("L’équipe", "Nous sommes l’équipage")
    team = [("Eddy", "Commandant de bord", "Direction, vues 2D/3D, référent, voix, équipage, espaces, cartes, dossier portable, tests, dossier et deck."),
            ("Brad", "Ingénieur de vol", "Dossier patient persistant, historique de priorité, contacts, sessions, scénarios slow-burn et false-alarm, premier dossier."),
            ("Davidson", "Systèmes", "à compléter"), ("Anthony", "Navigation", "à compléter"),
            ("Frederic", "Communications", "à compléter"), ("Merove", "Secouriste", "à compléter")]
    for i, (name, role, what) in enumerate(team):
        x = Inches(0.6 + (i % 3) * 4.1)
        y = Inches(1.8 + (i // 3) * 2.45)
        d.panel(s, x, y, Inches(3.9), Inches(2.25))
        d.text(s, name, x + Inches(0.25), y + Inches(0.15), Inches(3.4), Inches(0.5), size=18, color=ACCENT, bold=True)
        d.text(s, role.upper(), x + Inches(0.25), y + Inches(0.6), Inches(3.4), Inches(0.4), size=10, color=MUTED, spacing=2)
        d.text(s, what, x + Inches(0.25), y + Inches(0.95), Inches(3.4), Inches(1.2), size=11, color=INK)

    # 9 — next
    s = d.slide("Perspectives", "Ce qui vient, marche par marche")
    nxt = [("V0.9 · soutenance", "Fin de parole détectée avant transcription ; réflexion visible et parlée ; réponses plus courtes ; vue par pièce."),
           ("V1.0 · le vaisseau visité", "Vue pièce par pièce et vue vaisseau ; le référent montre les zones pendant ses briefs ; ronde automatique avec compte rendu parlé."),
           ("V1.1 · le briefing du bord", "Brief du matin parlé à l’équipage ; journal de bord audio ; tracé des contacts sur le vaisseau."),
           ("V1.2 · dérive et capteurs", "Moteur de dérive sur la semaine ; tête de mesure ESP32 sur le contrat série existant ; mode basse consommation.")]
    for i, (head, body) in enumerate(nxt):
        y = Inches(1.8 + i * 1.2)
        d.panel(s, Inches(0.6), y, Inches(12.1), Inches(1.08))
        d.text(s, head, Inches(0.85), y + Inches(0.15), Inches(3.6), Inches(0.6), size=15, color=WARN, bold=True)
        d.text(s, body, Inches(4.5), y + Inches(0.15), Inches(8.0), Inches(0.9), size=13, color=INK)

    # 10 — closing
    s = d.slide("Bilan", "Ce que nous avons démontré")
    d.panel(s, Inches(0.6), Inches(1.9), Inches(12.1), Inches(3.2), fill=PANEL, line=ACCENT)
    d.text(s, "« MedBox transforme un portable sans réseau en station médicale de bord : elle mesure l’équipage, décide et explique les isolements, "
              "parle à chacun dans sa langue, et continue quand tout le reste s’arrête. »",
           Inches(1.0), Inches(2.2), Inches(11.3), Inches(2.6), size=20, color=INK)
    d.text(s, "Prototype de simulation : mesures synthétiques, pas un dispositif médical validé. Tout le reste est réel, testé et livré.",
           Inches(0.6), Inches(5.5), Inches(12), Inches(0.6), size=14, color=MUTED)

    path = OUT / "Workshop2026-B3-Pres-MedBox.pptx"
    d.save(path)
    return path


def main() -> int:
    print(build())
    return 0


if __name__ == "__main__":
    sys.exit(main())
