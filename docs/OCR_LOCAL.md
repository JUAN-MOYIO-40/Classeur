# OCR local des PDF scannés

## Principe

Un PDF textuel peut être lu directement par `pypdf`. Un PDF scanné contient généralement des images de pages et ne fournit pas de texte exploitable par cette méthode. Classeur utilise alors, lorsque les outils sont installés, un OCR local avec Tesseract et Poppler.

Le document reste sur l’ordinateur. Aucun service distant n’est appelé par ce pipeline.

## Outils nécessaires

| Outil | Rôle |
|---|---|
| Tesseract OCR | Reconnaître les caractères dans les images |
| Pack de langue français | Améliorer la reconnaissance du français |
| Poppler | Convertir les pages PDF en images |

L’OCR est optionnel. Si l’un des outils manque, Classeur conserve le document, indique `OCR indisponible` et n’invente pas de contenu.

## Linux Ubuntu

```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-fra poppler-utils
```

Vérifie ensuite :

```bash
tesseract --list-langs
pdftoppm -v
```

Les langues `fra` et `eng` sont recommandées.

## Windows

Installe une distribution Windows de Tesseract contenant le pack français, puis une distribution Windows de Poppler. Ajoute les dossiers contenant `tesseract.exe` et `pdftoppm.exe` à la variable d’environnement `PATH`.

Ferme puis rouvre le terminal et vérifie :

```powershell
tesseract --list-langs
pdftoppm -v
```

La construction de Classeur reste possible sans ces outils. Dans ce cas, l’application fonctionne pour les fichiers texte et les PDF textuels, mais les PDF scannés sont signalés comme non lus.

## Limites et prudence

Pour limiter les temps de traitement, Classeur rasterise un nombre de pages limité et utilise une résolution contrôlée. Les documents très volumineux, flous, inclinés, manuscrits ou protégés peuvent produire un texte incomplet ou incorrect.

Le statut **contenu lu par OCR local** indique qu’un texte a été obtenu, pas qu’il est parfait. Il faut vérifier l’extrait, la proposition de classement et le nom proposé avant un déplacement ou un classement automatique.

L’OCR n’est pas une preuve d’identité documentaire. Une empreinte SHA-256 reste nécessaire pour reconnaître les fichiers binaires identiques. Les signatures textuelles issues d’un OCR doivent être considérées comme prudentes, car une erreur de reconnaissance peut modifier le texte.
