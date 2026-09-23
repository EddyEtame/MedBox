# Comprendre MedBox

*De quoi la station est faite, pourquoi elle est faite ainsi, et comment on le
prouve. Écrit le 24 septembre 2026 pour pouvoir l'expliquer à quelqu'un qui ne
l'a jamais vue. Tout ce qui est affirmé ici est vérifiable dans le dépôt ; les
chiffres ont été mesurés sur le portable de démonstration (i7-1255U, sans GPU).*

---

## 1. Le problème en une phrase

Quarante personnes à bord de l'ESA Horizon, six mois sans contact avec la
Terre, pas de médecin. Le jour où six d'entre elles tombent malades en même
temps, il faut décider **qui voir en premier, qui isoler, et sur quelle base**,
avec un équipage qui n'est pas formé et un ordinateur qui peut tomber en panne.

MedBox est la « mallette médicale intelligente » (option A du pilier
HumanTech & HealthTech du workshop *Horizon 2080*) : une station locale, sans
internet, sans compte, sans nuage, qui mesure, classe, propose et parle, et
qui **continue de fonctionner quand son intelligence artificielle est morte**.

## 2. La décision d'architecture, celle qui répond à presque toutes les questions

Il y a deux voies dans la station, et elles ne se touchent pas.

**La voie rapide** : capteurs → score clinique → écran. Dix fois par seconde.
Aucun modèle de langage n'y participe. C'est du code déterministe : les mêmes
mesures donnent toujours le même score, le même ordre, la même proposition
d'isolement.

**La voie lente** : le modèle de langage local (l'« assistant ») lit ce que
la voie rapide a déjà décidé et propose des hypothèses, des questions à poser,
des mesures à refaire. Il met vingt à trente secondes. Il a le droit de
tomber en panne : la voie rapide ne s'en aperçoit même pas.

Pourquoi ? Parce qu'une station de triage n'est pas une fenêtre de discussion.
Quand quinze pour cent de l'équipage est à terre, personne ne tape des
questions à un chatbot. Et parce qu'un modèle de langage, quel qu'il soit, se
trompe parfois avec assurance : il ne doit jamais être entre une mesure et la
personne qui la lit.

Cette règle est **imposée par des tests**, pas seulement écrite :

- en Python, rien dans `server/triage.py`, `server/sensors/` ou `server/db.py`
  n'a le droit d'importer `server/ai/` ; un test le vérifie à chaque exécution ;
- dans le navigateur, chaque appel vers la voix ou le micro est gardé par un
  `if`, parce qu'un fichier manquant n'est pas une erreur d'import en
  JavaScript mais une exception au milieu du traitement des messages, qui
  **figerait le tableau avec des chiffres plausibles dessus** : la pire panne
  possible. Un test refuse tout appel non gardé.

## 3. Ce que la station mesure, et comment elle classe

Le score est **NEWS2** (*National Early Warning Score 2*, Royal College of
Physicians, 2017), le standard britannique de détection de la dégradation
clinique. Nous n'avons rien inventé : c'est ce qu'utilisent les hôpitaux, et
c'est défendable devant un jury.

Sept paramètres, chacun noté de 0 à 3 :

| Paramètre | D'où il vient dans MedBox |
|---|---|
| Fréquence respiratoire | instrument (simulé) |
| Saturation en oxygène (SpO2) | instrument (simulé) |
| Pouls | instrument (simulé) |
| Température | instrument (simulé) |
| Tension artérielle systolique | instrument (simulé, le brassard) |
| Conscience (échelle ACVPU : Alerte, Confusion nouvelle, Voix, Douleur, Inconscient) | observée par une personne, saisie dans le dossier |
| Oxygène d'appoint | observé par une personne, saisi dans le dossier |

La somme donne la bande : **0 à 4 routine, 5 à 6 moyenne, 7 et plus haute**.
Un seul paramètre à 3 fait passer en bande moyenne même si le total est bas
(règle officielle dite du « single parameter 3 »). Chaque résultat porte la
liste de ce qui a été **réellement mesuré** ; s'il manque des paramètres,
l'étiquette dit « dépistage partiel dérivé de NEWS2 » et non « NEWS2 ». Un
paramètre absent n'est jamais compté comme normal en silence.

Quand les sept paramètres sont là, l'étiquette devient « NEWS2 complet, sept
paramètres ». C'est ce qu'on montre en saisissant une confusion nouvelle sur
un membre d'équipage : le score change à l'instant.

## 4. Les données : d'où viennent les chiffres

Il n'y a pas de capteurs réels pour la soutenance (le matériel arrive après).
Tout est **synthétique, et dit l'être** : un bandeau à l'écran l'affiche en
permanence, et l'horloge est accélérée (quatre minutes simulées par seconde
réelle ; quatre-vingt-dix secondes de démonstration représentent jusqu'à six
heures de surveillance).

