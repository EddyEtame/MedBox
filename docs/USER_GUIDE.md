<!-- Généré par tools/guide.py à partir du produit. Ne pas modifier à la main : exécuter `python tools/guide.py`, sinon la prochaine génération écrasera les changements. -->

# MedBox — guide de l’opérateur

**ESA Horizon · 40 membres · aucun médecin à bord · aucun contact avec la Terre.**

> **MedBox est un prototype de recherche et de formation. Ce n’est pas un dispositif médical et il ne pose aucun diagnostic.** La priorité affichée est un dépistage partiel dérivé de NEWS2. L’assistant ne fait que proposer des hypothèses traçables ; il ne prescrit rien et ne peut jamais modifier le score.

## 1. Comprendre l’architecture

MedBox fonctionne sur deux voies séparées.

La **voie rapide** lit les capteurs ou la simulation, compare chaque personne à sa ligne de base, calcule le score et met l’interface à jour. Aucun modèle de langage n’intervient dans ce circuit.

La **voie lente** est l’assistant local. Il résume, suggère des hypothèses et formule des questions. Il peut être lent, indisponible ou arrêté sans interrompre les mesures.

Si Ollama s’arrête, les constantes continuent, l’ordre de priorité reste calculé, les candidats à la quarantaine restent visibles et les isolements déjà confirmés demeurent en place. La confirmation et la levée d’un isolement restent toujours des décisions humaines.

## 2. Démarrer la station

Dans le paquet autonome Windows, double-cliquer sur l’exécutable du lanceur MedBox. Il démarre les composants locaux, attend que la station réponde, puis ouvre le navigateur. Fermer le lanceur arrête uniquement les processus qu’il a démarrés.

Depuis le dépôt de développement :

```
Windows          .\.venv\Scripts\python medbox.py
Linux / macOS    .venv/bin/python medbox.py
```

Ouvrir ensuite <http://127.0.0.1:8765>. Le port principal est `8765` ; le lanceur peut choisir un autre port si celui-ci est déjà occupé.

| Adresse | Vue | Usage |
|---|---|---|
| `http://127.0.0.1:8765/` | Console 3D du vaisseau | Présentation principale. |
| `http://127.0.0.1:8765/board` | Tableau plat, sans 3D | Secours si WebGL ou le projecteur pose problème. |

## 3. Lire la priorité NEWS2

L’équipage est classé par score décroissant afin que les écarts les plus préoccupants restent visibles. Chaque ligne affiche les quatre constantes mesurées, le total et la bande associée.

| Total dérivé de NEWS2 | Bande | Conduite indiquée par la bande |
|---|---|---|
| 0 | **nominal** | Surveillance habituelle. |
| 1–4 | **faible** | Faire revoir la personne par un professionnel compétent. |
| 5–6 | **moyen** | Revue urgente et escalade vers le responsable médical. |
| 7 ou plus | **élevé** | Réponse d’urgence et surveillance continue. |

**Règle importante :** un seul paramètre valant 3 points impose au minimum la bande **moyen**, même si le total paraît plus faible.

NEWS2 complet comporte sept paramètres. MedBox en mesure quatre : température, SpO₂, pouls et fréquence respiratoire. La pression artérielle systolique, le niveau de conscience et l’oxygène supplémentaire ne sont pas mesurés par ce prototype. L’interface affiche donc **dépistage partiel dérivé de NEWS2** et ne présente jamais ce résultat comme un NEWS2 complet.

Les voyants indiquent la connexion de l’écran, l’état de l’assistant et le scénario en cours. Un voyant d’assistant éteint ne coupe pas la voie rapide. La mention **simulateur, pas un modèle** signifie que des règles fixes répondent à la place d’Ollama.

## 4. Examiner une personne et simuler un écart

Cliquer sur un membre ouvre son dossier. Le panneau détaille chaque constante, les points attribués, la ligne de base saine personnelle et la courbe récente.

Les scénarios et les réglages manuels n’écrasent pas la ligne de base. Ils appliquent un **écart** traçable pendant une durée choisie. Le moteur calcule la trajectoire ; aucune valeur numérique n’est demandée au LLM. L’option d’exposition contagieuse est un fait de simulation saisi par l’opérateur, pas une conclusion tirée des constantes.

Toute donnée de démonstration est étiquetée comme synthétique. Elle ne doit jamais être présentée comme une mesure captée sur une personne réelle.

## 5. Activer l’écoute locale

