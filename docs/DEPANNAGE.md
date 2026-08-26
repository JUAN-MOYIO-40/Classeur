# Dépannage de Classeur

## L’application ne démarre pas

Vérifie que Python 3.11 ou une version plus récente est installé et que l’environnement virtuel est activé. Réinstalle les dépendances avec `python -m pip install -r requirements.txt`, puis relance `python main.py`.

Sous Windows, l’exécutable doit être lancé depuis le dossier `dist\MDJR_Classeur` avec ses fichiers associés. Il ne faut pas déplacer uniquement le fichier `.exe` hors de son dossier de distribution.

## Le scan ne trouve aucun fichier

Vérifie le chemin du dossier source et assure-toi qu’il existe. Les dossiers source et destination doivent être différents et non imbriqués. Les fichiers temporaires, les liens symboliques et les fichiers qui sont encore en cours d’écriture sont ignorés volontairement.

Si un fichier est dans un format non pris en charge, il peut être présent dans le dossier mais ne produire aucune proposition exploitable. Consulte la colonne **Lecture** et le panneau d’explication.

## Le nom proposé est peu précis

Classeur ne peut proposer un nom détaillé que si le contenu est lisible. Un PDF composé d’images, une photo ou un fichier dans un format non pris en charge ne fournit pas forcément de texte. Dans ce cas, le nom d’origine est conservé ou la proposition est signalée comme peu fiable.

Vérifie l’extrait affiché et la justification. Tu peux modifier la matière ou la nature dans la file avant de classer. Ne valide pas automatiquement les propositions marquées **À vérifier**.

## Un document n’est pas copié

Regarde l’état de la ligne. Si elle indique un doublon exact conservé, Classeur a trouvé un fichier de même empreinte ou un texte normalisé équivalent dans la destination. Il n’effectue pas une seconde copie.

Si le fichier différent porte le même nom qu’un document existant, Classeur ajoute un suffixe contrôlé comme `(1)`. Il ne remplace pas le document existant.

## La surveillance ne réagit pas

Vérifie que la surveillance est active et que le dossier source est accessible. Classeur attend deux observations cohérentes pour limiter le risque de traiter un fichier encore en cours de copie.

Si le module `watchdog` n’est pas disponible, l’application utilise un mode de vérification périodique plus simple. Ce mode peut réagir avec un délai plus long.

## L’annulation est partielle

L’annulation vérifie la taille et la date de modification de chaque fichier cible. Si un fichier a été modifié depuis le classement, Classeur le laisse en place au lieu de l’écraser ou de le supprimer. Une annulation partielle est donc un comportement de protection, pas nécessairement une panne.

La suppression définitive des doublons ne peut pas être annulée par Classeur. Utilise la quarantaine lorsque tu veux conserver une possibilité de récupération manuelle.

## L’index de recherche semble incomplet

Relance l’action de reconstruction de l’index depuis la fenêtre de recherche. Les fichiers inchangés utilisent le cache, tandis que les fichiers modifiés sont relus. Vérifie également que le dossier voulu fait partie des racines de recherche.

Les recherches sont locales. Elles portent sur les noms, chemins, catégories, titres et extraits réellement indexés, pas sur le contenu d’un document illisible.

## Signaler une erreur

Pour signaler un problème, indique le système utilisé, la version de Classeur, l’étape concernée et un exemple reproductible avec des fichiers de test non sensibles. Ne joins pas de documents personnels, de mots de passe, de tokens ou de bases SQLite contenant ton historique local.
