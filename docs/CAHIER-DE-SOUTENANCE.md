# Cahier de soutenance — chaque effet, comment le déclencher, ce qui doit se passer

Pour répéter la démonstration sans surprise. Chaque ligne est un test : le geste,
ce que l’écran fait, ce que la voix dit. Si une ligne ne se passe pas comme écrit,
ce n’est pas normal.

## 0. Avant d’entrer dans la salle

| Geste | Attendu |
|---|---|
| Brancher le chargeur ; fermer Chrome, WhatsApp, Spotify, le VPN | Le modèle a besoin de mémoire vive : sous 4 Go libres, il ralentit ; sous 2,5 Go, il rame. |
| Double-clic `DEMARRER-LA-DEMO.cmd` à la racine de `Desktop\MedBox`, cinq minutes avant | Une fenêtre noire : « Ollama installé en écoute », la mémoire libre, « Démarrage de la station », puis « MedBox répond » et le navigateur s’ouvre sur le vaisseau, en une dizaine de secondes. La puce « assistant » passe de « préchauffage » à « prêt » en moins d’une minute. **Garder cette fenêtre ouverte** : la fermer arrête MedBox. Si MedBox tournait déjà, le double-clic ouvre juste le navigateur. |
| Une ligne ECHEC dans cette fenêtre | Port pris par un autre programme (le nom est écrit) ou `.venv` absent : corriger, relancer. Ollama absent ou muet ne bloque pas : la station démarre et la page dit que le référent est arrêté. |
| Le dossier portable (`MedBox-Portable`, sur le PC ou la clé) | Même bouton à sa racine : contrôle complet puis `MedBox.exe`. Ne pas le lancer en même temps que la version du dossier `MedBox` : ils veulent les mêmes ports. |
| `http://127.0.0.1:8771` à `8776` dans des onglets | Les six espaces personnels répondent (Eddy, Brad, Davidson, Anthony, Frederic, Merove). |

## 1. La page vaisseau (`/ship`)

| Geste | Attendu |
|---|---|
| Regarder | Un vaisseau vu de trois quarts : la coque ouverte côté public, deux ponts, quarante cabines, l’infirmerie au centre du pont bas, les trois zones d’isolement A, B, C autour, les serres sur le dos, les moteurs à l’arrière. Quarante points lumineux : l’équipage, dans ses cabines. |
| Glisser la souris | Le vaisseau tourne ; la coupe suit la caméra (le flanc face à vous s’ouvre). Molette : zoom. |
| Cliquer un point | Le panneau du membre s’ouvre à droite : nom, rôle, constantes, score ; la caméra s’approche. Échap ferme. |
| Cliquer la zone **A** dans le rail des zones (ou dire « MedBox, montre la zone A ») | La caméra entre dans la pièce ; le pont du dessus s’efface ; le panneau « Zone A · 0/4 · ouverte » liste qui s’y trouve. **Brief** la décrit à voix haute ; **Suivante** passe à B ; **Vaisseau** (ou Échap) revient. |
| Bouton **Ronde** (ou « MedBox, ronde ») | Le référent fait le tour à voix haute : état du bord, zone A, B, C, infirmerie, retour. Environ une minute. |
| **Son coupé → Son activé** | Le référent se présente à voix haute une fois. |
| Pastille **Écoute locale → Activer** | Le navigateur demande le micro ; la pastille s’ouvre sur le texte de consentement ; dire **« j’accepte »** ; il demande la langue ; dire **« français »** ; « À l’écoute. Dites MedBox, puis votre demande. » La pastille se replie toute seule. |
| Dire **« MedBox, qui est en isolement ? »** | Réponse immédiate, à l’écran et à voix haute, depuis les registres (pas le modèle) : « Tout l’équipage (40 membres) est dans sa plage habituelle. Personne n’est en isolement. » Pendant le scénario : « Équipage de 40 : à surveiller : … ; personne en isolement. » puis les noms décidés. |
| Dire **« MedBox, comment va Brad ? »** (depuis n’importe quelle page) | Le membre nommé devient le sujet : « Brad est en routine aujourd’hui : score 0… ». Immédiat. |
| Dire **« MedBox, présente-toi »** | La présentation de la station, immédiate. |
| Champ **Commande** : `worst` | Le membre le plus prioritaire est sélectionné. `isoles`, `pourquoi`, `suivant`, `aide` marchent aussi. |

## 2. Le scénario « Alerte respiratoire à bord »

| Geste | Attendu |
|---|---|
| Choisir « Alerte respiratoire à bord » → **Lancer** | La barre du bas compte 01:30 ; en quelques secondes six points virent au jaune puis au rouge ; les compteurs « à surveiller » montent ; « 6 à confirmer » dans le rail des zones. |
| Attendre les décisions | Les membres décidés glissent dans les couchettes des zones ; le panneau d’un membre dit « isolement décidé, à confirmer ». |
| **Réinitialiser** | Tout revient en routine ; les points rentrent dans leurs cabines. **Rejouer** relance à l’identique. |

