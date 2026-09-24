# MedBox — les cinq minutes (soutenance locale, vendredi 25 septembre 2026)

Cinq minutes de démonstration, cinq de questions, en français. Chronomètre
visible. Tout ce qui est dit ici est vrai sur la version taguée
`v0.9-soutenance` ; ne rien promettre d'autre.

Avant d'entrer : `tools\preflight.ps1` doit dire « Prêt ». Mode avion. Secteur.
Station lancée, page vaisseau ouverte en plein écran, scénario « Alerte
respiratoire à bord » sélectionné, rien lancé. Terminal réduit à côté, avec
`tools\assistant.ps1 stop` déjà tapé, non validé.

---

## Minute 0 – 1 · L'équipe, en anglais (obligatoire), puis le problème

Chaque membre se présente, une phrase, en anglais. **Nous sommes l'équipage** :
Eddy (commandant), Brad, Davidson, Anthony, Frederic, Merove sont les six
premiers membres à bord, avec leurs constantes et leur semaine dans la base.
Puis, en français :

> Quarante personnes, six mois sans contact avec la Terre, et pas de médecin.
> Le jour où six d'entre elles tombent malades en même temps, qui décide qui
> voir en premier, qui isoler, et sur quelle base ? MedBox est la mallette qui
> répond à ça, sans internet, sans compte, sans cloud. Et elle répond même
> quand son intelligence artificielle est morte. On va vous le montrer.

## Minute 1 – 2 · La station se présente et demande l'accord

Cliquer **« Activer MedBox »** (une seule fois, c'est l'autorisation du micro).
La station parle, avec sa propre voix, hors ligne : qui elle est, ce qu'elle
ne fera jamais, et demande si elle peut écouter. Dire clairement :
**« J'accepte. »** L'état passe à « À L'ÉCOUTE ».

> Vous venez d'entendre la voix de MedBox. Elle est rendue à bord, hors ligne ;
> aucun service. Ce que la station annonce est écrit par nous ; quand l'assistant
> parle, c'est sa réponse relue par la station, jamais son texte brut. L'écoute reste locale : aucun son n'est conservé.

## Minute 2 – 3 · La crise : quinze pour cent de l'équipage

Cliquer **« Lancer »**. Pendant trente secondes, commenter ce que la salle voit :

- les points de l'anneau qui changent de couleur, ordonnés par **NEWS2**, le
  score d'alerte du Royal College of Physicians, calculé sans aucun modèle ;
- la voix : « Isolement proposé. Confirmation humaine requise. » pour chaque
  cas, avec le nom ;
- le rail des zones : **« 6 à confirmer »**.

> Six sur quarante. La station ne met personne en quarantaine toute seule : elle
> propose, une personne décide.

