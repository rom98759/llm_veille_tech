# Instructions projet — llm_veille_tech

Ce fichier prime sur les préférences globales pour ce dépôt.

## Commits

- Format [Conventional Commits](https://www.conventionalcommits.org/) : `type(scope): résumé court à l'impératif`
  (`feat`, `fix`, `refactor`, `docs`, `style`, `test`, `build`, `chore`).
- Résumé en français ; corps de commit en français, qui explique le *pourquoi*, pas juste le *quoi*
  (le diff montre déjà le quoi).
- **Jamais** de ligne d'attribution IA (`Co-Authored-By: Claude...`, `Claude-Session: ...`,
  ou équivalent) dans les messages de commit — le dépôt est public, l'usage de l'IA est mentionné
  une fois dans le README, pas répété sur chaque commit.
- Un commit = un changement logique cohérent. Pas de commits "wip" ou "fix typo" qui cassent la
  lisibilité de l'historique : squasher avant de pousser si besoin.

## Code

- Python : ruff (lint + format) doit passer sans erreur avant tout commit (`make check`).
- Commentaires et identifiants en anglais, docstrings/commentaires seulement quand le *pourquoi*
  n'est pas évident du code.
- Pas de dépendance ajoutée sans raison claire (cf. `pyproject.toml`, déjà minimal).

## Documentation

- `README.md` est la vitrine du projet (portfolio) : garder à jour les captures d'écran dans
  `docs/screenshots/` si le rendu HTML change visuellement.
- `CHANGELOG.md` suit [Keep a Changelog](https://keepachangelog.com/) — une entrée par changement
  notable, pas par commit.
