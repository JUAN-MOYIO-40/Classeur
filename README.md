# Classeur

Classeur est une application de bureau locale pour ranger des fichiers et des documents.

L'idée est simple : on choisit un dossier d'arrivée et un dossier de classement. Classeur analyse les fichiers déjà présents, puis surveille l'arrivée de nouveaux fichiers. Il propose une destination, un nom et une arborescence. L'utilisateur peut vérifier avant de copier ou déplacer.

Le projet est prévu pour fonctionner sans connexion après l'installation des dépendances. Les documents sont analysés sur l'ordinateur.

## Ce que fait l'application

Classeur peut :

- analyser les fichiers déjà présents dans un dossier
- surveiller les nouveaux fichiers pendant que l'application est ouverte
- lire les noms, les chemins, les fichiers texte, les PDF qui contiennent du texte, les DOCX, les XLSX, les PPTX et certains ODT
- reconnaître une année ou une période quand le signal est fiable
- proposer un domaine, une matière, un thème et une nature de document
- réutiliser les dossiers qui existent déjà
- créer une nouvelle branche quand aucune destination correcte n'existe
- proposer un nom de fichier lisible
- rechercher rapidement un fichier par mot clé
- repérer les doublons binaires et les doublons textuellement équivalents lorsqu’un contenu complet est disponible
- placer les doublons dans une quarantaine avant toute suppression

Le classement par défaut est une copie. L'original reste donc dans le dossier d'arrivée. Le déplacement doit être choisi volontairement. Les copies sont écrites dans un fichier temporaire puis rendues visibles seulement quand la copie est terminée.

## Exemple d'arborescence étudiante

Un dossier peut être organisé comme ceci :

```text
MDJR_Classement/
└── Année 1/
    └── Sciences/
        └── Physique/
            └── Électromagnétisme/
                ├── Cours/
                └── TD/
└── Année 2/
    └── Administratif/
        └── Scolarité/
            └── Relevé de notes/
```

Un fichier contenant des indications comme `année 1`, `physique`, `électromagnétisme` et `cours` pourra être proposé sous cette branche :

```text
Année 1/Sciences/Physique/Électromagnétisme/Cours/
```

## Exemple professionnel et personnel

La même logique peut servir pour d'autres usages :

```text
2025/Économie et gestion/Finance/Budget familial/Documents administratifs/
2025/Économie et gestion/Marketing/Projet/
2025/Administratif/Assurance/Contrats/
```

La profondeur est limitée. Classeur ne crée pas un dossier pour chaque mot trouvé. Il ajoute un niveau seulement quand le signal est suffisamment clair. Les documents incertains sont marqués `à vérifier` ou envoyés vers `À trier`.

## Réutilisation des dossiers existants

Avant de créer une destination, Classeur regarde les dossiers déjà présents. Il rapproche certaines variantes connues. Par exemple, `Maths` peut correspondre à `Mathématiques` et `TD` peut correspondre à `Travaux dirigés`.

Si un dossier compatible existe, il est réutilisé. Si aucun dossier ne correspond, Classeur propose d'en créer un. Cette étape évite d'obtenir un nouveau dossier à chaque fichier.

## Créer ses propres règles professionnelles

Les règles sont enregistrées dans un fichier JSON. Le format contient quatre parties : `subjects`, `categories`, `domains` et `topics`.

Le moyen le plus simple est de copier le fichier d'exemple :

```powershell
copy examples\regles_professionnelles.json regles.json
```

Ensuite, ouvre `regles.json` avec un éditeur de texte. Chaque ligne associe un nom de dossier à une liste de mots clés.

```json
{
  "subjects": {
    "Clients": ["client", "clientèle", "prospect"],
    "Projets": ["projet", "chantier", "livrable"]
  },
  "categories": {
    "Contrats": ["contrat", "avenant", "signature"],
    "Factures": ["facture", "paiement", "acompte"]
  },
  "domains": {
    "Gestion": ["gestion", "budget", "comptabilité"],
    "Commercial": ["vente", "client", "prospection"]
  },
  "topics": {
    "Assurance": ["assurance", "sinistre", "garantie"],
    "Ressources humaines": ["salarié", "contrat de travail", "congé"]
  }
}
```

Un exemple de résultat peut être :

```text
2025/Commercial/Clients/Prospect/Contrats/
```

Il est préférable de commencer avec des mots clés précis. Les mots très courts peuvent provoquer des résultats inattendus. Après une modification du fichier, relance l'analyse afin que le cache soit recalculé.

## Nommage intelligent et doublons

Pendant l’analyse, Classeur lit le contenu réellement disponible, détecte un titre possible et affiche séparément le nom original et le nom proposé. Le nom proposé combine prudemment les informations reconnues, par exemple la période, la matière, le thème, la nature et un titre lisible. Lorsque le contenu est absent, illisible ou dans un format non pris en charge, Classeur ne prétend pas comprendre le document et conserve le nom d’origine ou produit une proposition de faible confiance.

