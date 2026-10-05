"""Vérification réelle des sources : accessibilité, format, fraîcheur, liens exploitables.

Utilise exactement le même parseur que la collecte : si un flux passe ici, il passera en prod.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx

from .collect import PARSERS, http_client
from .config import Feed

COMMON_PATHS = ["/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml", "/blog/rss.xml",
                "/blog/feed", "/blog/feed.xml", "/feeds/posts/default", "/rss/"]
FEED_TYPES = ("rss", "atom", "xml")


def check_feed(client: httpx.Client, feed: Feed, stale_days: int = 30) -> dict:
    res = {"name": feed.name, "url": feed.url, "kind": feed.kind, "status": None, "verdict": "ERREUR",
           "items": 0, "latest": None, "age_days": None, "ms": None, "detail": "", "final_url": None}
    t0 = time.monotonic()
    try:
        resp = client.get(feed.url)
    except httpx.HTTPError as e:
        res["detail"] = f"{type(e).__name__}: {e}"[:160]
        return res
    res["ms"] = int((time.monotonic() - t0) * 1000)
    res["status"] = resp.status_code
    if str(resp.url) != feed.url:
        res["final_url"] = str(resp.url)
    ctype = resp.headers.get("content-type", "")
    if resp.status_code >= 400:
        res["detail"] = {403: "refusé (anti-bot / géo / UA)", 404: "n'existe pas", 429: "rate-limit"}.get(
            resp.status_code, resp.reason_phrase)
        return res

    try:
        items = PARSERS[feed.kind](feed, resp.content)
    except ValueError as e:
        res["detail"] = f"contenu illisible : {e}"[:160]
        return res

    if not items:
        if "html" in ctype:
            found = discover_in_html(resp.text, str(resp.url))
            res["verdict"] = "PAGE HTML"
            res["detail"] = ("flux détecté : " + ", ".join(found[:3])) if found else "page HTML, aucun flux déclaré"
        else:
            res["verdict"] = "VIDE"
            res["detail"] = "aucun article exploitable (pas de titre/lien)"
        return res

    latest = max(datetime.fromisoformat(i["published"]) for i in items)
    age = (datetime.now(timezone.utc) - latest).total_seconds() / 86400
    res.update(items=len(items), latest=latest.isoformat()[:10], age_days=round(age, 1))
    res["verdict"] = "OK" if age <= stale_days else "INACTIF"
    if res["verdict"] == "INACTIF":
        res["detail"] = f"dernier article il y a {age:.0f} j"
    return res


def check_feeds(feeds: list[Feed], stale_days: int = 30) -> list[dict]:
    with http_client() as client, ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda f: check_feed(client, f, stale_days), feeds))


def discover_in_html(html: str, base_url: str) -> list[str]:
    """Liens <link rel="alternate" type="application/rss+xml|atom+xml"> déclarés par la page."""
    found = []
    for tag in re.findall(r"<link\b[^>]*>", html, re.I):
        if not re.search(r"rel=[\"']?alternate", tag, re.I):
            continue
        typ = re.search(r"type=[\"']([^\"']+)", tag, re.I)
        href = re.search(r"href=[\"']([^\"']+)", tag, re.I)
        if typ and href and any(t in typ.group(1).lower() for t in FEED_TYPES):
            url = urljoin(base_url, href.group(1))
            if url not in found:
                found.append(url)
    return found


def discover(site: str) -> list[dict]:
    """Trouve les flux d'un site : balises <link> de la page puis chemins usuels. Chaque candidat est testé."""
    if not site.startswith("http"):
        site = "https://" + site
    root = "{0.scheme}://{0.netloc}".format(urlsplit(site))
    candidates: list[str] = []
    with http_client() as client:
        try:
            resp = client.get(site)
            if "xml" in resp.headers.get("content-type", ""):
                candidates.append(str(resp.url))  # l'URL donnée est déjà un flux
            else:
                candidates += discover_in_html(resp.text, str(resp.url))
        except httpx.HTTPError:
            pass
        candidates += [root + p for p in COMMON_PATHS if root + p not in candidates]
        results = [check_feed(client, Feed(name=u, url=u)) for u in candidates]
    # dédoublonne par URL finale et ne garde que ce qui contient des articles
    seen, out = set(), []
    for r in results:
        key = r["final_url"] or r["url"]
        if r["items"] and key not in seen:
            seen.add(key)
            out.append(r)
    return out
