"""Build the local workshop dossier; PDF is intentionally ignored by Git.

Requires reportlab (document tooling, not a runtime dependency of MedBox).
"""
from pathlib import Path
import argparse
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', help='Numéro de groupe, si attribué')
    parser.add_argument('--members', default='', help='Noms des membres, séparés par des virgules')
    args = parser.parse_args()
    if args.group and not args.group.replace('_', '').isalnum():
        parser.error('Use a group number or an alphanumeric placeholder.')
    out = ROOT / 'output' / 'pdf'
    out.mkdir(parents=True, exist_ok=True)
    filename = f'Workshop2026-B3-G{args.group}-Dossier.pdf' if args.group else 'Workshop2026-B3-Dossier-MedBox.pdf'
    path = out / filename
    styles = getSampleStyleSheet()
    styles['BodyText'].fontName = 'Helvetica'
    styles['BodyText'].fontSize = 10
    styles['BodyText'].leading = 15
    styles.add(ParagraphStyle('Cover', parent=styles['Title'], fontSize=30, leading=36, textColor=colors.HexColor('#12364a')))
    story = []
    def p(text):
        story.append(Paragraph(text, styles['BodyText']))
        story.append(Spacer(1, 9))
    def h(text):
        story.append(Paragraph(text, styles['Heading2']))
    def table(rows, widths):
        cells = [[Paragraph(str(x).replace('≤', '&lt;=').replace('≥', '&gt;='), styles['BodyText']) for x in row] for row in rows]
        t = Table(cells, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e0edf2')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#b6c8d0')),
            ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        story.append(t)
    def page(): story.append(PageBreak())
    story.append(Spacer(1, 35))
    story.append(Paragraph('MedBox', styles['Cover']))
    p('Horizon 2080 - Workshop EPSI Bachelor 3 - Septembre 2026')
    group_label = f'Groupe {args.group}' if args.group else 'Groupe : numéro non attribué'
    p(f'<b>Dossier technique - {group_label}</b><br/>23 septembre 2026')
    if args.members:
        p(f'<b>Équipe :</b> {args.members}')
    h('Une station locale pour suivre un équipage isolé')
    p('Le prototype rassemble les mesures simulées de 40 membres d’équipage, calcule une priorité, conserve les données et propose une assistance conversationnelle locale. Il vise à démontrer une continuité de surveillance pendant une contamination touchant 15 % de l’équipage.')
    h('Périmètre réellement réalisé')
    p('Deux interfaces web, un serveur Python, une base SQLite, un client Ollama, des scénarios reproductibles, la saisie de réponses patient, des courbes d’historique et une gestion de quarantaine. Le matériel n’est pas disponible : toutes les mesures de la démonstration sont synthétiques.')
    h('Avant le dépôt')
    p('Si un numéro de groupe est attribué, l’ajouter avant le dépôt. Exécuter les tests sur la machine de soutenance et évaluer les réponses du modèle Ollama choisi. Aucun étalonnage matériel n’a été réalisé.')
    p('<b>Statut :</b> prototype pédagogique. Il ne constitue pas un dispositif médical validé et ne doit pas servir à décider de soins réels.')
    page()
    h('1. Architecture et choix techniques')
    table([
        ['Couche', 'Rôle et justification'],
        ['HTML / CSS / JavaScript', 'Interface locale : vue 3D et tableau 2D. Les réponses et historiques utilisent un module commun.'],
        ['Python / FastAPI', 'API HTTP, diffusion WebSocket et boucle de simulation dans un même serveur.'],
        ['SQLite', 'Stockage local dans un fichier : mesures, réponses, événements et contacts. Requêtes paramétrées.'],
        ['Ollama', 'Service IA local appelé à la demande. Sa panne ne doit pas interrompre les mesures.'],
    ], [4*cm, 12*cm])
    h('Deux chemins distincts')
    table([
        ['Chemin de surveillance', 'Chemin de conversation'],
        ['1. Source simulée<br/>2. Score déterministe et quarantaine<br/>3. SQLite et affichage WebSocket',
         '1. Question et réponse du patient<br/>2. SQLite, puis texte déclaré non fiable<br/>3. Ollama, validation, affichage'],
    ], [8*cm, 8*cm])
    p('Les modules de mesure, stockage et triage n’importent pas le module IA. Les réponses du patient n’entrent pas dans le calcul du score. L’interface conserve un message clair lorsque l’assistant est indisponible.')
    h('Fonctionnement hors ligne')
    p('Après installation des dépendances et téléchargement des modèles, les échanges restent locaux. Le prototype sert ses ressources web depuis le serveur. Les fonctions de reconnaissance vocale dépendent d’un modèle local optionnel.')
    page()
    h('2. Dialogue et historique patient')
    p('Le serveur reçoit une question et une réponse par POST /api/patient/{id}/answer. Il vérifie que le patient existe, refuse les champs vides et limite les longueurs. SQLite conserve question, réponse et horodatage, y compris après redémarrage.')
    p('Les boutons Oui, Non et Incertain, ainsi qu’une saisie libre, sont présents dans les deux vues. Une confirmation d’enregistrement invite à relancer l’analyse. Les trois dernières réponses rejoignent le bloc de déclarations délimité par SymptomLog ; les caractères permettant de fermer ce bloc sont neutralisés.')
    p('Quatre courbes représentent les dix dernières minutes disponibles. Le dernier changement de niveau dans cette période est indiqué par un trait jaune. Les niveaux et leurs transitions sont enregistrés indépendamment des analyses IA.')
    h('3. Quarantaine et contacts')
    p('Le prototype conserve les règles d’admission existantes : fièvre associée à une désaturation, une respiration élevée ou un niveau de priorité au moins medium. Une zone occupée est signalée comme fermée ; un manque de place reste visible.')
    p('La sortie exige au moins 120 secondes depuis l’affectation et deux observations complètes ne déclenchant plus l’isolement, espacées d’au moins deux secondes. Une rechute ou une valeur absente remet le compteur à zéro. Cette durée est uniquement une convention de démonstration, pas un protocole clinique.')
    p('Le registre conserve les paires de patients présents dans la même zone, avec début et fin de co-présence. Les données sont persistées. Cela ne prouve pas une contamination et ne couvre pas les contacts hors des zones suivies.')
    page()
    h('4. Barème implémenté et scénarios')
    p('Le tableau ci-dessous décrit le code existant server/triage.py. Il ne constitue pas une validation indépendante de NEWS2. La pression artérielle n’est pas mesurée ; conscience et oxygène supplémentaire sont supposés par défaut.')
    table([
        ['Paramètre', 'Points attribués par le prototype'],
        ['Température', '≤35 : 3 ; ≤36 : 1 ; ≤38 : 0 ; ≤39 : 1 ; au-delà : 2.'],
        ['SpO2', '≤91 : 3 ; ≤93 : 2 ; ≤95 : 1 ; au-delà : 0.'],
        ['Pouls', '≤40 : 3 ; ≤50 : 1 ; ≤90 : 0 ; ≤110 : 1 ; ≤130 : 2 ; au-delà : 3.'],
        ['Respiration', '≤8 : 3 ; ≤11 : 1 ; ≤20 : 0 ; ≤24 : 2 ; au-delà : 3.'],
        ['Priorité', 'Total ≥7 : high ; ≥5 : medium ; un paramètre à 3 : medium ; total ≥1 : low ; sinon routine.'],
    ], [4*cm,12*cm])
    h('Scénarios de démonstration')
    table([
        ['Scénario', 'Résultat à observer'],
        ['contamination', 'Six membres sur quarante se dégradent ; classement et zones évoluent.'],
        ['single-patient', 'Une consultation avec mesures évolutives et questions de l’assistant.'],
        ['slow-burn', 'Un patient se dégrade pendant 600 secondes. Courbes et transitions permettent de suivre cette évolution.'],
        ['false-alarm', 'Température élevée, oxygénation et respiration conservées : pas d’isolement attendu.'],
    ], [4*cm,12*cm])
    page()
    h('5. Validation, organisation et limites')
    p('Le point de départ est le commit eec32cb, récupéré en fast-forward depuis 57de847. La première exécution sous Windows comportait un test de chemin incompatible ; la vérification a été rendue indépendante des séparateurs de plateforme.')
    p('Les nouveaux tests vérifient la conservation des réponses après réouverture, les transitions de priorité, les champs invalides, l’absence de patient, les limites du contexte IA, la durée minimale, les observations espacées, les rechutes, les données manquantes, les contacts et les résultats des deux nouveaux scénarios.')
    h('Répartition')
    table([
        ['Responsable', 'Périmètre'],
        ['Eddy', 'Interfaces initiales 2D/3D, IA, voix, manifeste de capacités et guide.'],
        ['Dev 2', 'Dialogue persistant, historique, scénarios complémentaires, quarantaine, contacts et dossier.'],
        ['Intégration commune', 'API, affichage partagé et validation de non-régression.'],
    ], [4*cm,12*cm])
    h('Limites et suite')
    p('D3 est reportée jusqu’à disponibilité des capteurs. Aucun résultat de calibration n’est revendiqué. Les affectations actives de quarantaine ne sont pas rechargées au redémarrage ; les historiques restent disponibles. La démonstration ne remplace pas une étude de sécurité ou une validation médicale.')
    p('Les vérifications avec le simulateur tools/fake_ollama.py prouvent la circulation des données et le rendu, pas la pertinence d’un vrai modèle. L’acceptation finale de D1 avec Ollama exige une revue manuelle sur la machine cible.')
    h('Capture de la démonstration')
    screenshot = ROOT / 'docs' / 'assets' / 'contamination-demo.png'
    if screenshot.exists():
        story.append(Image(str(screenshot), width=13.5*cm, height=13.5*cm*272/932))
        story.append(Paragraph('Scénario « contamination » : 40 personnes simulées, 6 avec des mesures préoccupantes et 6 isolées. Capture fournie par l’équipe le 23 septembre 2026.', styles['BodyText']))
    h('Sources du dossier')
    p('Cahier des charges EPSI Horizon 2080, pages 3, 7 à 9 ; tasks/dev-2.md ; README.md ; server/triage.py ; tests/test_dev2.py ; docs/DEV2_DELIVERY.md. Le PDF reste local et exclu de Git.')
    def footer(canvas, doc):
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(colors.HexColor('#546875'))
        canvas.drawString(2*cm,1.1*cm,'MedBox | Dossier technique | 23 septembre 2026')
        canvas.drawRightString(19*cm,1.1*cm,str(doc.page))
    SimpleDocTemplate(str(path),pagesize=(21*cm,29.7*cm),rightMargin=2*cm,leftMargin=2*cm,
                      topMargin=1.7*cm,bottomMargin=1.8*cm).build(story,onFirstPage=footer,onLaterPages=footer)
    print(path)


if __name__ == '__main__':
    main()