- Chaque membre d'équipage a une **ligne de base saine** dans une base SQLite
  locale, dérivée de façon déterministe de son identifiant (profil de
  référence versionné « healthy-adult-reference-v2 »). Deux lancements donnent
  les mêmes lignes de base.
- Les mesures simulées sont des **écarts par rapport à cette ligne de base**,
  jamais des valeurs inventées de toutes pièces ; chaque lecture enregistre sa
  provenance.
- Les **scénarios** (`scenarios/*.yaml`) décrivent une crise : quel groupe,
  quels écarts, à quel moment. Celui de la démonstration, « Alerte respiratoire
  à bord », rend malades six personnes sur quarante, avec une exposition
  confirmée à un risque respiratoire non identifié.
- Des **boutons de simulation** dans le dossier permettent de pousser une
  mesure à la main, dans des limites bornées (on ne peut pas mettre une
  température de 60 °C).

Pourquoi un scénario plutôt que du direct ? Parce qu'une répétition rejouable
ne peut pas vous ridiculiser devant un jury, et que du matériel réel le peut.

## 5. L'isolement : la station propose, une personne décide

La règle est simple et lisible : **fièvre, plus désaturation ou respiration
accélérée**. Quand elle est vraie, la station annonce à voix haute
« Isolement proposé. Confirmation humaine requise. » avec le nom de la
personne, et la place dans une liste « à confirmer ».

- Personne n'est mis en quarantaine automatiquement ; c'est un clic humain.
- Une zone est **scellée dès le premier occupant** ; sa capacité ne gouverne
  que les nouvelles entrées.
- Quand il n'y a plus de place, la personne est « en attente d'un lit », en
  rouge sur les deux vues, jamais oubliée.
- **Aucune levée automatique** : sortir quelqu'un de l'isolement est aussi un
  geste humain.

## 6. L'assistant : ce qu'il peut faire, et surtout ce qu'il ne peut pas

Le modèle est **qwen2.5 1,5 milliard de paramètres, version instruct**,
servi par **Ollama** en local, sur le processeur seul. Il est sous licence
Apache-2.0 (le modèle de 3 milliards de la même famille ne l'est pas, ce qui
est une raison de ne pas l'avoir choisi). Il tourne sur un portable ordinaire.

Il ne répond **jamais en texte libre**. Il décode sous une **grammaire** (un
schéma JSON strict) qui ne contient que ces champs :

- deux hypothèses au maximum, nommées d'après les instruments (« Fièvre avec
  désaturation »), jamais d'après une maladie ;
- deux signes au maximum, chacun citant l'instrument qui l'a mesuré ;
- une question à poser au patient ;
- une mesure à refaire ;
- un résumé de moins de quinze mots.

Il n'existe **aucun champ** pour un diagnostic, un médicament, une dose ou un
niveau d'urgence : il ne peut pas les écrire, parce que la grammaire ne les
accepte pas. Et par sécurité, un **validateur** reconstruit la réponse à
partir des clés du schéma (ce que le modèle aurait inventé ne peut pas
passer), supprime tout mot de médicament, de voie d'administration ou de
maladie, renomme une hypothèse qui ne suit pas le motif attendu, et retire
un signe qui cite un paramètre pourtant normal. Ce qui a été supprimé est
affiché comme supprimé : la station ne cache pas qu'elle a corrigé le modèle.
Cela a été vérifié contre un faux Ollama volontairement malveillant
(`tools/fake_ollama.py --rogue`).

### Les chiffres qu'il faut connaître

| | |
|---|---|
| Une évaluation, modèle chaud | 18 à 36 s ; plafond du clic : 40 s |
| Clic sur un membre déjà **préparé** | 1 à 2 s depuis le dépôt ; 0,03 s mesuré depuis le dossier portable |
| Génération | 14 à 15,5 jetons par seconde |
| Préchauffage au démarrage | 40 s (chargement 7 s, évaluation du préambule 33 s) |

Le secret du clic rapide s'appelle **préparation anticipée** : dès qu'un score
monte, la station demande l'évaluation en arrière-plan et la garde en cache.
Quand la personne clique, la réponse est déjà là, datée (« Préparée il y a
N s, avant la demande »). Une réponse en cache n'est réutilisée que si le
score NEWS2 n'a pas changé et qu'elle a moins de trois minutes.