Avant une copie ou un déplacement, Classeur calcule une empreinte SHA-256. Il compare aussi, lorsque le document textuel est entièrement lisible, une signature du texte normalisé. Deux fichiers dont les noms sont différents mais dont le contenu est identique ou textuellement équivalent ne sont donc pas recopiés dans la destination. La décision apparaît dans la file sous le statut de doublon exact conservé. Les collisions de noms non identiques reçoivent un suffixe contrôlé comme `(1)` au lieu d’écraser un fichier existant.

Le mode recommandé reste la copie de l’original. Le déplacement peut renommer directement le fichier déplacé, mais il doit être vérifié par l’utilisateur avant validation. Aucune suppression n’est déclenchée par le nommage ou par la détection de doublons.

## Recherche rapide

Le bouton `Recherche rapide` recherche dans les noms, chemins, années, domaines, matières, thèmes, catégories et extraits de contenu. Les accents sont normalisés. Une recherche comme `scolarite` peut retrouver `scolarité`.

La recherche fonctionne avec un index SQLite local. Les fichiers inchangés ne sont pas relus inutilement. Il est possible de filtrer les résultats par statut, d'ouvrir le fichier ou d'afficher son dossier.

## Doublons

Le bouton `Scanner les doublons` compare le contenu réel des fichiers et non leurs noms. Le moteur utilise une empreinte SHA-256 pour les fichiers binaires identiques. Pour les formats textuels entièrement lisibles, il calcule aussi une signature du texte normalisé. Les espaces répétées et la casse ne créent donc pas artificiellement deux documents différents.

Cette seconde comparaison reste volontairement prudente. Elle ne prétend pas reconnaître deux textes reformulés ou deux documents qui traitent du même sujet. Une égalité de contenu est différente d’une similarité de sujet.

Lors d’un classement, un document déjà présent dans la destination n’est pas recopié si son contenu est identique ou si son texte normalisé est identique. L’interface indique le doublon conservé. Si deux documents différents portent le même nom proposé, un suffixe contrôlé comme `(1)` est ajouté. Aucun fichier existant n’est écrasé.

La suppression automatique est désactivée. Le choix recommandé est la quarantaine. La suppression définitive demande une action séparée et une confirmation. Avant une opération de doublon, Classeur vérifie que les fichiers concernés n’ont pas changé depuis l’analyse.

## Profils de fonctionnement

| Profil | Utilisation | Ressources |
|---|---|---|
| Lite | Nom, chemin et règles simples | Faible |
| Standard | Cache, contenu lisible et surveillance événementielle | Recommandé |
| Sémantique locale | Rapprochement léger pour les cas difficiles | Activé seulement si nécessaire |

Classeur n'embarque pas de grand modèle génératif dans la version standard. Le moteur local est déterministe et plus léger. Il est plus facile à expliquer et il ne demande pas de connexion.

## Documentation

Les documents suivants complètent ce README :

| Document | Utilité |
|---|---|
| [Guide utilisateur](docs/GUIDE_UTILISATEUR.md) | Installation, premier classement, nommage, doublons, surveillance et annulation |
| [Dépannage](docs/DEPANNAGE.md) | Diagnostic des problèmes courants et comportements de protection |
| [Architecture](ARCHITECTURE.md) | Découpage des couches et règles de dépendance |
| [Contribution](CONTRIBUTING.md) | Normes de code, tests, sécurité et revue |
| [Hiérarchie](HIERARCHIE.md) | Principes de construction des destinations |
| [Utilisation de GitHub](docs/UTILISATION_GITHUB.md) | Clonage, règles, commits et publication |

## Architecture

Le projet suit une séparation en couches. Le domaine contient les modèles et la logique de destination, `application/` contient les cas d’usage, `infrastructure/` encapsule le système de fichiers, SQLite, l’historique et la surveillance, et `presentation/` contient les fenêtres, dialogues, modèles Qt et workers adaptateurs. `app.py` assemble ces composants et orchestre la fenêtre principale. Le détail du découpage est disponible dans [ARCHITECTURE.md](ARCHITECTURE.md).

## Installation pour le développement

Il faut Python 3.11 ou une version plus récente. Sous Windows :

```powershell
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Sous Linux ou macOS :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python main.py
```

## Créer l'exécutable Windows

Sur Windows, lance :

```text
build_windows.bat
```

Le script crée l'environnement `.venv`, vérifie les dépendances et lance PyInstaller. Une connexion est nécessaire seulement si une dépendance manque. Après la première installation, une nouvelle construction peut fonctionner sans connexion.

Le résultat est ici :

```text
dist\MDJR_Classeur\MDJR_Classeur.exe
```

Il faut partager tout le dossier `dist\MDJR_Classeur`, pas seulement le fichier exe.

## Préférences et apparence

Le bouton `Préférences` ouvre un espace simple organisé en onglets. La langue peut être réglée sur français ou anglais. Le changement de langue est appliqué au prochain démarrage afin de garantir que toute l’interface soit cohérente.

