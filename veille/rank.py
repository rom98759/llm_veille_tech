"""Étape 2a : regroupement des doublons et pré-tri heuristique (sans LLM, rapide)."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

_STOPWORDS_EN = "the a an of to in on for and or with is are was by from at as its it this that new how why"
_STOPWORDS_FR = "le la les des du de un une et ou en pour sur par avec est dans au aux"
STOPWORDS = frozenset(f"{_STOPWORDS_EN} {_STOPWORDS_FR}".split())


def matches_keywords(text: str, keywords: list[str]) -> list[str]:
    text = text.lower()
    return [k for k in keywords if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text)]


def title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.+-]*", title.lower()) if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def same_story(a: set[str], b: set[str], threshold: float = 0.5) -> bool:
    # Identifiants (CVE, versions...) différents => sujets différents, même si le titre est proche.
    ids_a, ids_b = {t for t in a if any(c.isdigit() for c in t)}, {t for t in b if any(c.isdigit() for c in t)}
    if ids_a and ids_b and not ids_a & ids_b:
        return False
    return jaccard(a, b) >= threshold


def cluster(items: list[dict], threshold: float = 0.5) -> list[list[dict]]:
    """Regroupe les articles qui parlent du même sujet (titres proches). Glouton, O(n²) suffisant ici."""
    clusters: list[tuple[set[str], list[dict]]] = []
    for it in items:
        toks = title_tokens(it["title"])
        for ctoks, members in clusters:
            if same_story(toks, ctoks, threshold):
                members.append(it)
                break
        else:
            clusters.append((toks, [it]))
    return [m for _, m in clusters]


def heuristic_score(item: dict, keywords: list[str], now: datetime | None = None) -> float:
    """Score = mots-clés × poids source × fraîcheur × couverture multi-sources."""
    now = now or datetime.now(timezone.utc)
    in_title = set(matches_keywords(item["title"], keywords))
    in_text = matches_keywords(f"{item['title']} {item.get('summary') or ''}", keywords)
    kw = sum(2.0 if k in in_title else 1.0 for k in in_text)
    age_h = max(0.0, (now - datetime.fromisoformat(item["published"])).total_seconds() / 3600)
    freshness = math.exp(-age_h / 48)  # demi-vie ~33h
    coverage = 1 + 0.5 * (item.get("coverage", 1) - 1)
    return round((1 + kw) * item.get("source_weight", 1.0) * (0.3 + freshness) * coverage, 3)


def preselect(items: list[dict], keywords: list[str], limit: int) -> list[dict]:
    """Déduplique par sujet, garde le meilleur représentant de chaque cluster, trie, coupe."""
    reps = []
    for members in cluster(items):
        for m in members:
            m["coverage"] = len({x["source"] for x in members})
            m["score_h"] = heuristic_score(m, keywords)
        best = max(members, key=lambda m: m["score_h"])
        best["related"] = [
            {"title": m["title"], "url": m["url"], "source": m["source"]} for m in members if m is not best
        ]
        reps.append(best)
    reps.sort(key=lambda m: m["score_h"], reverse=True)
    return reps[:limit]
