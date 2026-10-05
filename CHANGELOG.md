# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Modifié
- Nouveau design du rapport et de l'historique (maquette Claude Design) : titre et résumé mis en avant, note de pertinence en information secondaire, bloc « L'essentiel », navigation entre rapports, historique groupé par mois avec répartition par axe.
- Résumé par article bien plus complet : champ `summary` de 5 à 8 phrases en plus de l'accroche, jusqu'à 5 points clés (`SUMMARY_VERSION` incrémentée : les résumés en cache sont régénérés).

## [0.1.0] - 2026-10-05

### Ajouté
- Pipeline de veille : collecte RSS/Atom par axe + flux partagés routés par mots-clés, déduplication et regroupement par sujet, pré-tri heuristique, notation et résumé par LLM local (API compatible OpenAI), synthèse par axe avec citations, résumé exécutif.
- Rapport HTML autonome (cartes, filtres, recherche, thème clair/sombre, impression), export Markdown et JSON, index de l'historique.
- Stockage SQLite de tous les liens ; `veille links` pour chercher dans l'historique, `veille prune` pour purger.
- `veille check-feeds` et `veille discover` pour tester les sources ; catalogue de ~75 sources annotées.
- Source `cisa_kev` (catalogue JSON des vulnérabilités exploitées ; les flux RSS CISA sont retirés depuis 05/2025).
- `veille export-opml` et banc de comparaison Miniflux / miniflux-ai / betternews (`bench/`).
- Outillage : ruff, pre-commit, CI GitHub Actions, dépendances figées (`requirements.lock`).

### Corrigé (suite au premier test réel)
- Notes LLM saturées (8-10) : notation par grille de critères oui/non, note calculée en Python.
- Cache LLM indexé par modèle et version de prompt.
- Résumé fait sur l'extrait RSS signalé (log + fiche).
- Articles anciens ignorés à la collecte (`max_age_days`), nouvel essai sur HTTP 429/503.
