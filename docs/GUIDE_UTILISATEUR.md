# Guide utilisateur de Classeur

## Vue d’ensemble

Classeur est un organisateur documentaire local. Il analyse les fichiers dans un dossier source, propose une destination hiérarchique et affiche un nom de fichier plus lisible lorsque le contenu permet de le faire. Les documents restent sur l’ordinateur et le classement peut être utilisé sans connexion après l’installation.

Le fonctionnement repose sur une règle simple : **Classeur propose, l’utilisateur vérifie, puis l’application exécute**. Le mode copie est recommandé pour une première utilisation.

## Le parcours recommandé

### 1. Choisir deux dossiers séparés

Le premier dossier reçoit les fichiers à traiter. Le second contient l’organisation finale. Ils doivent être distincts et ne doivent pas être imbriqués l’un dans l’autre.

```text
Documents à trier/
Documents classés/
```

Classeur refuse les dossiers identiques ou imbriqués afin d’éviter qu’il analyse ses propres résultats en boucle.

### 2. Analyser

Le bouton **Analyser les fichiers existants** parcourt le dossier source. Les fichiers temporaires de logiciels, les liens symboliques et les fichiers déjà situés dans la destination sont ignorés.

Pour chaque document, Classeur affiche le nom original, le nom proposé, la matière, la nature, l’arborescence, le niveau de confiance, l’état de lecture et la destination prévue.

### 3. Vérifier

Sélectionne une ligne pour afficher la justification, l’extrait de contenu, le nom original, le nom proposé et l’empreinte du document. Les propositions marquées **À vérifier** ne doivent pas être classées automatiquement sans contrôle.

Les matières et natures peuvent être corrigées dans la file de validation. Un libellé ne peut pas contenir de séparateur de chemin ni de caractère interdit.

### 4. Classer

Le bouton **Classer les éléments sélectionnés** demande une confirmation lorsque cette option est activée. Les destinations sont créées si nécessaire et les collisions sont traitées sans écraser un fichier existant.

Le mode **Copier l’original** conserve le document source. Le mode **Déplacer l’original** déplace et renomme le fichier dans la destination. Il doit être réservé aux cas où la proposition a été vérifiée.

## Nommage intelligent

Classeur sépare trois informations : le nom original, le titre détecté et le nom proposé. Le nom proposé peut combiner une période, une matière, un thème, une nature et un titre lisible extrait du document.

Exemple :

```text
Nom original : IMG_001.txt
Nom proposé  : Physique - Électromagnétisme - Cours - Champ électrique.txt
```

Le moteur ne fabrique pas un résumé lorsqu’il ne peut pas lire le contenu. Pour un fichier image ou un PDF scanné, le nom d’origine peut être conservé et la confiance sera faible. Cette prudence est intentionnelle.

## Doublons et identité documentaire

Classeur calcule une empreinte SHA-256 pour identifier les fichiers identiques en octets. Pour un document textuel entièrement lisible, il calcule aussi une signature du texte normalisé. Deux fichiers peuvent donc être reconnus comme équivalents même si la casse ou les espaces diffèrent.

Cette fonction ne reconnaît pas encore deux documents reformulés. Un contenu identique, un texte normalisé identique et un sujet similaire sont trois situations différentes.

Avant une copie ou un déplacement, si un document identique est déjà présent dans la destination, Classeur le conserve et n’effectue pas de seconde copie. Les fichiers différents qui ont le même nom reçoivent un suffixe contrôlé comme `(1)`.

Le bouton **Scanner les doublons** permet une analyse plus large des fichiers et des dossiers. La quarantaine est préférable à la suppression définitive. La suppression définitive n’est pas annulable par Classeur.

## Surveillance des nouveaux fichiers

Le bouton **Démarrer la surveillance** active la détection des nouveaux fichiers. La surveillance attend deux observations cohérentes avant de traiter un fichier afin de réduire le risque de classer un document encore en cours d’écriture.

Le mode automatique peut classer les propositions pendant la surveillance. Pour une première utilisation, il est préférable de laisser ce mode désactivé et de vérifier la file manuellement.

## Historique et annulation

Le bouton **Historique** affiche les opérations réussies enregistrées localement. Le bouton **Annuler la dernière opération** cible la dernière session de classement.

Avant de restaurer une opération, Classeur vérifie la taille et la date de modification de la destination. Si le fichier a changé, il est laissé en place et l’annulation devient partielle. Cette règle protège les modifications faites après le classement.

L’annulation ne transforme pas la suppression définitive des doublons en opération réversible. Pour cette raison, la quarantaine reste le choix recommandé.

## Préférences

La fenêtre **Préférences** regroupe la langue, l’apparence et les confirmations. Le thème **Système** est utilisé par défaut. Les modes clair et sombre sont disponibles, ainsi qu’une couleur d’accent et une image de fond locale.

La langue peut être réglée sur français ou anglais. Le changement complet est appliqué au prochain démarrage afin d’éviter un mélange de libellés pendant la session en cours.

L’image de fond est purement visuelle. Elle ne quitte pas l’ordinateur et n’est pas traitée comme un document à classer.

## Limites à connaître

Classeur lit les formats texte, les PDF textuels et certains formats bureautiques XML. Il ne réalise pas encore d’OCR pour les scans et les images. Une confiance affichée est un indicateur heuristique et non une garantie de justesse.

Il est conseillé de tester l’application sur une copie de ses documents importants, de conserver une sauvegarde séparée et de vérifier les propositions avant d’utiliser le mode déplacement ou le classement automatique.

## Résolution rapide des problèmes

| Problème | Vérification recommandée |
|---|---|
| Aucun fichier n’apparaît | Vérifier le dossier source, les extensions et le fait que le fichier ne soit pas temporaire. |
| Le nom proposé paraît étrange | Lire la justification et l’extrait ; corriger la matière ou la nature dans la file. |
| Un fichier n’est pas renommé | Le contenu est peut-être illisible, vide ou le nom original est déjà le choix le plus sûr. |
| Une copie n’est pas créée | Vérifier le statut de doublon exact ou textuel dans la file. |
| L’annulation est partielle | Le fichier cible a probablement changé depuis le classement. |
| La surveillance ne démarre pas | Vérifier que les deux dossiers existent et sont séparés. |
