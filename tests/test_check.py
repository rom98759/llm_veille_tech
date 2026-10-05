"""Tests hors-ligne de la vérification des sources (serveur HTTP simulé)."""

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import httpx

from veille.check import check_feed, discover_in_html
from veille.config import Feed, load_catalog

NOW = datetime.now(timezone.utc)


def rss(items):
    body = "".join(
        f"<item><title>{title}</title>{f'<link>{link}</link>' if link else ''}<guid>{guid}</guid>"
        f"<pubDate>{format_datetime(date)}</pubDate></item>"
        for title, link, guid, date in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


ROUTES = {
    "/ok": (200, "application/rss+xml", rss([("A", "https://ex.com/a", "1", NOW - timedelta(hours=3))])),
    "/hf": (200, "application/xml", rss([("Sans lien", None, "https://hf.co/blog/post", NOW)])),
    "/old": (200, "application/rss+xml", rss([("Vieux", "https://ex.com/v", "2", NOW - timedelta(days=200))])),
    "/blocked": (403, "text/html", "Forbidden"),
    "/page": (
        200,
        "text/html",
        '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>',
    ),
    "/kev": (
        200,
        "application/json",
        json.dumps(
            {
                "vulnerabilities": [
                    {
                        "cveID": "CVE-2026-1111",
                        "vendorProject": "Acme",
                        "product": "VPN",
                        "vulnerabilityName": "RCE",
                        "dateAdded": NOW.date().isoformat(),
                        "shortDescription": "Bug.",
                        "requiredAction": "Patcher.",
                        "knownRansomwareCampaignUse": "Known",
                    }
                ]
            }
        ),
    ),
}


def client():
    def handler(req):
        code, ctype, body = ROUTES.get(req.url.path, (404, "text/plain", "nope"))
        return httpx.Response(code, headers={"content-type": ctype}, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test")


def check(path, kind="rss"):
    return check_feed(client(), Feed(name=path, url=f"https://test{path}", kind=kind))


def test_ok():
    r = check("/ok")
    assert r["verdict"] == "OK" and r["items"] == 1 and r["status"] == 200


def test_feed_without_link_uses_guid():
    r = check("/hf")
    assert r["verdict"] == "OK" and r["items"] == 1


def test_stale_and_errors():
    assert check("/old")["verdict"] == "INACTIF"
    r = check("/blocked")
    assert r["verdict"] == "ERREUR" and r["status"] == 403 and "anti-bot" in r["detail"]
    assert check("/missing")["detail"] == "n'existe pas"


def test_html_page_suggests_feed():
    r = check("/page")
    assert r["verdict"] == "PAGE HTML" and "https://test/feed.xml" in r["detail"]


def test_cisa_kev_json():
    r = check("/kev", kind="cisa_kev")
    assert r["verdict"] == "OK" and r["items"] == 1


def test_discover_in_html_relative_and_atom():
    html = (
        '<link rel="alternate" type="application/atom+xml" href="/atom.xml">'
        '<link rel="stylesheet" href="/s.css"><link type="application/rss+xml" rel="alternate" href="https://x.org/rss">'
    )
    assert discover_in_html(html, "https://site.fr/blog/") == ["https://site.fr/atom.xml", "https://x.org/rss"]


def test_catalog_loads():
    cat = load_catalog(Path(__file__).resolve().parents[1] / "sources" / "catalog.yaml")
    feeds = [f for fs in cat.values() for f in fs]
    assert len(feeds) > 60 and all(f.url.startswith("https://") for f in feeds)
    assert any(f.kind == "cisa_kev" for f in feeds)
