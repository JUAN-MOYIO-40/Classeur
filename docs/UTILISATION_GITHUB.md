# Utiliser GitHub avec Classeur

Ce guide explique les commandes de base pour récupérer Classeur, le modifier et publier une amélioration.

## 1. Installer les outils

Installe Git depuis https://git-scm.com/downloads et GitHub CLI depuis https://cli.github.com/ si tu veux travailler avec les commandes `gh`.

Vérifie ensuite l'installation :

```powershell
git --version
gh --version
```

Connecte GitHub une seule fois :

```powershell
gh auth login
```

Choisis GitHub.com, HTTPS et la connexion avec le navigateur.

## 2. Récupérer Classeur

Après la publication du dépôt, utilise :

```powershell
gh repo clone TON_COMPTE/Classeur
cd Classeur
```

Tu peux aussi utiliser le bouton `Code` sur la page GitHub, puis choisir `Download ZIP`.

## 3. Comprendre les fichiers principaux

| Fichier | Utilité |
|---|---|
| `README.md` | Présentation et installation |
| `mdjr_classeur/classifier.py` | Règles et classification |
| `mdjr_classeur/app.py` | Interface et surveillance |
| `examples/regles_professionnelles.json` | Exemple de règles métier |
| `tests/` | Tests du projet |
| `build_windows.bat` | Création de l'application Windows |

## 4. Modifier une règle

Copie l'exemple :

```powershell
copy examples\regles_professionnelles.json regles.json
```

Ajoute ensuite des mots clés dans la bonne section. Les mots doivent être suffisamment précis. Après la modification, redémarre l'application et relance une analyse.

Un exemple pour une petite activité :

```json
{
  "subjects": {
    "Clients": ["client", "prospect", "contact"]
  },
  "categories": {
    "Contrats": ["contrat", "avenant"],
    "Factures": ["facture", "paiement"]
  },
  "domains": {
    "Commercial": ["vente", "prospection", "offre"]
  },
  "topics": {
    "Assurance": ["assurance", "garantie", "sinistre"]
  }
}
```

## 5. Tester avant de publier

Depuis la racine du projet :

```powershell
python -m pytest -q
```

Une modification est prête à être publiée si les tests passent et si l'application démarre correctement.

## 6. Publier une modification

Vérifie les fichiers modifiés :

```powershell
git status
git diff
```

Ajoute les fichiers et crée un commit :

```powershell
git add .
git commit -m "Ajout de règles professionnelles"
```

Envoie la modification :

```powershell
git push
```

Un commit doit décrire une seule amélioration. Les messages simples sont suffisants :

```text
Ajout des règles pour les contrats
Amélioration de la recherche locale
Correction du classement des relevés
```

## 7. Trouver des dépôts intéressants

Sur GitHub, utilise la recherche avec des termes simples :

```text
language:Python artificial intelligence stars:>1000
language:Python document management stars:>500
language:Python local AI stars:>500
language:Python semantic search stars:>1000
```

Tu peux aussi ouvrir directement :

```text
https://github.com/search?q=language%3APython+artificial+intelligence+stars%3A%3E1000&type=repositories
```

Dans les résultats, regarde la date du dernier commit, la licence, la documentation, le nombre de contributeurs et les issues ouvertes. Beaucoup d'étoiles ne garantissent pas que le projet est encore maintenu.

Pour suivre les projets populaires, utilise la page Trending :

```text
https://github.com/trending
```

Pour chercher depuis un terminal :

```powershell
gh search repos "document management" --language Python --stars ">500"
gh search repos "local AI" --language Python --stars ">500"
```

## 8. Dépôts à consulter

Les projets suivants sont connus dans leurs domaines respectifs. Vérifie toujours leur licence et leur activité directement sur GitHub avant de les utiliser.

| Projet | Domaine | Lien |
|---|---|---|
| Transformers | Modèles de langage et de vision | https://github.com/huggingface/transformers |
| llama.cpp | Exécution locale de modèles | https://github.com/ggml-org/llama.cpp |
| Ollama | Utilisation locale de modèles | https://github.com/ollama/ollama |
| scikit-learn | Apprentissage automatique classique | https://github.com/scikit-learn/scikit-learn |
| LangChain | Applications avec modèles de langage | https://github.com/langchain-ai/langchain |
| Haystack | Recherche et systèmes question-réponse | https://github.com/deepset-ai/haystack |

Le nombre d'étoiles et l'activité évoluent. La commande suivante permet de vérifier les chiffres actuels :

```powershell
gh repo view huggingface/transformers --json nameWithOwner,stargazerCount,pushedAt,licenseInfo
```

## 9. Règles de sécurité

Ne mets jamais de clé API, mot de passe, document personnel ou fichier de configuration privé dans Git. Utilise un fichier `.env` ignoré par Git et fournis un exemple sans secret dans `.env.example`.

Avant chaque publication, vérifie :

```powershell
git status
git diff --cached
```

Si une clé a été publiée par erreur, considère-la comme compromise et révoque-la immédiatement auprès du service concerné.

## 10. Style du dépôt

Le dépôt Classeur utilise volontairement une présentation simple. La documentation doit rester directe, précise et personnelle. Il vaut mieux expliquer une limite clairement que promettre une fonction qui n'existe pas. Les tirets longs ne sont pas utilisés dans les documents publics.
