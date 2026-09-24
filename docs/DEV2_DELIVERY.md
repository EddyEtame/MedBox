# Livraison de Brad - 22 septembre 2026

Base récupérée : `eec32cb` (pull fast-forward depuis `57de847`).

## Travail intégré

- D1 : `answers` dans SQLite, API validée, boutons Oui / Non / Incertain et saisie libre sur les deux interfaces. Les trois dernières réponses persistées passent dans `SymptomLog` avant l'appel IA, jamais après ses délimiteurs. Une réponse ne modifie aucun score.
- D2 : quatre courbes sur les dix dernières minutes, transitions de niveau enregistrées, journal des scénarios et contacts. Actualisation toutes les cinq secondes, indépendante de l'IA.
- D3 : reporté, matériel indisponible confirmé par Brad. Pas de firmware prétendument testé, pas de courbe de calibration inventée.
- D4 : scénarios `slow-burn` (600 secondes) et `false-alarm`, avec vérification des priorités et de l'isolement.
- D5 : durée minimale de démonstration de 120 secondes, deux relevés complets non isolants espacés d'au moins deux secondes, compteur remis à zéro après rechute ou donnée manquante. Contacts de co-présence en zone persistés. La file d'attente était déjà affichée par le collaborateur.
- D6 : dossier PDF local préparé avec les six prénoms fournis et une capture de la crise (40 membres, 6 suivis, 6 isolés). Aucun numéro de groupe n'a été attribué ; le PDF reste ignoré par Git.

## Comment vérifier

Vérification du 22 septembre : 150 tests passent, 3 sont ignorés. Les formulaires
ont été essayés dans les deux vues : réponse Oui en 3D, réponse libre en 2D,
et lecture de la réponse persistée en changeant de vue. La vérification utilise
le simulateur explicitement étiqueté, avec une base séparée.

Vérification du 23 septembre : 150 tests passent, 3 sont ignorés. Dans la vue 2D,
`false-alarm` a donné LOW 2 sans isolement ; `contamination` a donné 6 personnes
sur 40 avec des mesures préoccupantes, 6 isolées, et des patients HIGH 9 classés
en tête. La capture fournie par l'équipe est dans `docs/assets/contamination-demo.png`
et intégrée au dossier PDF local.

1. Arrêter l'ancien serveur avec Ctrl+C, puis lancer `.\.venv\Scripts\python medbox.py`.
2. Ouvrir `/board` ou `/ship`, choisir un patient et consulter son historique sous la fiche.
3. Avec Ollama disponible, demander une analyse, répondre à une question et relancer l'analyse. L'enregistrement est visible immédiatement ; le contenu généré par un vrai modèle doit être évalué séparément.
4. Lancer `false-alarm` : température élevée seule, aucune isolation attendue. Lancer `slow-burn` : aggravation progressive sur dix minutes.
5. Lancer `.\.venv\Scripts\python -m pytest tests/ -q`.

## Limites explicites

Les données de démonstration sont simulées. Les contacts enregistrés indiquent uniquement une présence commune en zone de quarantaine : ce n'est pas un suivi de proximité dans le vaisseau. Les affectations actives ne sont pas restaurées au redémarrage ; les historiques sont conservés. Reset remet la simulation à zéro et termine les contacts en cours. La durée d'isolement est une règle de démonstration, sans validation clinique. Le score est partiel, sans pression artérielle ; les hypothèses IA ne constituent pas un diagnostic. Les tests avec simulateur vérifient le transport des informations, pas la qualité d'un vrai modèle médical.

## Fichiers à comprendre

`server/db.py` gère les requêtes SQL paramétrées et la persistance. `server/app.py` valide les réponses, expose les API et construit le contexte IA. `server/quarantine.py` contient les règles déterministes. `web/patient-record.js` partage les formulaires et courbes entre les deux vues. `tests/test_dev2.py` couvre les cas de stockage, d'injection, de reprise et de simulation.