Le navigateur impose une action physique avant d’autoriser le micro. Cliquer une fois sur **Activer MedBox**, puis accepter l’autorisation du navigateur. Cette étape ne peut pas être validée à la voix.

MedBox affiche ensuite l’avis de consentement et, si la synthèse vocale locale est disponible, le lit à haute voix. Répondre clairement **J’accepte**, **Oui**, **I accept** ou **Yes**. Une réponse négative, ambiguë ou trop peu fiable ne démarre pas l’écoute.

Après consentement, l’écoute reste active **uniquement tant que la session et la page restent ouvertes**. Dire **MedBox**, puis la demande. Le français et l’anglais sont reconnus localement. La parole ambiante sans phrase d’appel est écartée.

Aucun fichier audio n’est conservé. Avant consentement, même la transcription est supprimée ; seule la décision et son horodatage sont audités. Les boutons **Mettre en pause** et **Retirer mon accord** restent disponibles. Le retrait ferme immédiatement l’accès de MedBox au microphone pour cette session.

## 6. Déclarations et assistant

Une phrase saisie ou prononcée est enregistrée comme **déclaration**, jamais comme mesure. Elle ne change donc jamais le score.

Après sélection d’une personne, appuyer sur **Demander à l’assistant**. La réponse peut contenir :

- un résumé bref des mesures ;
- au maximum deux hypothèses, jamais un diagnostic ;
- la source de chaque signe : température, SpO₂, pouls, fréquence respiratoire, systolic_bp, déclaré par le membre, non mesuré ;
- le degré de concordance (« une mesure concorde », « plusieurs mesures concordent », « tous les paramètres mesurés concordent »), qui n’est pas une probabilité ;
- les questions à poser et les observations à recueillir.

Si les quatre mesures n’étayent aucune hypothèse, l’assistant doit le dire et peut rendre une liste vide. Une réponse devient périmée après une minute ou dès que le score change ; l’interface demande alors de la relancer.

Le schéma de sortie ne contient aucun champ de diagnostic, de priorité ou de traitement. Un garde supplémentaire supprime toute liste qui contiendrait un médicament, une dose ou une voie d’administration. Le modèle libre ne prescrit jamais.

La zone **Protocoles locaux vérifiés** suit une autre voie, entièrement déterministe. Elle cherche une carte signée, affiche ses sources officielles et n’envoie ni l’observation ni le dossier au LLM. Une option médicamenteuse issue de l’inventaire simulé reste masquée tant que l’identité, l’âge, la grossesse, les allergies, les traitements actuels, les contre-indications et les signes d’alerte ne sont pas tous vérifiés.

La dernière ouverture exige en plus une validation récente d’un clinicien, liée à la carte exacte, ainsi qu’un lot simulé actif, non périmé et en quantité suffisante. Le résultat indique la référence et son emplacement simulés, sans dose, sans diagnostic et sans administration automatique. Il s’agit d’une démonstration de garde-fous, pas d’une prescription.

Le modèle configuré est `qwen2.5:1.5b-instruct`, exécuté localement par Ollama. Une requête est abandonnée après 40 secondes ; les mesures ne l’attendent jamais.

## 7. Ajouter un rapport médical

Dans le dossier d’un membre, la zone **Rapports médicaux locaux** accepte PDF, DOCX, PNG, JPEG et TXT, avec une limite de 12 Mo. MedBox vérifie le type, attribue un nom de stockage interne, calcule une empreinte SHA-256 et conserve les métadonnées dans la base locale.

Le document peut être rouvert par l’opérateur, mais son contenu n’est ni interprété ni transmis à l’assistant. L’ajout d’un fichier ne modifie jamais le score NEWS2.

## 8. Si l’assistant s’arrête

Arrêter Ollama pendant une consultation constitue un test prévu. Le voyant IA s’éteint et une nouvelle demande signale que l’assistant est indisponible. Les mesures, les tendances, la priorisation, les simulations, les dossiers, les candidats à l’isolement et les décisions humaines continuent de fonctionner.

Le panneau d’aide reste disponible parce qu’il est rendu à partir de données détenues par la station, et non inventé par le modèle.

## 9. Quarantaine : confirmation et levée humaines

Les constantes ne prouvent jamais qu’une personne est contagieuse. Dans un exercice, un drapeau d’exposition déclaré, associé à une fièvre et à une désaturation ou une respiration élevée, crée seulement un **candidat à l’isolement**.

