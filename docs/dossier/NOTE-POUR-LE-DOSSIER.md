# Le dossier et la présentation de l’équipage

Le dossier technique et la présentation remis le 24 septembre 2026 sont générés
depuis le dépôt, à partir du code et des derniers résultats de tests :

```powershell
.\.venv\Scripts\python toolsuild_dossier.py     # PDF, 18 pages, deux parties
.\.venv\Scripts\python toolsuild_deck.py        # PPTX, 10 diapositives
```

Les fichiers sortent dans `.build\deliverables\` (ignoré par Git) ; les captures
d’écran utilisées sont dans `.build\deliverables\shots\`. Structure : l’équipage
et ses deux solutions ; partie A, MedBox (1A, Eddy et Brad) ; partie B, ARIA /
PsychoSpace (1B, Davidson, Anthony, Frederic, Merove), dossier de l’équipe 1B
repris tel quel ; organisation, conclusion, références.

La note ci-dessous est l’état de MedBox au 24 septembre à 13 h 15, telle qu’elle
a servi à écrire la partie A. Elle reste utile pour les chiffres et le déroulé de
démonstration.

---

## 1. Corrections à faire dans le dossier du 23 septembre

| Où | Ce qui est écrit | Ce qu'il faut écrire |
|---|---|---|
| p. 1, équipe | « Brad, Eddy, Davidson, Junior, Anthony, Mérovée » | Les six membres, tels qu'ils apparaissent dans la station : **Eddy** (commandant de bord), **Brad** (ingénieur de vol), **Davidson** (systèmes), **Anthony** (navigation), **Frederic** (communications), **Merove** (secouriste). Vérifier « Junior » / « Frederic » et l'orthographe « Mérovée » / « Merove » avec les intéressés, puis mettre la même orthographe partout (PDF, PPTX, station). |
| p. 1, périmètre | « Deux interfaces web » | **Quatre pages** (vaisseau 3D, tableau 2D, tableau de bord équipage, espace personnel) et **sept serveurs** : la station principale et six espaces personnels, un port par membre. |
| p. 2, hors ligne | « Les fonctions de reconnaissance vocale dépendent d'un modèle local optionnel » | La voix est **livrée dans le bundle**, dans les deux sens : reconnaissance (faster-whisper, FR + EN) et synthèse (Piper, une voix française et une voix anglaise). Rien n'est optionnel ni téléchargé au lancement. |
| p. 3, quarantaine | « La sortie exige au moins 120 secondes […] deux observations complètes » | **La sortie d'isolement est une décision humaine** (`release_policy: manual_only`). La règle des 120 secondes a été écrite puis volontairement non retenue : un test la marque comme non attendue (`xfail`). L'isolement est proposé par la station, confirmé et levé par une personne. |
| p. 5, répartition | « Dev 2 » | **Brad**, partout (tableau de répartition, sources). Toutes les occurrences « Dev 2 » du dépôt ont été remplacées par « Brad » le 24 septembre. |
| p. 5, limites | « Les affectations actives de quarantaine ne sont pas rechargées au redémarrage » | Exact, mais à compléter : au premier cycle après redémarrage, une personne encore en alerte est **re-proposée** à l'isolement ; réponses, historique de priorité, contacts, messages et préférences sont **conservés** (SQLite). |
| p. 5, validation | « tools/fake_ollama.py […] pas la pertinence d'un vrai modèle » | Le vrai modèle (`qwen2.5:1.5b-instruct`, Ollama 0.13.1) est **livré dans le bundle** et a été testé sur la machine de soutenance : réponse en 24 à 31 secondes sur ce portable, sans réseau. |
| p. 5, capture | Capture anglaise (« Run », « Reset », « AI narration ») | Refaire la capture : l'interface est entièrement en français depuis le 23 septembre. |
| partout | « assistance conversationnelle » | Le terme retenu dans le produit est **« le référent médical du bord »** (voir § 4). |

## 2. Corrections à faire dans le brouillon de présentation

| Diapositive | Ce qui est écrit | Ce qu'il faut écrire |
|---|---|---|
| 1 | « Brad · Eddy · Davidson · Junior · Anthony · Mérovée » | Même liste que ci-dessus, même orthographe que dans la station. |
| 2 | « Historique et aide textuelle locale » | « Historique, référent médical du bord (texte **et voix**), espaces personnels ». |
| 2 | « aucune mesure réelle ni diagnostic médical » | « aucune mesure réelle ; dans la simulation, le référent nomme ce que les mesures montrent et décide des isolements, il ne prescrit rien ». |
| 3 | « 1. Lancer le scénario 2. Ouvrir un patient 3. Lire courbe, réponses et quarantaine » | Suivre le déroulé de démonstration du § 8 (voix, message, carte, vaisseau, espace personnel). |
| 4 | « Ma contribution Dev 2 » / « Contribution du collaborateur » | « Contribution de Brad » / « Contribution d'Eddy », puis les autres membres (§ 6). |
| 5 | « 150 tests réussis », « 3 scénarios » | **407 tests réussis** (3 ignorés, 1 échec attendu), **9 scénarios**. |

---

## 3. Ce qui est fait (vérifié le 24 septembre à 10 h 30, sur le bundle lui-même)

### 3.1 Surveillance (chemin rapide, sans modèle)

- 40 membres d'équipage simulés, dix mesures par seconde, score NEWS2
  déterministe (`server/triage.py`), priorité routine / faible / moyenne / haute.
- Proposition d'isolement automatique, **confirmation et levée humaines**,
  zones du vaisseau avec places, registre des contacts (qui a partagé une zone
  avec qui, et quand), tout persisté.
- Vue 3D du vaisseau (`/ship`) et tableau 2D (`/board`), alimentés par le même
  flux WebSocket ; l'absence du modèle n'arrête jamais l'affichage.
- Neuf scénarios reproductibles en français, écrits en écarts par rapport à la
  ligne de base personnelle de chacun : `contamination`, `single-patient`,
  `slow-burn`, `false-alarm`, `baisse-thermique`, `effort-prolonge`,
  `exposition-environnementale`, `gene-respiratoire`, `signes-pseudo-grippaux`.

### 3.2 L'équipage, c'est nous

- Les six premiers membres (P-01 à P-06) sont **l'équipe**, avec des lignes de
  base personnelles et **une semaine de mesures stockée en base** (SQLite,
  `seed_week`).
- **Tableau de bord équipage** (`/crew`) : statistiques de la semaine, état de
  chacun aujourd'hui, messages du référent, zones du vaisseau, activités de
  groupe du jour, et **le membre en forme cette semaine** (celui dont la
  semaine est restée la plus proche de sa ligne de base) avec ses habitudes à
  suivre.
- **Espace personnel** (`/me/{id}`) pour chaque membre, **chacun sur son propre
  port** (8771 à 8776, ouverts au lancement avec la station) : le référent sait
  à qui il parle, se présente, lit l'évaluation à la deuxième personne, répond
  aux questions, affiche la semaine, les activités personnelles, les messages,
  le dossier patient et le vaisseau embarqué centré sur la personne.
- Chaque membre peut **nommer son assistant** ; ce nom devient son mot de
  réveil vocal (avec « MedBox »).
- Une navigation commune sur toutes les pages (tableau, vaisseau, équipage,
  et les six espaces personnels avec leur port).

### 3.3 Le référent médical du bord (chemin lent)

- Modèle local `qwen2.5:1.5b-instruct` via Ollama, réponses **contraintes par
  schéma JSON** puis passées par un validateur : aucun médicament, aucune
  dose, aucune maladie inventée que les mesures ne montrent pas ; liste des
  refus dans `server/ai/capabilities.py`.
- Persona : dans la simulation, il n'y a pas de médecin à bord ; le référent
  **nomme ce que les mesures montrent, décide l'isolement, le dit à la
  personne et prévient l'équipage**. Il ne se présente jamais comme « pas un
  médecin » ; il ne prescrit rien.
- **Mode texte** : une question libre depuis n'importe quelle page
  (`/api/assistant/ask`), réponse courte (≤ 280 caractères), ancrée dans les
  mesures, en français ou en anglais ; à la deuxième personne sur un espace
  personnel. Les questions sur l'isolement et sur l'état de l'équipage sont
  répondues **par la station elle-même, en quelques millisecondes**, à partir
  de ses registres ; le modèle ne peut pas inventer un isolé. Quand la réponse
  prend du temps, le référent dit « un instant, je regarde les constantes ».
- **Messages** : à chaque décision d'isolement, un message à la personne et un
  message au tableau de bord équipage, avec **signal sonore fort** ; « Lire »
  ouvre la **carte de la personne** avec le vaisseau 3D et la **zone
  d'isolement qui s'illumine**, et le message est **lu à voix haute**.
- Le dossier patient de Brad, fusionné le 24 septembre : réponses persistées
  (Oui / Non / Incertain / texte libre, sur toutes les pages), historique des
  changements de priorité, contacts, sessions, courbes des dix dernières
  minutes.

### 3.4 La voix, dans les deux sens, hors ligne

- **Consentement** lu à voix haute, accepté à la voix en français ou en anglais
  (« j'accepte », « oui », « I accept », « yes ») ; refus prioritaire ; rien de
  l'audio n'est conservé.
- Après consentement, le référent demande la **langue préférée**, puis écoute
  en continu ; réveil sur « MedBox » ou sur le nom donné à l'assistant.
- Reconnaissance : faster-whisper base, FR + EN. Synthèse : Piper, voix
  `fr_FR-siwis-medium` et `en_US-lessac-medium`, 64 phrases pré-rendues et
  rendu à la demande pour tout le reste (évaluations, réponses, messages).
- Le micro est présent sur **toutes** les pages : vaisseau, tableau, équipage et
  chaque espace personnel.

### 3.5 Qualité et tests

- **407 tests réussis, 3 ignorés, 1 échec attendu** (la levée automatique
  d'isolement, volontairement non retenue), 73 secondes, le 24 septembre à 13 h.
- Tests de bout en bout sur la station réelle (HTTP + WebSocket) et
  vérifications dans le navigateur (pages, menu, micro, carte, vaisseau
  embarqué).
- Un manifeste de capacités (`server/ai/capabilities.py`) et un test
  d'honnêteté du guide : le guide utilisateur ne peut pas promettre ce que le
  code ne fait pas.

### 3.6 Autonome, sans réseau

- **Bundle `MedBox-Portable`** : 1,6 Go, 3 790 fichiers vérifiés par SHA-256,
  lanceur `MedBox.exe`, Python 3.11 embarqué, Ollama et le modèle embarqués,
  modèles de reconnaissance et de synthèse vocales embarqués, aucun accès
  réseau.
- Lancement à froid mesuré le 24 septembre : **station prête en 9 secondes**,
  modèle chaud en moins d'une minute, six espaces personnels ouverts avec la
  station.
- Le bundle est sur le PC d'Eddy et sur la clé USB (copie vérifiée fichier par
  fichier). Outils livrés avec : `tools/preflight.ps1` (contrôle avant la
  soutenance), `tools/assistant.ps1` (arrêter / relancer le modèle pour la
  démonstration du « moment de panne »).

### 3.7 Documentation

`README.md`, `packaging/README.md` et `LISEZ-MOI.txt`, `docs/COMPRENDRE-MEDBOX.md`
(explication pour non-techniciens, y compris « Il se prend pour un médecin ? »),
`docs/USER_GUIDE.md` (généré depuis le manifeste de capacités), `docs/pitch.md`,
`docs/DEV2_DELIVERY.md` (livraison de Brad), `CLAUDE.md` (passation technique).

---

## 4. Ce qui est en cours ou pas fait (à dire honnêtement)

- **Aujourd'hui** : le dossier PDF et la présentation (cette note sert à les
  compléter), la vidéo de démonstration si demandée.
- **Vitesse du modèle** : 24 à 31 secondes par réponse sur ce portable
  (processeur seul). Le chemin rapide n'attend jamais le modèle ; l'évaluation
  est préchargée quand c'est possible.
- **Matériel (D3)** reporté : aucun capteur réel, aucun étalonnage ; toutes les
  mesures sont synthétiques et le disent.
- Les contacts enregistrés ne prouvent pas une contamination ; les affectations
  d'isolement sont re-proposées, pas rechargées, après un redémarrage.
- Le micro demande l'autorisation du navigateur à chaque session (c'est le
  navigateur, pas nous).
- Statut : prototype de simulation. Il ne constitue pas un dispositif médical
  validé et ne doit pas servir à décider de soins réels.

---

## 5. Chiffres à reprendre tels quels

| Donnée | Valeur |
|---|---|
| Membres d'équipage simulés | 40 (dont 6 = l'équipe) |
| Pages | 4 (vaisseau, tableau, équipage, espace personnel) |
| Serveurs au lancement | 7 (station 8765 + espaces personnels 8771 à 8776) |
| Scénarios | 9 |
| Tests | 407 réussis, 3 ignorés, 1 échec attendu |
| Modèle | qwen2.5:1.5b-instruct, Ollama 0.13.1, processeur seul |
| Voix | faster-whisper base (FR + EN) ; Piper fr_FR-siwis-medium + en_US-lessac-medium |
| Bundle | 1,6 Go, 3 790 fichiers, SHA-256 vérifié, lancement en 9 s |
| Réponse du référent | 24 à 31 s par question sur le portable de soutenance |

---

## 6. Répartition (à compléter par l'équipe)

| Responsable | Périmètre |
|---|---|
| Eddy | Direction du projet ; vues 2D/3D ; référent médical (modèle, schémas, validateur, persona) ; voix dans les deux sens ; équipage et espaces personnels ; messages et cartes ; bundle autonome ; tests et documentation. |
| Brad | Dossier patient persistant (réponses, historique de priorité, contacts, sessions) ; scénarios `slow-burn` et `false-alarm` ; règles de quarantaine ; dossier technique du 23 septembre. |
| Davidson | *à compléter* |
| Anthony | *à compléter* |
| Frederic | *à compléter* |
| Merove | *à compléter* |
| Intégration commune | API, affichage partagé, non-régression (fusion du 24 septembre). |

---

## 7. Paragraphes prêts à coller

**Périmètre réalisé.** MedBox est une station médicale locale pour un
équipage de quarante personnes sans médecin à bord. Elle mesure (simulation),
priorise (NEWS2, règles explicites), décide et explique (référent médical du
bord, modèle local sous contrainte), et parle (reconnaissance et synthèse
vocales hors ligne). Elle se présente en quatre pages et sept serveurs : la
station et un espace personnel par membre de l'équipe. Elle est livrée sous
forme d'un dossier autonome de 1,6 Go qui se lance en neuf secondes sans réseau.

**Deux chemins.** Le chemin de surveillance (mesures, score, isolement,
affichage) n'importe jamais le module d'intelligence artificielle et
n'attend jamais le modèle. Le chemin de conversation (questions, réponses,
évaluations, messages) passe par un schéma JSON et un validateur qui
interdisent toute prescription et toute maladie non montrée par les mesures.
Les réponses du patient n'entrent pas dans le calcul du score.

**Le référent médical du bord.** Dans la simulation, il n'y a pas de médecin :
le référent nomme ce que les mesures montrent, décide l'isolement, le dit à la
personne concernée, prévient le tableau de bord de l'équipage par un message
sonore et lit ce message à voix haute. Il ne prescrit aucun médicament.

**L'équipage, c'est nous.** Les six premiers membres sont l'équipe, avec une
semaine de mesures en base. Le tableau de bord équipage montre les statistiques
de la semaine, l'état de chacun, les activités du jour et le membre en forme
dont les habitudes sont proposées aux autres. Chaque membre a son espace
personnel sur son propre port, où le référent le reconnaît, se présente, lui
lit son évaluation et répond à ses questions ; chacun peut nommer son
assistant, et ce nom devient son mot de réveil.

**Validation.** 407 tests réussis (3 ignorés, 1 échec attendu) le
24 septembre, dont des tests de bout en bout sur la station réelle et un test
d'honnêteté du guide. Le bundle a été lancé à froid sur la machine de
soutenance : station prête en neuf secondes, modèle, oreilles et voix
disponibles, six espaces personnels ouverts, 3 790 fichiers vérifiés par
SHA-256 sur le PC et sur la clé USB.

**Limites.** Aucun capteur réel ni étalonnage ; le modèle répond en 24 à
31 secondes sur un processeur seul ; les contacts enregistrés ne prouvent pas
une contamination ; la levée d'isolement est une décision humaine. Le
prototype ne constitue pas un dispositif médical validé.

---

## 8. Déroulé de démonstration (cinq minutes, vendredi)

1. Double-clic sur `MedBox.exe` : la station s'ouvre dans le navigateur en
   neuf secondes (tableau 3D du vaisseau). Le référent se présente à voix
   haute ; consentement micro dit à la voix (« j'accepte »), choix de la
   langue.
2. Menu **Navigation** → **Équipage** : la semaine de l'équipe, le membre en
   forme et ses habitudes, les activités du jour.
3. Scénario **contamination** : six membres se dégradent ; propositions
   d'isolement ; **message sonore** sur le tableau équipage ; **Lire** →
   carte de la personne, vaisseau 3D, zone d'isolement qui s'illumine, message
   lu à voix haute.
4. Espace personnel d'un membre (port 8771 à 8776) : le référent le reconnaît,
   lit son évaluation à la deuxième personne ; question à la voix (« MedBox,
   est-ce que je vais bien ? ») ou au clavier ; réponse parlée.
5. Le moment de panne : `tools\assistant.ps1 stop` ; la surveillance
   continue, l'écran le dit ; `start` ; le référent revient.

Avant de commencer : `tools\preflight.ps1` (ports libres, modèle, voix).

---

## 9. Sources dans le dépôt

`server/app.py` (routes `/api/crew/week`, `/api/me/{id}`, `/api/messages`,
`/api/assistant/ask`, `/api/voice/say`), `server/spoken.py`, `server/tts.py`,
`server/voice.py`, `server/activities.py`, `server/personal.py`,
`server/ai/schemas.py`, `server/ai/validate.py`, `server/ai/capabilities.py`,
`server/db.py`, `server/quarantine.py`, `web/crew.*`, `web/me.*`, `web/mic.js`,
`web/voice.js`, `web/nav.js`, `web/patient-record.js`, `scenarios/*.yaml`,
`tests/` (407 tests), `tools/build-portable.ps1`, `packaging/`.
