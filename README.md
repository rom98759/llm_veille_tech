# llm_veille_tech

Veille technologique 100 % locale : flux RSS → pré-tri → jugement et résumé par un LLM local → rapport Markdown/HTML/JSON sur un template commun, avec **tous les liens conservés** (SQLite).

## Pipeline

```
 1. COLLECTE            2. TRI                          3. COMPILATION                4. RENDU
 flux RSS/Atom   ─►  dédup URL + regroupement     ─►  extraction texte (trafilatura) ─►  rapport .md / .html / .json
 par axe +           par sujet (multi-sources)         résumé JSON par article          (template Jinja commun)
 flux partagés       score heuristique                 synthèse par axe avec [n]        + latest.html
 routés par          (mots-clés × poids source         résumé exécutif tous axes
 mots-clés           × fraîcheur × couverture)
                     top N ─► LLM note 0-10
                     selon ton profil
            └──────────────── tout est stocké dans SQLite (data/veille.db) ────────────────┘
```

- **Sources utiles** : un flux a un `weight` ; un sujet repris par plusieurs sources est boosté ; le LLM note chaque candidat par rapport au `profile` défini dans la config (ce qui t'intéresse / ce qui est du bruit). Seuls les articles ≥ `min_llm_score` sont résumés.
- **Économie de LLM** : le pré-tri heuristique limite à `candidates_per_axis` appels de notation par axe ; notes et résumés sont mis en cache en base, une relance ne refait que le nouveau.
- **Traçabilité** : chaque affirmation de synthèse cite `[n]` → ancre vers la fiche article → lien source. Les candidats écartés sont listés avec leur note et la raison (« Autres liens évalués »). L'historique complet reste interrogeable.

## Installation

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
cp config.example.yaml config.yaml     # définir axes, flux, profil, modèle

# LLM local (exemple Ollama)
ollama pull qwen2.5:7b-instruct
```

Tout serveur compatible OpenAI fonctionne (`llm.base_url`) : Ollama, llama.cpp `llama-server`, LM Studio, vLLM.
Modèles conseillés (bon suivi d'instructions + JSON, multilingue) : `qwen2.5:7b-instruct`, `llama3.1:8b`, `mistral-nemo`, `gemma2:9b`. Sur CPU seul, un 3-4B (`qwen2.5:3b`, `phi3.5`) passe mais les synthèses sont plus pauvres.

## Utilisation

```bash
veille collect                 # récupère les flux (à lancer souvent, ex. toutes les 2 h)
veille report                  # trie + résume + génère reports/veille-<date>.{md,html,json}
veille run                     # collect + report
veille run --axis cyber        # un seul axe

# Creuser : recherche dans tout l'historique collecté
veille links kubernetes --days 30
veille links --axis cyber --min-score 7
```

### Vérifier les sources (à faire en premier)

```bash
veille check-feeds                                   # sources de config.yaml
veille check-feeds --catalog sources/catalog.yaml --out reports/sources.md   # ~80 sources candidates
veille check-feeds --catalog sources/catalog.yaml --group cyber_fr
veille discover cyberveille.esante.gouv.fr next.ink  # trouver le flux d'un site
```

Chaque source est réellement téléchargée et parsée avec le même code que la collecte :

| Verdict | Signification |
|---|---|
| ✅ OK | flux valide, articles avec titre + lien, dernier article < 30 j (`--stale-days`) |
| 💤 INACTIF | flux valide mais plus alimenté |
| 🔎 PAGE HTML | l'URL est une page, pas un flux — les flux déclarés par la page sont proposés |
| ⚠️ VIDE | flux lisible mais aucun article exploitable |
| ❌ ERREUR | 403 (anti-bot/Cloudflare), 404, 429, timeout, DNS… |

`sources/catalog.yaml` : sources par thème (agrégateurs, tech, tech FR, IA, recherche, cyber, cyber FR, homelab, releases GitHub) avec une note `web` (URL confirmée par recherche) ou `à tester`. Copier les ✅ utiles dans `config.yaml`.

Points connus :
- **CISA** a retiré ses flux RSS (mai 2025) → source `kind: cisa_kev` qui lit le catalogue JSON des vulnérabilités activement exploitées.
- **Anthropic** n'a pas de flux officiel → flux communautaires (GitHub) dans le catalogue.
- **Hugging Face** : items sans `<link>` → repli automatique sur `<guid>`.
- **Reddit** : `www.reddit.com/r/<sub>/.rss` fonctionne, `old.reddit.com` exige un login ; 403 possibles selon l'IP.
- **Phoronix, Cloudflare** : protection anti-bot, 403 fréquents depuis des IP de datacenter (moins depuis une IP résidentielle).

### Planification

cron :
```
0 */2 * * *  cd /opt/llm_veille_tech && .venv/bin/veille collect
30 7 * * *   cd /opt/llm_veille_tech && .venv/bin/veille report
```

Docker :
```bash
docker compose up -d ollama web
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose run --rm veille run      # avec base_url: http://ollama:11434/v1
# rapport : http://<lab>:8080/latest.html
```

## Ajouter un axe

Dans `config.yaml`, sous `axes:` :

```yaml
  homelab:
    title: Homelab & self-hosting
    description: Proxmox, NAS, réseau, domotique.
    keywords: [proxmox, truenas, homelab, self-hosted, opnsense, wireguard]
    feeds:
      - {name: r/selfhosted, url: "https://www.reddit.com/r/selfhosted/top/.rss?t=day"}
```

`keywords` sert au pré-tri et au routage des `shared_feeds` (HN, Lobsters…) ; `description` est donnée au LLM pour juger la pertinence.
Sources sans RSS : beaucoup de sites en ont un caché (`/feed`, `/rss`, `/atom.xml`) ; sinon [RSS-Bridge](https://github.com/RSS-Bridge/rss-bridge) auto-hébergé, ou `hnrss.org`, `reddit.com/r/<sub>/.rss`, chaînes YouTube (`/feeds/videos.xml?channel_id=`), releases GitHub (`/<owner>/<repo>/releases.atom`).

## Personnaliser

- Rapport : `veille/templates/report.md.j2` (le HTML est dérivé du Markdown, style dans `report.html.j2`).
- Prompts : `veille/prompts.py` (courts et cadrés pour modèles 7-9B).
- Données brutes pour analyse : `sqlite3 data/veille.db` — tables `articles` (texte complet, résumé JSON), `article_axes` (notes par axe), `reports` (JSON de chaque rapport).

## Tests

```bash
pip install -e '.[dev]' && pytest
```