Deux détails qui comptent : tous les appels au modèle utilisent **le même
préambule système**, parce qu'Ollama garde en cache le préambule déjà évalué
et qu'un préambule différent le fait recalculer (quinze secondes de perdues) ;
et un modèle **lent n'est pas un modèle mort** : un dépassement de délai ne
fait pas annoncer « l'assistant s'est arrêté », seule la sonde de présence le
fait.

## 7. Ce qu'il apprend

Les commandes vocales ou tapées (« montre-moi le plus malade », « scelle la
zone A ») sont d'abord résolues **sans modèle** :

1. une liste blanche de commandes explicites ;
2. le **carnet de formulations apprises** (base SQLite) ;
3. un **lexique** par intention, français et anglais : un seul candidat →
   résolu ; aucun → refusé ;
4. le modèle n'arbitre que s'il reste **plusieurs** candidats, et il ne peut
   choisir que parmi eux (grammaire à choix fermé, huit secondes maximum).

Une formulation résolue par le modèle est retenue : la fois suivante elle est
déterministe, sans modèle. Le panneau Aide montre « Ce que MedBox a appris »,
et chaque ligne s'oublie d'un clic. Une leçon donnée par l'opérateur n'est
jamais écrasée par le modèle. Mesuré : 0,4 à 0,8 s quand le lexique suffit,
4,4 s quand le modèle arbitre.

## 8. La voix, dans les deux sens, sans rien envoyer nulle part

**Sortie** : cinquante-neuf phrases françaises pré-enregistrées avec la voix
Piper `fr_FR-siwis-medium` (licence CC BY 4.0), livrées dans le dépôt. Le
portable de démonstration n'a besoin d'aucun moteur de parole. Ce que la voix
dit est **écrit par nous**, jamais par le modèle. Chaque clip a été
retranscrit par la station elle-même pour vérifier qu'il se comprend à l'oral
(c'est ainsi qu'on a découvert que « MedBox » se disait mal et qu'il fallait
écrire « Med Box »).

**Entrée** : reconnaissance par `faster-whisper` (modèle *base*), en local.
Pas l'API de reconnaissance vocale du navigateur, qui envoie le son chez
Google et annulerait toute la promesse « hors ligne ».