L’opérateur examine le dossier et appuie sur **Confirmer l’isolement**. Ce n’est qu’après cette action que MedBox affecte un lit. Un candidat non confirmé n’occupe aucune place et ne scelle aucune zone.

La configuration comporte 3 zones (A, B, C), 4 lits chacune, soit 12 places. Une zone est scellée dès le premier occupant **confirmé**. Lorsqu’elle atteint sa capacité, les nouvelles confirmations passent à la prochaine zone libre.

Lorsque les 12 places sont occupées, la personne confirmée suivante reste visible **en attente d’un lit** au lieu de disparaître du registre.

La normalisation ultérieure des constantes ne libère personne automatiquement. L’opérateur doit vérifier la situation et choisir **Lever manuellement** ; l’action est enregistrée dans la piste d’audit.

## 10. Capacités disponibles

Cette liste provient de la même source que le panneau **Aide**.

### Fonctionne même sans assistant

#### Prioriser tout l’équipage selon les mesures

Chaque membre reçoit un dépistage partiel dérivé de NEWS2, calculé à partir des cinq constantes mesurées par MedBox et des deux observations saisies. Le tableau et le vaisseau sont ordonnés selon ce score déterministe.

*Toujours actif : aucune demande à formuler.*

#### Lire à voix haute ses évaluations et ses réponses

Une voix française embarquée (Piper, hors ligne) lit le résumé d’une évaluation, ses hypothèses et sa question, ainsi que la réponse à une question tapée. Rien ne sort de la machine. Les annonces du vaisseau restent des phrases pré-enregistrées écrites par l’équipe, jamais par le modèle.

*Activer la voix (bouton haut-parleur). Si la voix embarquée manque, seules les phrases pré-enregistrées sont dites.*

#### Expliquer le calcul du score d’une personne

Après sélection d’un membre, chaque constante indique pourquoi elle a reçu ses points. MedBox distingue aussi les paramètres réellement mesurés de ceux qui sont absents ou supposés.

*Cliquer sur un membre dans l’une ou l’autre vue.*

#### Proposer une quarantaine à confirmer humainement

Une exposition déclarée par le scénario, associée à une fièvre et à une désaturation ou une respiration élevée, crée un candidat. Un humain doit confirmer l’affectation : rien n’est isolé automatiquement. Après confirmation, la zone est scellée dès son premier occupant et cesse d’accepter des arrivées quand sa capacité est atteinte. Toute personne sans place reste affichée en attente d’un lit. La levée est elle aussi manuelle.

*Ouvrir le dossier du candidat, vérifier le contexte, puis confirmer ou refuser. La libération exige une action humaine explicite.*

#### Enregistrer ce qu’un membre déclare

Le texte saisi ou prononcé est conservé comme une déclaration à vérifier. Il peut être transmis à l’assistant, mais ne modifie jamais le score NEWS2 puisqu’aucun capteur ne l’a mesuré.

*Sélectionner un membre, puis utiliser la zone « Déclarations ».*

#### Comparer chaque personne à sa ligne de base saine

Les constantes de référence sont personnelles, déjà enregistrées dans la base locale et accompagnées de leur provenance. Une simulation manuelle applique des écarts visibles à cette base ; elle ne demande jamais au modèle d’inventer une mesure.

*Sélectionner un membre, puis choisir un scénario ou saisir un écart manuel.*

#### Joindre un compte rendu médical au dossier local

MedBox accepte uniquement les formats autorisés, limite la taille, calcule une empreinte et conserve le fichier localement. Le document n’est jamais envoyé au modèle et son contenu n’est pas interprété.

*Sélectionner un membre, puis utiliser la zone « Documents médicaux ».*

#### Consulter une carte de protocole locale validée

Un moteur déterministe séparé du LLM recherche une carte signée et affiche ses sources officielles. Toute option issue de l’inventaire simulé reste masquée tant que l’identité, l’âge, la grossesse, les allergies, les traitements actuels, les contre-indications et les signes d’alerte ne sont pas vérifiés, puis validés récemment par un clinicien pour cette carte précise. Aucune dose ni administration automatique n’est fournie.

*Sélectionner un membre, choisir « Chercher une carte », puis suivre chaque contrôle humain affiché.*

#### Rester à l’écoute après un consentement explicite

Après l’autorisation du navigateur et une réponse vocale explicite, MedBox écoute localement tant que la session reste ouverte. Seule la phrase d’appel « MedBox » ouvre une demande ; la parole ambiante est écartée et aucun fichier audio n’est conservé. L’écoute peut être mise en pause ou révoquée à tout moment.

