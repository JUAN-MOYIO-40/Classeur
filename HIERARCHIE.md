# Vision de l’arborescence hiérarchique de MDJR classeur

MDJR ne doit pas imposer une profondeur fixe à tous les utilisateurs. Il construit une hiérarchie adaptative à partir du contexte détecté dans le nom, le chemin et le contenu du document.

## Niveaux possibles

| Niveau | Exemple étudiant | Exemple professionnel | Règle d’apparition |
|---|---|---|---|
| Année / période | `Année 1`, `2024-2025` | `2025`, `T1` | Créé uniquement si une année ou période fiable est détectée |
| Domaine | `Sciences` | `Administratif`, `Finance` | Ajouté si le domaine est suffisamment identifiable |
| Matière / espace | `Physique` | `Ressources humaines` | Niveau principal déduit par le moteur |
| Thème | `Électromagnétisme` | `Contrats` | Ajouté seulement lorsqu’un thème précis est détecté |
| Nature | `Cours`, `TD`, `Relevé de notes` | `Facture`, `Rapport` | Toujours présent comme dernier niveau utile |

## Exemples de résultats

```text
MDJR_Classement/
└── Année 1/
    └── Sciences/
        └── Physique/
            └── Électromagnétisme/
                └── Cours/
                    └── Champs électriques et lois de Gauss.pdf
```

```text
MDJR_Classement/
└── Année 2/
    └── Sciences/
        └── Mathématiques/
            └── Analyse/
                └── TD/
                    └── Séries et intégrales.pdf
```

```text
MDJR_Classement/
└── Administratif/
    └── Scolarité/
        └── Relevé de notes/
            └── Relevé de notes 2024.pdf
```

```text
MDJR_Classement/
└── 2025/
    └── Économie et gestion/
        └── Finance/
            └── Budget familial/
                └── Documents administratifs/
                    └── Budget familial 2025.pdf
```

```text
MDJR_Classement/
└── 2025/
    └── Économie et gestion/
        └── Marketing/
            └── Projet/
                └── Rapport de campagne.docx
```

## Principes de sécurité et de lisibilité

MDJR ne crée pas un dossier pour chaque mot trouvé. Un niveau n’est ajouté que si son score de confiance dépasse un seuil. La profondeur maximale est limitée par défaut à cinq niveaux afin d’éviter une arborescence illisible. Les dossiers existants sont rapprochés sémantiquement avant toute création. Les propositions restent visibles et annulables. Lorsqu’aucune matière fiable n’est trouvée, ou lorsque deux matières sont presque à égalité, la proposition est marquée **à vérifier** et ne doit pas être automatisée sans validation. Un document générique peut conserver uniquement sa nature, mais il reste alors traçable dans la file de revue.

Pour un usage non étudiant, le niveau `Année` devient une période lorsqu’elle est présente ; sinon il est omis. Les catégories génériques restent disponibles afin que la même application puisse organiser des documents personnels, administratifs, professionnels ou associatifs.
