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
- repérer les doublons exacts par contenu
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

## Recherche rapide

Le bouton `Recherche rapide` recherche dans les noms, chemins, années, domaines, matières, thèmes, catégories et extraits de contenu. Les accents sont normalisés. Une recherche comme `scolarite` peut retrouver `scolarité`.

La recherche fonctionne avec un index SQLite local. Les fichiers inchangés ne sont pas relus inutilement. Il est possible de filtrer les résultats par statut, d'ouvrir le fichier ou d'afficher son dossier.

## Doublons

Le bouton `Scanner les doublons` compare les contenus. Deux fichiers sont considérés comme identiques seulement si leur contenu binaire est le même. Les noms seuls ne suffisent pas.

Le moteur compare d'abord la taille, puis une empreinte rapide, puis calcule le SHA-256 complet pour les candidats. Les dossiers qui contiennent les mêmes fichiers peuvent aussi être signalés.

La suppression automatique est désactivée. Le choix recommandé est la quarantaine réversible. La suppression définitive demande une action séparée et une confirmation. Avant une quarantaine ou une suppression, Classeur vérifie que l’empreinte du fichier n’a pas changé depuis le scan.

## Profils de fonctionnement

| Profil | Utilisation | Ressources |
|---|---|---|
| Lite | Nom, chemin et règles simples | Faible |
| Standard | Cache, contenu lisible et surveillance événementielle | Recommandé |
| Sémantique locale | Rapprochement léger pour les cas difficiles | Activé seulement si nécessaire |

Classeur n'embarque pas de grand modèle génératif dans la version standard. Le moteur local est déterministe et plus léger. Il est plus facile à expliquer et il ne demande pas de connexion.

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

Le test graphique hors écran sous Linux :

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/smoke_gui.py
```

## Structure du projet

| Fichier | Rôle |
|---|---|
| `main.py` | Point d'entrée |
| `mdjr_classeur/app.py` | Interface, surveillance et opérations |
| `mdjr_classeur/classifier.py` | Classification et hiérarchie |
| `mdjr_classeur/search_index.py` | Recherche locale |
| `mdjr_classeur/cache.py` | Cache SQLite |
| `mdjr_classeur/dedupe.py` | Doublons et quarantaine |
| `mdjr_classeur/semantic.py` | Rapprochement local léger |
| `examples/regles_professionnelles.json` | Exemple de règles personnalisées |
| `HIERARCHIE.md` | Règles de construction de l'arborescence |
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
