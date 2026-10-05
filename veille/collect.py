"""Étape 1 : collecte des flux RSS/Atom, normalisation, routage vers les axes."""
from __future__ import annotations

import html
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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


def fetch_feed(client: httpx.Client, feed: Feed) -> list[dict]:
    try:
        resp = client.get(feed.url)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("flux %s inaccessible : %s", feed.name, e)
        return []
    parsed = feedparser.parse(resp.content)
    now = datetime.now(timezone.utc).isoformat()
    items = []
    for e in parsed.entries:
        link = e.get("link")
        title = clean_text(e.get("title"), 300)
        if not link or not title:
            continue
        items.append({
            "url": normalize_url(link),
            "title": title,
            "summary": clean_text(e.get("summary") or e.get("description")),
            "source": feed.name,
            "source_weight": feed.weight,
            "published": _entry_date(e).isoformat(),
            "fetched_at": now,
        })
    log.info("%-28s %3d articles", feed.name, len(items))
    return items


def collect(cfg: Config, conn: sqlite3.Connection) -> int:
    """Récupère tous les flux et enregistre les articles. Renvoie le nombre de liens article/axe."""
    jobs: list[tuple[Feed, Axis | None]] = [(f, a) for a in cfg.axes.values() for f in a.feeds]
    jobs += [(f, None) for f in cfg.shared_feeds]

    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda j: fetch_feed(client, j[0]), jobs))

    links = 0
    for (feed, axis), items in zip(jobs, results):
        for item in items:
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
    return links