**Consentement** : au premier clic, la station se présente, dit ce qu'elle ne
fera jamais, et demande si elle peut écouter. On répond **à voix haute**
(« j'accepte », « oui », « accept », « yes »). Ensuite elle écoute en continu,
réagit au mot « MedBox », et **ne conserve aucun son**.

## 9. La mort de l'assistant, en direct

C'est le moment central de la démonstration. On arrête Ollama devant le jury
(`tools\assistant.ps1 stop`). Dans les cinq secondes, la sonde de présence le
voit, la voix dit « L'assistant s'est arrêté. Les mesures continuent. », et :

- les constantes bougent toujours, le score et l'ordre aussi ;
- les propositions d'isolement continuent ;
- un clic sur « Demander à l'assistant » rend **la réponse conservée**, datée,
  avec la mention que l'assistant est arrêté ;
- le manuel d'utilisation, qui est normalement narré par le modèle, est rendu
  tel quel par la station, parce que les faits appartiennent à la station et
  que le modèle n'est que la voix qui les lit.

Puis on peut le relancer (`tools\assistant.ps1 start`) : il revient en une
seconde, et la station le remarque dans les cinq suivantes.

## 10. Le dossier portable : « double-clic et ça marche »

Le livrable est un dossier de 1,5 Go qui tient sur une clé USB :

- `MedBox.exe`, un lanceur .NET autonome, qui trouve un port libre, démarre
  son propre Ollama sur le port 11555 et son propre Python, ouvre le
  navigateur, et arrête ses enfants quand on ferme la fenêtre ;
- un Python 3.11 embarqué, lancé de façon isolée pour ne jamais importer ce
  qui serait installé sur la machine hôte ;
- le moteur Ollama (processeur seul) et **uniquement** les fichiers du modèle
  configuré ;
- le modèle de reconnaissance vocale ;
- un manifeste et une liste SHA-256 de chaque fichier, pour vérifier n'importe
  quelle copie.

Il a été lancé **à froid** le 23 septembre : depuis un chemin contenant un
espace, avec le PATH réduit à `C:\Windows`, sans Python ni Ollama accessibles.
Station prête en moins de 25 s, assistant préchauffé à 40 s, aucune connexion
réseau hors de la machine, kill et relance vérifiés depuis le dossier.

## 11. Comment on prouve tout cela

- **346 tests** (`python -m pytest tests/ -q`), dont des tests « gardiens »
  que l'on a regardés échouer avant de les croire : on casse la chose, on
  lance le test, on vérifie qu'il est rouge, on répare.
- Le **guide utilisateur** (`docs/USER_GUIDE.md`) est **généré** à partir du
  code (`tools/guide.py`) ; un test échoue s'il diverge de la réalité.
- Le validateur du modèle est testé contre un faux modèle malveillant.
- `tools\preflight.ps1` vérifie la machine avant de projeter : port, version
  d'Ollama, modèle, clips, modèle vocal, dossier portable, et ce qui
  interrompt une démonstration (réseau, notifications, alimentation).
- Le dossier portable a un mode `Check` (tous les SHA-256) et un mode `Smoke`.

## 12. Les limites, dites avant qu'on nous les oppose

- Données synthétiques ; les capteurs réels arrivent après la soutenance
  locale. Le plan n'a jamais été une marque de montre, mais n'importe quel
  appareil parlant les profils de santé Bluetooth standard.
- Prototype de recherche et d'enseignement : **pas un dispositif médical**, il
  ne pose pas de diagnostic.
- NEWS2 est un score de **dégradation**, pas de contagion : la règle
  d'isolement est la nôtre, simple, et confirmée par une personne.
- Un modèle de 1,5 milliard de paramètres reste petit : c'est pour ça qu'il
  n'a aucune autorité et qu'on peut le tuer.
- Le microphone réel n'a été essayé qu'avec de l'audio synthétisé avant le
  24 septembre ; les cartes de protocole sont simulées et fermées par défaut.

## 13. Les questions qu'on nous posera

**Pourquoi pas un chatbot médical ?** Voir le point 2 : le score, l'ordre et
l'isolement sont calculés sans modèle ; le modèle propose et peut mourir sans
rien casser. On l'a montré.

**Pourquoi un si petit modèle, et pourquoi Ollama ?** Parce qu'il doit tourner
sur un portable sans carte graphique, sans réseau, sous une licence qui
permet de le redistribuer. Ollama est le moteur local le plus simple à
embarquer et il sait décoder sous grammaire, ce qui est la base de toute la
sécurité du point 6.

**Comment lui faire confiance médicalement ?** On ne lui fait pas confiance,
et l'architecture le dit : pas de champ pour un diagnostic ni un traitement,
hypothèses renommées d'après les instruments, tout ce qui ressemble à une
dose ou à une maladie supprimé et affiché comme supprimé.

**Et si un capteur ment ?** Chaque score porte ce qui a été mesuré et ce qui
est supposé ; une valeur invraisemblable reste une valeur d'un instrument,
pas un fait : la personne devant l'écran décide, et c'est pour ça que
l'isolement se confirme à la main.

**Pourquoi NEWS2 et pas un score maison ?** Parce qu'un score maison n'est
défendable devant personne, et que NEWS2 est enseigné, publié, et connu de
tout soignant.

**Où vont les données ?** Nulle part. Base SQLite locale, aucun son conservé,
aucune connexion sortante (vérifié au lancement à froid).

**Et si la base se corrompt ?** Les lignes de base se re-dérivent de
l'identifiant, les mesures continuent de s'afficher ; on perd l'historique,
pas la capacité de trier.

**Que ferait-on avec plus de temps ?** Les capteurs Bluetooth réels, la
détection de toux, le traçage des contacts entre membres d'équipage, une vue
téléphone pour la personne qui se déplace dans le vaisseau.

## 14. Glossaire

- **NEWS2** : score d'alerte précoce du Royal College of Physicians (2017).
- **ACVPU** : échelle de conscience (Alerte, Confusion, Voix, Douleur,
  Inconscient).
- **SpO2** : saturation en oxygène du sang, en pourcentage.
- **Ollama** : programme qui fait tourner un modèle de langage en local.
- **Grammaire / schéma** : la liste fermée des champs que le modèle a le droit
  de remplir ; tout le reste est physiquement impossible à produire.
- **Voie rapide / voie lente** : mesures et score sans modèle / propositions
  du modèle, qui peuvent être en retard ou absentes.
- **Préparation anticipée** : l'évaluation demandée en arrière-plan avant le
  clic.
- **Ligne de base** : les constantes habituelles d'une personne en bonne
  santé, contre lesquelles on lit les écarts.
