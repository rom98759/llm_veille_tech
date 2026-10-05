# Banc de comparaison : Miniflux / miniflux-ai / betternews vs `llm_veille_tech`

Objectif : décider si on garde notre collecte, si on la remplace par Miniflux (notre code devenant une simple couche « digest »), ou si un projet existant suffit tel quel.

Règle : **mêmes flux, même modèle, même fenêtre** pour tout le monde.

## 0. Préparation commune

```bash
# depuis la racine du dépôt
veille export-opml --out bench/feeds.opml      # flux de config.yaml, une catégorie par axe (CISA KEV ignoré : JSON, pas RSS)
OLLAMA_HOST=0.0.0.0 ollama serve               # ou override systemd : Environment="OLLAMA_HOST=0.0.0.0"
```

Modèle : `qwen3-4b:latest` (référence du premier test), puis refaire le point 3 avec `qwen3.8-27b-uncensored` : en 4B, les synthèses étaient trop pauvres pour juger les outils plutôt que le modèle.

## 1. Miniflux seul (collecte + lecture) — ~10 min

```bash
cd bench
cp miniflux-ai.config.yml config.yml && touch entries.json
docker compose up -d miniflux db
```

1. http://localhost:8081 → `admin` / `veille-bench`
2. Paramètres → Importer → `feeds.opml`
3. Attendre une collecte (ou « Actualiser tous les flux »)
4. Paramètres → Clés d'API → créer une clé, la mettre dans `bench/config.yml`

À relever :
- flux en erreur (page « Flux » → filtre erreurs) vs notre `veille check-feeds` (17/17 OK chez toi, Reddit 429 à la collecte) ;
- volume ingéré (Miniflux ne récupère que le contenu courant du flux, pas d'historique de type CISA KEV 1734 lignes) ;
- texte complet : Paramètres d'un flux → « Récupérer le contenu original », à comparer à notre extraction trafilatura ;
- recherche, filtres par catégorie, marquage lu/favori : couvre-t-il le besoin « garder tous les liens pour creuser » ?

## 2. miniflux-ai (résumé par article + digest « AI news ») — ~20 min

```bash
docker compose up -d miniflux_ai
docker compose logs -f miniflux_ai
```

- Les résumés sont insérés **en tête du contenu des articles non lus** dans Miniflux (bloc « 🤖 Résumé IA »).
- Digest : dans Miniflux, s'abonner à `http://miniflux_ai/rss/ai-news` (généré aux heures de `ai_news.schedule` ; pour tester tout de suite, mettre une heure proche puis `docker compose restart miniflux_ai`).
- Santé des flux : s'abonner à `http://miniflux_ai/rss/feeds-status`.

À relever : temps pour traiter N articles non lus, qualité des résumés FR, structure du digest (par axe ? sources citées ? liens conservés ?), possibilité de filtrer selon un profil (a priori : non, il résume tout ce qui n'est pas en `deny_list`).

## 3. betternews (notation par profil + résumés) — ~20 min, optionnel

Lecteur Flask + Ollama qui note chaque article selon un profil appris (j'aime / j'aime pas). Le plus proche de notre étape de tri.

```bash
git clone https://github.com/sxntixgo/betternews && cd betternews
cp .env.example .env    # FLASK_SECRET_KEY=<aléatoire>, OLLAMA_HOST=http://host.docker.internal:11434,
                        # SCORING_MODEL=qwen3-4b:latest, SUMMARY_MODEL=qwen3-4b:latest
docker compose up --build    # http://localhost:5001 → Manage Feeds → import feeds.opml
```

(Le README parle aussi d'un dépôt `rss-reader` : si le clone échoue, prendre l'URL donnée sur la page GitHub.)

À relever : la notation se disperse-t-elle mieux que la nôtre (chez nous 18/18 entre 8 et 10) ? combien de votes faut-il pour un profil utile ?

## 4. Référence : `llm_veille_tech`

```bash
veille collect && time veille report
```

## 5. Grille de décision

Sur la même fenêtre (ex. dernières 48 h), prendre **20 articles au hasard** dans la collecte et noter à la main ceux qui méritaient le rapport. Puis pour chaque outil :

| Critère | Miniflux seul | + miniflux-ai | betternews | llm_veille_tech |
|---|---|---|---|---|
| Installation (min) | | | | |
| Flux OK / total | | | | |
| Collecte : doublons inter-sources regroupés ? | | | | |
| Sélection : précision sur les 20 (retenus pertinents / retenus) | | | | |
| Sélection : rappel (pertinents retenus / pertinents) | | | | |
| Dispersion des scores (min–max) | – | – | | 8–10 |
| Qualité résumé FR (1-5) | – | | | |
| Rapport par axe avec synthèse + citations | non | | | oui |
| Liens écartés conservés avec raison | – | | | oui |
| Historique consultable / recherche | | | | `veille links` |
| Temps LLM à froid | – | | | 7 min 30 (qwen3-4b) |
| Maintenance (projet actif ? dernier commit) | | | | nous |

Dernier commit upstream au 2026-10-05 : miniflux-ai 2026-05-20 (≈ 4,5 mois) — à vérifier pour betternews.

## 6. Issues possibles

- **Miniflux couvre la collecte et la lecture** → on branche notre couche digest sur l'API Miniflux (`GET /v1/entries?category_id=…&published_after=…`) : suppression de `collect.py`, `check.py` et de la table `articles` ; on garde tri/LLM/rapport.
- **miniflux-ai suffit** → on s'arrête là (son digest n'est pas par axe et ne cite pas ses sources : à juger).
- **Rien n'apporte assez** → on garde l'outil actuel, avec les correctifs du rapport de test.