*Appuyer une fois sur « Activer MedBox », écouter l’avis, puis dire « J’accepte ».*

### Nécessite l’assistant

#### Répondre à une question tapée, à partir des faits de la station

L’opérateur tape une question (« pourquoi ce score ? », « que mesure MedBox ? »). L’assistant répond en deux phrases, uniquement à partir des faits que la station lui écrit : mesures, lignes de base, score, isolement, déclarations. Sa réponse est décodée sous un format fermé et passe le même filtre que les évaluations : pas de diagnostic, pas de médicament, pas de dose. Sans assistant, la station répond elle-même avec ces faits, et le dit.

*Dans la barre de commande du vaisseau, basculer sur « Question » ou commencer par « ? » ; sur le tableau, le champ « Question à l’assistant ».*

#### Proposer des hypothèses classées pour une personne

L’assistant lit les mesures et les déclarations de cette personne, puis propose des explications possibles. Chaque signe nomme son capteur ou reste clairement marqué comme déclaré et non mesuré. Il ne diagnostique pas, ne change jamais la priorité et doit reconnaître l’insuffisance des données au lieu d’inventer un profil.

*Sélectionner un membre, puis appuyer sur « Demander à l’assistant ».*

#### Suggérer les prochaines questions à poser

MedBox mesure cinq paramètres et en fait observer deux. L’assistant peut donc aider à formuler des questions brèves pour recueillir les informations qui manquent, sans les transformer en mesures.

*Inclus dans chaque évaluation de l’assistant.*

9 des 12 capacités documentées ne dépendent pas du modèle. L’IA reste une couche d’explication au-dessus d’un système déterministe.

## 11. Limites absolues de l’assistant

Ces limites ne reposent pas uniquement sur une consigne : elles sont renforcées par le schéma de sortie et par des contrôles serveur.

**Poser un diagnostic.** L’assistant propose seulement des hypothèses accompagnées de leurs signes. Le schéma de réponse ne contient aucun champ de diagnostic : il ne peut donc pas en produire, même si on le lui demande.

**Prescrire un médicament ou un traitement.** Aucun champ ne permet d’émettre un traitement. La seule liste qu’il peut remplir concerne les observations et mesures à recueillir. Si un médicament, une dose ou une voie d’administration y apparaît, MedBox supprime toute la liste et le signale. MedBox n’est pas médecin.

**Modifier la priorité d’une personne.** La priorité provient de NEWS2, calculé en Python à partir des mesures. Le modèle n’appartient pas à ce circuit et ne peut pas réécrire le score.

**Traiter une déclaration comme une mesure.** Les symptômes déclarés lui parviennent comme des informations non vérifiées. Chaque signe avancé doit nommer sa source.

**Bloquer les mesures.** L’assistant fonctionne sur une voie lente séparée. S’il se bloque ou s’arrête, les constantes, la priorisation, les propositions de quarantaine et l’enregistrement continuent.

**Accéder au réseau.** Le modèle fonctionne localement ; le vaisseau n’a aucun contact avec la Terre.

## 12. Commandes de la console 3D

Appuyer sur `/` pour placer le curseur dans la ligne de commande. Les commandes françaises sont prioritaires ; les anciennes formes anglaises restent des alias de compatibilité.

| Commande française | Alias compatibles | Action | Assistant requis |
|---|---|---|---|
| `prioritaire` | `pire`, `worst` | Sélectionner le membre ayant le score NEWS2 le plus élevé. | non |
| `suivant` | `next` | Passer au membre suivant dans l’ordre de priorité. | non |
| `pourquoi` | `why` | Afficher le calcul du score sélectionné, paramètre par paramètre. | non |
| `isolés` | `isolated` | Afficher les candidats en attente de confirmation, les personnes confirmées en quarantaine et les zones scellées. | non |
| `déclaré <mots>` | `said <words>` | Enregistrer les mots que ce membre vient de prononcer. | non |
| `évaluer` | `assess` | Demander des hypothèses à l’assistant pour le membre sélectionné. | oui |
| `demander` | `ask` | Lister les questions à poser ensuite à cette personne. | oui |
| `aide` | `help` | Expliquer ce que MedBox peut et ne peut pas faire, même sans IA. | non |

`déclaré` prend le reste de la ligne, par exemple : `déclaré j’ai mal à la tête depuis ce matin`. Cette phrase est enregistrée comme déclaration, pas comme mesure.

## 13. Lancer un scénario