Le thème `Système` est utilisé par défaut. Il suit la palette du système, tandis que les modes clair et sombre permettent de choisir une apparence stable. Une couleur d’accent personnalisée modifie les boutons, les sélections, les indicateurs et la barre de progression. Elle ne modifie jamais le contenu des documents.

Une image locale peut être choisie comme fond. Elle est enregistrée comme préférence, n’est pas classée comme document et peut être retirée avec `Réinitialiser`. Une couche de couleur conserve la lisibilité des textes et des tableaux.

L’onglet `Sécurité` rappelle que la suppression définitive des doublons ne peut pas être annulée par Classeur. Le bouton `Historique` permet de consulter les opérations réussies. Le bouton `Annuler la dernière opération` vérifie les empreintes avant de restaurer une session et ignore les fichiers qui ont changé.

## Première utilisation

Crée deux dossiers séparés :

```text
MDJR_A_trier
MDJR_Classement
```

Dans Classeur, sélectionne le dossier d'arrivée et le dossier de classement. Lance d'abord l'analyse des fichiers déjà présents. Vérifie quelques propositions. Ensuite, démarre la surveillance pour les nouveaux fichiers.

Pour une première utilisation, garde le mode copie et le mode de revue. Il est préférable de tester sur une copie de ses documents importants.

## Tests

Depuis la racine du projet :

```bash
python -m pytest -q
```

Les scénarios d’intégration et les smoke tests peuvent être lancés ainsi :

```bash
PYTHONPATH=. python tests/integration_flow.py
PYTHONPATH=. python tests/realtime_simulation.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/smoke_gui.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/smoke_preferences.py
```

Le test graphique hors écran sous Linux :

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/smoke_gui.py
```

## Structure du projet

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée |
| `mdjr_classeur/app.py` | Composition de l’application et orchestration de l’interface |
| `mdjr_classeur/application/services.py` | Classification, scan et annulation |
| `mdjr_classeur/application/naming.py` | Proposition de noms fondés sur le contenu lisible |
| `mdjr_classeur/application/document_identity.py` | Empreintes binaires et signatures textuelles |
| `mdjr_classeur/application/duplicates.py` | Service applicatif de détection et traitement des doublons |
| `mdjr_classeur/domain/` | Modèles métier, chemins et planification |
| `mdjr_classeur/infrastructure/` | Fichiers, historique, SQLite et surveillance |
| `mdjr_classeur/presentation/` | Fenêtres, dialogues, modèle Qt et workers |
| `mdjr_classeur/classifier.py` | Classification et hiérarchie |
| `mdjr_classeur/search_index.py` | Recherche locale |
| `mdjr_classeur/cache.py` | Cache SQLite |
| `mdjr_classeur/preferences.py` | Préférences persistantes et validation |
| `mdjr_classeur/i18n.py` | Libellés français et anglais |
| `mdjr_classeur/dedupe.py` | Doublons et quarantaine |
| `mdjr_classeur/semantic.py` | Rapprochement local léger |
| `examples/regles_professionnelles.json` | Exemple de règles personnalisées |
| `HIERARCHIE.md` | Règles de construction de l'arborescence |
| `ARCHITECTURE.md` | Séparation des responsabilités et guide de contribution |
| `CONTRIBUTING.md` | Normes de contribution et de tests |
| `docs/GUIDE_UTILISATEUR.md` | Guide d’utilisation complet |
| `docs/DEPANNAGE.md` | Résolution des problèmes courants |
| `build_windows.bat` | Construction de l'exécutable Windows |
| `requirements.txt` | Dépendances |
| `tests/` | Tests automatisés |

## Limites connues

Les PDF scannés comme des images, les photos et certains formats fermés ne peuvent pas toujours être lus. Dans ce cas, Classeur affiche que l’analyse est limitée au nom et au chemin. Les documents très complexes, les tableaux et certains éléments non textuels peuvent encore être partiellement extraits. Une version avec OCR local pourrait améliorer ce point.

Chaque proposition indique maintenant si le contenu a été lu, s’il est absent ou illisible, ou si l’extension n’est pas prise en charge. Une confiance affichée reste un score heuristique, pas une garantie mathématique. Les documents importants doivent donc être vérifiés et sauvegardés.

Les dossiers source et destination doivent être séparés. Les fichiers temporaires de logiciels et de synchronisation courants sont ignorés pendant la surveillance. L’annulation peut restaurer toute la dernière session quand les fichiers n’ont pas été modifiés depuis le classement ; les fichiers changés sont volontairement laissés en place.

Classeur ne remplace pas une sauvegarde. Il est conseillé de garder une copie des documents importants.

## Licence

Le projet est distribué sous licence MIT. Voir le fichier `LICENSE`.

## Références techniques

- Python : https://docs.python.org/3/
- PySide6 : https://doc.qt.io/qtforpython/
- PyInstaller : https://pyinstaller.org/en/stable/
- pypdf : https://pypdf.readthedocs.io/en/stable/
- python-docx : https://python-docx.readthedocs.io/en/latest/