Au même moment, **le tableau d'équipage** (`/crew`, sur un deuxième écran ou
un onglet) **sonne** : le référent y a écrit sa décision pour Eddy et Brad.
Cliquer **« Lire »** : il la dit à voix haute. Sur **la page personnelle de
Brad** (son propre port, http://<vaisseau>:8772), le même message lui est
adressé à la deuxième personne : « Brad, vous présentez de la fièvre et une
respiration rapide. Je vous place en isolement. Restez dans vos quartiers. »

> Chacun à bord a sa page et son serveur. Le référent sait à qui il parle.

Cliquer un candidat, **« Confirmer l'isolement »** : la zone A se scelle,
« Place d'isolement attribuée ». Laisser les cinq autres en attente.

## Minute 3 – 4 · L'assistant, et sa mort

Sur le membre le plus grave (« MedBox, montre-moi le plus malade » à voix
haute, ou cliquer la première ligne) : **« Demander à l'assistant »**. La
réponse est déjà là, en une seconde, en français : deux profils nommés
d'après les instruments, une question à poser, une mesure à refaire, et la
ligne « Préparée il y a N s, avant la demande ».

> Il l'avait préparée dès que le score est monté. Regardez ce qu'il n'a pas le
> droit de faire : pas de diagnostic, pas de médicament, pas de dose. S'il en
> écrit un, la station le bloque et vous le dit.

Si la voix est activée (bouton haut-parleur), l'assistant **lit sa réponse**
pendant qu'on parle. Puis, dans la barre de commande, taper
**« ? quel médicament lui donner ? »** : la réponse revient en quelques
secondes et dit que MedBox ne répond pas à cela ; le panneau montre ce qui a
été bloqué.

> Même quand on lui demande, il ne peut pas : la question passe par la même
> grammaire fermée et le même filtre que tout le reste.

Basculer sur le terminal, valider `tools\assistant.ps1 stop`. Revenir.

> Je viens de tuer l'intelligence artificielle.

Montrer : les constantes bougent toujours, le rail, le score, la voix
(« L'assistant s'est arrêté. Les mesures continuent. »). Cliquer à nouveau
**« Demander à l'assistant »** : la réponse conservée revient, datée, avec
« l'assistant est arrêté ; les mesures et la priorité continuent sans lui ».

## Minute 4 – 5 · Ce qu'elle apprend, et ce qu'elle mesure vraiment

Dire : **« MedBox, qui est le plus mal en point ? »** Elle comprend, répond, et
le panneau Aide montre « Ce que MedBox a appris » : la formulation est retenue,
déterministe la prochaine fois, effaçable d'un clic.

Ouvrir un dossier, **Observations de l'opérateur** : conscience « C —
confusion nouvelle ». Le score passe MOYEN à l'instant et l'étiquette dit
**« NEWS2 complet, sept paramètres »**.

> Cinq paramètres mesurés, deux observés par une personne, et la station dit
> toujours lesquels elle a et lesquels elle suppose. Merci.

---

## Les trois réponses à avoir

**« Il se prend pour un médecin ? »**
À bord, oui : c'est le référent médical du vaisseau, et il parle comme tel.
Mais ce qu'il affirme tient à des mesures et à un score publié : la priorité
et l'isolement sont calculés sans modèle, le modèle ne formule que sous une
grammaire fermée, et il ne prescrit aucun médicament. L'autorité est dans
la voix ; la sûreté est dans l'architecture.

**« Pourquoi pas un simple chat avec un modèle ? »**
Parce qu'une station de triage n'est pas une fenêtre de discussion. Quand
quinze pour cent de l'équipage est à terre, personne ne tape de questions. Le
score, l'ordre et l'isolement sont calculés sans modèle ; le modèle propose,
et il peut mourir sans rien casser. On vient de le montrer.

**« Comment faire confiance médicalement à un petit modèle local ? »**
On ne lui fait pas confiance, et l'architecture le dit : il n'a aucun champ
pour un diagnostic ni un traitement, la station renomme ses hypothèses
d'après les instruments, supprime tout ce qui ressemble à une dose ou à une
maladie, et l'affiche comme supprimé. Chaque signe qu'il cite nomme
l'instrument qui l'a mesuré, ou dit que personne ne l'a mesuré.

**« Et si un capteur ment ? »**
Chaque score porte la liste de ce qui a été mesuré et de ce qui est supposé ;
un paramètre absent n'est jamais compté comme normal en silence, l'étiquette
dit « dépistage partiel ». Une valeur invraisemblable reste une valeur d'un
instrument, pas un fait : la personne devant l'écran décide, et c'est pour ça
que l'isolement se confirme à la main.

**Si on demande la conformité :** prototype de recherche et d'enseignement,
pas un dispositif médical ; NEWS2 est un score de dégradation, pas de
contagion ; les cartes de protocole sont simulées et fermées par défaut.

## Ce qu'on ne fait pas ce jour-là

Pas de capteurs réels (données synthétiques, horloge accélérée, bandeau à
l'écran). Pas de démonstration depuis une machine inconnue. Pas de réponse à
un « et si » par une promesse : « c'est la prochaine étape », puis la
question suivante.
