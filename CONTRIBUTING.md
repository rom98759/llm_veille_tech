# Contribuer

## Mise en place

```bash
python -m venv .venv && . .venv/bin/activate
make install          # dépendances figées + outils de dev + hook pre-commit
```

## Avant chaque commit

```bash
make check            # ruff (lint + format) + pytest — c'est ce que lance la CI
make format           # corrige automatiquement ce qui peut l'être
```

Le hook pre-commit lance ruff et quelques vérifications (espaces, YAML/TOML, clés privées, gros fichiers).

## Branches et commits

- `master` est la branche stable : on n'y pousse pas directement, on passe par une PR dont la CI est verte.
- Une branche par sujet : `feat/…`, `fix/…`, `docs/…`, `chore/…`.
- Messages au format [Conventional Commits](https://www.conventionalcommits.org/fr/), description en français :
  `feat(report): filtre par source`, `fix(collect): nouvel essai sur HTTP 429`, `docs: choix du modèle`.
  Types : `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `build`, `ci`, `chore`.
- Une modification de comportement visible va dans `CHANGELOG.md` (section « Non publié »).

## Conventions du code

- Python ≥ 3.10, typé, style imposé par ruff (`pyproject.toml`).
- Modifier un prompt dans `veille/prompts.py` → incrémenter `JUDGE_VERSION` / `SUMMARY_VERSION` (invalide le cache LLM).
- Le rapport HTML reste autonome : aucune ressource externe (CDN, polices, scripts) ; un test le vérifie.
- Pas d'appel réseau ni de LLM dans les tests : serveur HTTP simulé (`httpx.MockTransport`) et faux LLM (`monkeypatch`).

## Dépendances

Ajouter la dépendance dans `pyproject.toml` (avec borne de version majeure), puis régénérer le lock :

```bash
pip install -e . && pip freeze --exclude-editable | grep -vE '^(pytest|iniconfig|pluggy|Pygments|ruff|pre-commit|cfgv|identify|nodeenv|virtualenv|distlib|filelock|platformdirs)==' > requirements.lock
```
