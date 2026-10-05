"""Étape 1 : collecte des flux RSS/Atom, normalisation, routage vers les axes."""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

from . import db
from .config import Axis, Config, Feed
from .rank import matches_keywords

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (veille-tech homelab; +https://github.com/)"
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src|source$)")


def normalize_url(url: str) -> str:
    """Supprime trackers, fragment, slash final : sert de clé de déduplication."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower().removeprefix("www."), path, urlencode(query), ""))


def clean_text(raw: str | None, limit: int = 1500) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:limit]


def _entry_date(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        if entry.get(key):
            return datetime(*entry[key][:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def entry_link(entry) -> str | None:
    """Lien de l'article ; certains flux (ex. blog Hugging Face) n'ont que <guid>/<id>."""
    for candidate in (entry.get("link"), entry.get("id"), entry.get("guid")):
        if candidate and str(candidate).startswith(("http://", "https://")):
            return candidate
    return None


def parse_rss(feed: Feed, content: bytes) -> list[dict]:
    parsed = feedparser.parse(content)
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for e in parsed.entries:
        link = entry_link(e)
        title = clean_text(e.get("title"), 300)
        if not link or not title:
            continue
        items.append(
            {
                "url": normalize_url(link),
                "title": title,
                "summary": clean_text(e.get("summary") or e.get("description")),
                "source": feed.name,
                "source_weight": feed.weight,
                "published": _entry_date(e).isoformat(),
                "fetched_at": now,
            }
        )
    return items


def parse_cisa_kev(feed: Feed, content: bytes) -> list[dict]:
    """Catalogue CISA KEV (JSON) : une entrée par CVE activement exploitée."""
    data = json.loads(content)
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for v in data.get("vulnerabilities", []):
        cve = v.get("cveID")
        if not cve:
            continue
        added = datetime.fromisoformat(v.get("dateAdded", now[:10])).replace(tzinfo=timezone.utc)
        ransomware = " — utilisée par des ransomwares" if v.get("knownRansomwareCampaignUse") == "Known" else ""
        product = f"{v.get('vendorProject', '')} {v.get('product', '')}".strip()
        action = v.get("requiredAction", "")
        items.append(
            {
                "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
                "title": f"{cve} exploitée : {product} — {v.get('vulnerabilityName', '')}",
                "summary": f"{v.get('shortDescription', '')} Action requise : {action}{ransomware}",
                "source": feed.name,
                "source_weight": feed.weight,
                "published": added.isoformat(),
                "fetched_at": now,
            }
        )
    return items


PARSERS = {"rss": parse_rss, "cisa_kev": parse_cisa_kev}


def http_client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def get_with_retry(client: httpx.Client, url: str) -> httpx.Response:
    """Un seul nouvel essai sur 429/503, en respectant Retry-After (plafonné à 30 s)."""
    resp = client.get(url)
    if resp.status_code in (429, 503):
        try:
            wait = min(30.0, float(resp.headers.get("retry-after", 10)))
        except ValueError:
            wait = 10.0
        log.info("%s : HTTP %d, nouvel essai dans %.0f s", url, resp.status_code, wait)
        time.sleep(wait)
        resp = client.get(url)
    return resp


def fetch_feed(client: httpx.Client, feed: Feed) -> list[dict]:
    try:
        resp = get_with_retry(client, feed.url)
        resp.raise_for_status()
        items = PARSERS[feed.kind](feed, resp.content)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("flux %s inaccessible : %s", feed.name, e)
        return []
    log.info("%-28s %3d articles", feed.name, len(items))
    return items


def collect(cfg: Config, conn: sqlite3.Connection) -> int:
    """Récupère tous les flux et enregistre les articles. Renvoie le nombre de liens article/axe."""
    jobs: list[tuple[Feed, Axis | None]] = [(f, a) for a in cfg.axes.values() for f in a.feeds]
    jobs += [(f, None) for f in cfg.shared_feeds]

    with http_client() as client, ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: fetch_feed(client, j[0]), jobs))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg.pipeline.max_age_days)).isoformat()
    links = skipped = 0
    for (_feed, axis), items in zip(jobs, results, strict=True):
        for item in items:
            if item["published"] < cutoff:  # historique des flux (CISA KEV, archives complètes…)
                skipped += 1
                continue
            article_id = db.upsert_article(conn, item)
            if axis is not None:
                targets = [axis.key]
            else:  # flux partagé : routage par mots-clés
                text = f"{item['title']} {item['summary']}"
                targets = [a.key for a in cfg.axes.values() if matches_keywords(text, a.keywords)]
            for key in targets:
                db.link_axis(conn, article_id, key)
                links += 1
    conn.commit()
    log.info("%d articles ignorés car plus vieux que %d j", skipped, cfg.pipeline.max_age_days)
    return links