Un scénario est une chronologie répétable appliquée à l’équipage synthétique. Appuyer sur **Lancer** ; **Réinitialiser** ramène les trajectoires vers les lignes de base.

### Baisse thermique après incident (`baisse-thermique`)

Un membre revient d'une zone froide avec une baisse progressive de température. Le système détecte l'écart à sa ligne personnelle et demande une vérification clinique sans nommer de pathologie.

### Alerte respiratoire à bord (`contamination`)

Six membres sur quarante présentent une détérioration compatible avec une exposition respiratoire confirmée par le scénario. Le système détecte les écarts, priorise la surveillance et propose l'affectation en zone d'isolement sans poser de diagnostic.

### Récupération après effort prolongé (`effort-prolonge`)

Un membre revient d'une intervention physique avec pouls et respiration élevés. Le profil teste la surveillance d'un écart potentiellement transitoire et rappelle qu'une alerte n'est pas un diagnostic.

### Exposition environnementale groupée (`exposition-environnementale`)

Trois membres suivis montrent des écarts concordants après une exposition confirmée par le scénario. MedBox affiche ce regroupement connu et propose un isolement opérationnel avec validation humaine.

### Gêne respiratoire progressive (`gene-respiratoire`)

Un membre sous surveillance présente une augmentation de sa fréquence respiratoire puis une baisse de SpO2 explicitement simulée. Le scénario teste l'alerte rapide sans attribuer de maladie.

### Profil pseudo-grippal simulé (`signes-pseudo-grippaux`)

Un membre présente des écarts thermiques et respiratoires compatibles avec plusieurs causes possibles. La plainte peut être dictée séparément pendant la démonstration; MedBox recommande une évaluation sans conclure à une grippe.

### Écart thermique individuel (`single-patient`)

Un membre signale un mal de tête puis sa température s'écarte progressivement de sa ligne habituelle. Le système surveille et priorise sans diagnostiquer.

**Pendant la soutenance, annoncer explicitement qu’il s’agit de données synthétiques.** Les scénarios démontrent la réaction du logiciel ; ils ne valident pas un capteur médical réel.

## 14. Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| Tableau vide ou connexion éteinte | Le navigateur ne reçoit plus le flux | Recharger la page ; si nécessaire, relancer MedBox. |
| Voyant IA éteint | Ollama démarre encore ou n’est pas disponible | Attendre le préchauffage. Les mesures restent actives. |
| Assistant indisponible ou délai dépassé | La requête locale a échoué | Lire le motif affiché et réessayer ; ne pas interrompre la surveillance. |
| Le navigateur refuse le micro | Permission absente, page non sécurisée ou micro occupé | Présenter depuis `localhost`, vérifier le périphérique et l’autorisation du navigateur, puis réactiver MedBox. |
| L’avis de consentement n’est pas lu à haute voix | Aucun clip ou voix locale française disponible | Lire le texte affiché ; l’accord vocal reste obligatoire avant l’écoute continue. |
| Vue 3D noire | WebGL indisponible | Utiliser `/board`, qui reçoit les mêmes données. |
| Candidat détecté mais aucune zone scellée | La confirmation humaine n’a pas encore eu lieu | Vérifier le dossier puis choisir explicitement **Confirmer l’isolement**. |
| Constantes redevenues normales mais zone toujours scellée | La levée automatique est volontairement désactivée | Vérifier la situation puis choisir **Lever manuellement**. |

## 15. Données et composants locaux

| Composant | Configuration |
|---|---|
| Modèle | `qwen2.5:1.5b-instruct`, exécuté localement par Ollama |
| Modèles de repli configurés | `qwen2.5:0.5b-instruct` |
| Version Ollama ciblée | 0.13.1 |
| Reconnaissance vocale | Locale, français/anglais ; aucun audio conservé. |
| Alertes vocales | Clips locaux préenregistrés ; aucun service en ligne. |
| Base | Fichier SQLite local (`data/medbox.db`), choisi pour un paquet autonome sans serveur à administrer. |
| Rapports médicaux | Stockage local contrôlé ; jamais envoyés au LLM. |
| Réseau extérieur | Aucun appel nécessaire au fonctionnement de la station ou du modèle. |

L’API de reconnaissance vocale du navigateur n’est pas utilisée, car elle peut transmettre l’audio à un service distant. La transcription MedBox passe uniquement par le moteur local configuré.

---

*Regénérer ce document avec `python tools/guide.py`. Il est construit à partir du produit afin de rester aligné sur la version démontrée.*
