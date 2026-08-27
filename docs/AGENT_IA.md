# Agent IA documentaire de Classeur

## Positionnement

Classeur n’est pas entraîné pour devenir un modèle général comme un grand laboratoire d’IA. Sa force est différente : il combine un moteur documentaire spécialisé, une mémoire locale, des règles explicables, un planificateur d’actions et un espace de dialogue. L’agent ne doit jamais prétendre être certain lorsqu’il ne l’est pas.

> Un agent documentaire observe les fichiers, construit une représentation de leur contenu, propose un plan, demande une permission adaptée au risque, exécute des opérations réversibles et apprend des corrections explicitement validées.

## Boucle agentique

Le cycle prévu est le suivant :

1. **Observer** : détecter les nouveaux fichiers, les modifications, les documents incomplets et les doublons potentiels.
2. **Comprendre** : extraire le texte, exécuter l’OCR local si nécessaire, repérer le titre, l’année, le domaine, la matière, le thème et la nature.
3. **Se souvenir** : comparer avec le cache, l’index documentaire et les corrections humaines précédentes.
4. **Planifier** : choisir une destination, un nom, un mode de traitement et un niveau de confirmation.
5. **Dialoguer** : présenter la décision, expliquer les indices utilisés et répondre aux demandes de l’utilisateur.
6. **Agir** : copier, déplacer, renommer, mettre en quarantaine ou ne rien faire selon la permission accordée.
7. **Vérifier** : contrôler le résultat, l’intégrité, l’absence d’écrasement et la cohérence de l’index.
8. **Apprendre** : enregistrer uniquement les corrections validées, jamais les prédictions non confirmées.

## Trois niveaux de décision

| Niveau | Conditions | Action |
|---|---|---|
| Confiance élevée | Signaux cohérents, destination stable, aucune collision | Classement automatique possible si l’utilisateur a activé ce mode |
| Confiance moyenne | Proposition plausible mais indices incomplets | Demande de validation ou classement manuel |
| Confiance faible | Document illisible, ambigu, conflit ou risque d’écrasement | Blocage prudent et envoi dans la file de revue |

## Apprentissage supervisé

Une correction humaine de matière, catégorie ou arborescence devient un exemple local. La mémoire conserve le contexte minimal nécessaire : nom, extrait, empreintes et étiquette validée. Lors d’une future analyse, des exemples similaires peuvent influencer la proposition. La mémoire ne remplace pas la vérification : elle augmente la confiance seulement lorsque les signaux sont compatibles.

La prochaine amélioration consiste à ajouter une page de validation des exemples appris, un bouton pour oublier un exemple, une mesure de précision par catégorie et un seuil configurable. L’utilisateur doit pouvoir comprendre pourquoi une correction précédente a influencé une nouvelle décision.

## Découverte non supervisée

Le mode non supervisé ne doit pas créer directement des dossiers définitifs. Il doit d’abord regrouper les documents similaires à partir des textes, noms, dates et signatures, puis présenter des groupes candidats. L’utilisateur valide les intitulés et l’arborescence avant toute réorganisation. Les groupes contenant trop peu de documents ou présentant une forte dispersion restent en revue.

## Dialogue

L’espace de dialogue doit accepter des demandes telles que :

- « Montre-moi les documents que tu hésites à classer. »
- « Pourquoi ce fichier a-t-il été placé dans cette matière ? »
- « Regroupe mes cours de mécanique par année. »
- « Ne déplace rien, prépare seulement un aperçu. »
- « Applique cette correction aux documents similaires. »
- « Annule la dernière session si les fichiers n’ont pas changé. »

Une demande conversationnelle ne doit pas déclencher une opération sensible sans confirmation lorsqu’elle implique déplacement, suppression, écrasement ou transmission en ligne.

## Renfort en ligne

Le mode en ligne est un accélérateur, pas le cerveau obligatoire de Classeur. Le fonctionnement local doit rester complet. Lorsque l’utilisateur l’autorise, le service distant peut recevoir un extrait limité et nettoyé pour les documents ambigus. Le fichier original, les images de scan et les informations personnelles ne sont pas transmis par défaut.

## Feuille de route

La version agentique complète devra ajouter le dialogue Qt, le planificateur persistant, la validation des corrections apprises, la découverte de groupes non supervisés, l’évaluation de précision, l’adaptateur IA distant optionnel et un tableau de supervision des tâches. Chaque évolution doit comporter des tests, un changelog et une validation avant publication distante.
