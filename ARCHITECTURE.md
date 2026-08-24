# Architecture de Classeur

Classeur est organisé en couches simples. Chaque couche a une responsabilité précise et les dépendances doivent aller vers les couches plus stables, jamais l’inverse.

## Organisation

| Dossier | Responsabilité | Dépendances autorisées |
|---|---|---|
| `domain/` | Modèles métier et construction des destinations | `classifier.py` pour les types de classification historiques |
| `application/` | Cas d’usage : scanner, classifier, indexer, organiser et annuler | domaine, cache, index et infrastructure |
| `infrastructure/` | Système de fichiers, SQLite, historique et watchdog | bibliothèques système et modèles métier |
| `presentation/` | Fenêtres, dialogues, modèles Qt et workers adaptateurs | application, domaine et infrastructure via contrats |
| `app.py` | Composition de l’application et orchestration de `MainWindow` | toutes les couches, uniquement pour les assembler |

## Règle de dépendance

> L’interface déclenche un cas d’usage et affiche son résultat. Elle ne décide pas de la politique métier et ne réalise pas directement les opérations physiques sur les fichiers.

Les opérations de classement sont décomposées ainsi :

```text
ScanWorker ou action utilisateur
        ↓
ScanService
        ↓
ClassificationService
        ↓
Planning du domaine
        ↓
FileOperationService
        ↓
HistoryRepository et SearchIndex
```

Les workers Qt ne contiennent pas la logique de copie, de déplacement, de classification ou d’indexation. Ils adaptent seulement les signaux des services aux événements attendus par l’interface.

## Services principaux

`ClassificationService` centralise l’usage du classificateur et du cache. `ScanService` parcourt un dossier, ignore les fichiers temporaires et construit des `PlanItem`. `FileOperationService` réalise les copies atomiques et les déplacements. `UndoService` restaure la dernière session après vérification de la taille et de la date de modification des cibles. `SearchIndexService` exécute la reconstruction transactionnelle de l’index.

## Ajouter une fonctionnalité

Une nouvelle règle métier doit être ajoutée au domaine ou à un service applicatif. Un nouveau format de document doit être ajouté aux extracteurs du classificateur. Une nouvelle persistance doit être encapsulée dans l’infrastructure. Un nouveau bouton ou dialogue doit rester dans `presentation/` et appeler un service au lieu de manipuler directement les fichiers.

Avant toute modification, il faut ajouter un test indépendant de Qt lorsque cela est possible, puis un smoke test d’interface seulement si le comportement visible change. Cette discipline permet de garder une application locale, testable et évolutive sans transformer la fenêtre principale en nouveau point de concentration.