## 3. La page équipage (`/crew`, menu Navigation → Équipage)

| Geste | Attendu |
|---|---|
| Regarder | Compteurs (équipage, en forme, à surveiller, isolés + « à confirmer »), messages du référent, « en forme cette semaine » avec ses habitudes, les activités du jour, le tableau des six avec leur semaine. |
| Pendant le scénario | Chaque décision arrive avec un **signal sonore** et une carte jaune. |
| **Lire** sur un message | La carte de la personne s’ouvre : ses constantes, le vaisseau embarqué centré sur la pièce d’isolement (le pont du dessus effacé), et le message est **lu à voix haute**. |
| Cliquer le nom du membre en forme | Son espace personnel s’ouvre (son port). |
| Pastille **Écoute locale** | Même consentement, mêmes commandes que sur le vaisseau. |

## 4. Un espace personnel (`http://127.0.0.1:8776`, Merove)

| Geste | Attendu |
|---|---|
| Ouvrir | « Bonjour Merove. Je suis MedBox, le référent médical du bord… » ; ses constantes du jour face à ses valeurs habituelles ; sa semaine ; ses messages ; ses activités ; son dossier ; le vaisseau centré sur elle. |
| **Écouter le référent** | La présentation est lue à voix haute, à la deuxième personne. |
| **Mon évaluation** | Pour les six membres qui ont une page, l’évaluation est préparée en arrière-plan dès que le modèle est chaud (compter deux minutes après le lancement) : le clic l’affiche aussitôt et elle est lue. Sinon les étapes de réflexion s’affichent (je relève vos constantes… je compare… je vérifie…) et l’évaluation arrive en dix à vingt secondes. Pendant le scénario : elle nomme ce que les mesures montrent et la décision. |
| Écrire ou dire **« est-ce que je vais bien ? »** | Réponse immédiate : « Vous êtes en routine aujourd’hui : score 0… » ou « Vous êtes à surveiller : score 5, priorité moyenne, avec de la fièvre et une respiration plus rapide que d’habitude. L’isolement est décidé, à confirmer. » |
| **« pourquoi mon pouls monte ? »**, **« ma température ? »** | Réponse immédiate avec la valeur, la plage habituelle et le poids dans le score. |
| **« j’ai mal à la tête, c’est grave ? »** | Immédiat : « Je note « j’ai mal à la tête… » dans votre dossier. Pour l’instant, vos constantes ne montrent rien d’anormal… » ; la plainte apparaît dans le dossier. |
| Une question ouverte (**« est-ce que je dois dormir plus ? »**) | Le référent dit « un instant, je regarde vos constantes » ; les étapes défilent ; la réponse arrive en trois à cinq secondes quand la mémoire vive est libre ; si le modèle dépasse dix secondes, la station répond avec ses faits et le dit. Pendant le scénario, une question passe devant l’évaluation de fond : elle ne fait jamais la queue. |
| **Nommer** un assistant (par exemple « Nova ») | « Nova » devient un mot de réveil : « Nova, est-ce que je vais bien ? » |

## 5. Le tableau (`/board`)

| Geste | Attendu |
|---|---|
| Regarder | Les quarante membres classés par score, couleur par priorité ; à droite les zones et le dossier du membre sélectionné ; en bas le réglage manuel des écarts. |
| Cliquer une ligne | Le dossier : réponses Oui / Non / Incertain, courbes des dix dernières minutes, contacts. |

## 6. Le moment de panne

| Geste | Attendu |
|---|---|
| PowerShell : `tools\assistant.ps1 stop` | En quelques secondes la puce passe à « Simulation de secours, pas un modèle » ; les constantes, le score, les zones continuent ; « Mon évaluation » dit que la station répond avec ses faits. |
| `tools\assistant.ps1 start` | La puce repasse à « préchauffage » puis « prêt » ; le référent revient. |

## 7. Ce qu’il faut savoir dire si une question tombe

- **Pourquoi la réponse met parfois plusieurs secondes ?** Le modèle tourne sur le processeur du portable, sans carte graphique : il lit environ trente-cinq mots par seconde et en écrit seize. La station répond elle-même à tout ce qu’elle sait (état, constantes, isolement, plainte, présentation, un membre nommé) en moins d’une seconde, et confie au modèle seulement les questions ouvertes, avec des faits réduits à l’essentiel, en le laissant dix secondes.
- **Pourquoi un si petit modèle ?** Parce qu’il doit tenir dans le vaisseau, sans réseau ; il formule, il ne décide pas.
- **Et si le micro ne s’active pas ?** Le clavier fait tout : le champ Commande, le champ question, les boutons.
- **Et si le navigateur garde une vieille page ?** Ctrl+F5 ; les pages se revalident à chaque chargement.
