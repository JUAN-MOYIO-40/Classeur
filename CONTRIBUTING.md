# Contribuer à Classeur

Merci de contribuer à Classeur. Le projet privilégie une application locale, explicable et prudente. Une modification utile n’est pas seulement une nouvelle fonction : elle doit aussi préserver les documents de l’utilisateur, rester testable et respecter la séparation des responsabilités.

## Principes du projet

Les documents ne doivent pas être envoyés vers un service distant par le comportement standard. Les opérations qui copient, déplacent, mettent en quarantaine ou suppriment des fichiers doivent être explicites, traçables et testées sur des répertoires temporaires.

Une proposition de classement doit rester compréhensible. Lorsqu’un format n’est pas réellement lu, le code doit l’indiquer au lieu de présenter une confiance artificielle. Le nom original, le nom proposé et la justification doivent rester distinguables.

## Où placer le code

| Besoin | Emplacement |
|---|---|
| Modèle métier ou règle indépendante de Qt | `mdjr_classeur/domain/` |
| Cas d’usage et orchestration métier | `mdjr_classeur/application/` |
| Système de fichiers, SQLite, historique ou watchdog | `mdjr_classeur/infrastructure/` |
| Fenêtre, dialogue, modèle Qt ou worker | `mdjr_classeur/presentation/` |
| Assemblage et signaux de la fenêtre principale | `mdjr_classeur/app.py` |
| Tests indépendants de l’interface | `tests/test_*.py` |
| Tests graphiques ou de parcours | `tests/smoke_*.py` et `tests/integration_*.py` |

La présentation peut appeler un service, mais elle ne doit pas décider seule de la politique métier ni manipuler directement `shutil`, SQLite ou les fichiers de configuration. Les workers Qt doivent adapter les signaux et déléguer leur travail.

## Méthode de développement

Avant de coder, décrire le cas d’usage et ses risques. Ajouter d’abord un test qui exprime le comportement attendu. Implémenter ensuite la logique dans la couche appropriée. Enfin, brancher l’interface et ajouter un smoke test si le comportement visible change.

Les noms de fichiers proposés doivent être nettoyés et limités. Aucun nom ne doit introduire de séparateur de chemin, de caractère interdit ou d’écrasement silencieux. Les opérations physiques doivent gérer les collisions et vérifier les signatures lorsque cela est nécessaire.

## Vérifications locales

Depuis la racine du dépôt :

```bash
python3 -m py_compile mdjr_classeur/*.py mdjr_classeur/domain/*.py mdjr_classeur/application/*.py mdjr_classeur/infrastructure/*.py mdjr_classeur/presentation/*.py
python3 -m pytest -q
PYTHONPATH=. python3 tests/integration_flow.py
PYTHONPATH=. python3 tests/realtime_simulation.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 tests/smoke_gui.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 tests/smoke_preferences.py
git diff --check
```

Les tests ne doivent jamais utiliser les dossiers personnels de l’utilisateur. Utiliser `tmp_path` ou `TemporaryDirectory`. Un test qui touche à la copie, au déplacement ou à la suppression doit vérifier à la fois l’état du fichier source, l’état de la destination et le résultat retourné par le service.

## Revue et commit

Un commit doit avoir un objectif lisible. Il doit inclure les tests correspondant au changement et ne doit pas contenir `.venv`, `dist`, `build`, bases SQLite personnelles, fichiers de configuration locaux ou secrets.

Avant une pull request, vérifier la documentation, les traductions français/anglais, les collisions de noms, les fichiers partiellement écrits, les chemins identiques ou imbriqués et les interruptions pendant une opération.

## Limites à respecter

Il ne faut pas présenter le classificateur local comme un modèle général de compréhension. L’OCR, les modèles sémantiques lourds et les documents reformulés appartiennent à des chantiers distincts et doivent être ajoutés avec une mesure de précision, une option claire et un comportement de repli sûr.
