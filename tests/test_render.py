"""Rendu HTML/Markdown, parsing RSS, notation par grille, dégradations LLM, cache par modèle."""

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from veille import collect, db, process, report
from veille.config import Feed, load_config
from veille.llm import LLM

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc)


def _item(n, score, **kw):
    it = {
        "id": n,
        "title": f"Titre {n}",
        "url": f"https://ex.com/{n}",
        "source": "Src",
        "published": NOW.isoformat(),
        "llm_score": score,
        "llm_reason": "raison",
        "criteria": {"new_fact": True, "major": True},
        "score_h": 1.0,
        "coverage": 1,
        "related": [],
        "digest": {
            "tldr": "Accroche **gras**",
            "summary": "Premier paragraphe.\n\nSecond paragraphe.",
            "key_points": ["a"],
            "why_it_matters": "b",
            "tags": ["cve"],
            "text_source": "page",
        },
    }
    it.update(kw)
    return it


def sample():
    evil = _item(
        3,
        8.5,
        title='<script>alert(1)</script> & "x"',
        digest={
            "tldr": "<img src=x onerror=alert(1)>",
            "key_points": [],
            "why_it_matters": "",
            "tags": [],
            "text_source": "rss",
        },
    )
    return {
        "generated_at": NOW.isoformat(timespec="minutes"),
        "since": NOW.isoformat()[:16],
        "model": "m",
        "executive_summary": "- Point [cyber:1]\n- Autre [cyber:9]",
        "axes": [
            {
                "key": "cyber",
                "title": "Cybersécurité",
                "description": "d",
                "synthesis": "Faits [1][3] puis [1] et [7].",
                "items": [_item(1, 9.5), _item(2, 7.5, coverage=3), evil],
                "others": [_item(4, 2.0, llm_reason="hors sujet")],
                "total_collected": 10,
            }
        ],
    }


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.hrefs, self.scripts = [], [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#") and len(a["href"]) > 1:
            self.hrefs.append(a["href"][1:])
        if tag == "script":
            self.scripts += 1


def test_html_structure_anchors_and_escaping(tmp_path):
    data = sample()
    _, html_path, js = report.render(data, tmp_path, prev="veille-avant.html", number=7)
    html = html_path.read_text()
    p = Collector()
    p.feed(html)

    assert len(set(p.ids)) == len(p.ids), "ids dupliqués"
    assert set(p.hrefs) <= set(p.ids), f"ancres mortes : {set(p.hrefs) - set(p.ids)}"
    assert html.count('<article class="card"') == 3
    assert 'data-axis="cyber" data-score="9.5"' in html
    # citations : [7] et [cyber:9] n'existent pas -> laissées telles quelles
    # synthèse : [7] n'existe pas -> laissé tel quel ; résumé exécutif : [cyber:9] invalide -> retiré, pas de pastille
    assert 'href="#cyber-3"' in html and "[7]" in html and "[cyber:9]" not in html
    assert html.count('class="chip"') == 1 and "Autre</span>" in html
    assert 'id="cite-cyber-1"' in html and 'href="#cite-cyber-1"' in html  # aller-retour synthèse <-> fiche
    # contenu LLM/flux échappé : seuls nos 2 scripts (thème + interactions)
    assert p.scripts == 2 and "<img src=x" not in html and "&lt;script&gt;alert(1)" in html
    assert "<strong>gras</strong>" in html
    # titre et résumé complet mis en avant, note en information secondaire
    assert "<p>Premier paragraphe.</p>" in html and "<p>Second paragraphe.</p>" in html
    card = html[html.index('id="cyber-1"') :]
    assert card.index("<h3>") < card.index('class="lead"') < card.index('class="summary"')
    assert '<span class="score"' in card and "9,5/10" in card
    assert 'href="veille-avant.html"' in html and "Rapport n° 7" in html
    assert "résumé sur extrait RSS" in html
    # autonome, ouvrable en file:// : aucune ressource externe chargée
    assert not re.search(r"<script[^>]+src=|<link[^>]+stylesheet|@import|url\(http", html)
    # JSON exporté = données d'origine, sans champs de présentation
    assert "synthesis_html" not in js.read_text() and json.loads(js.read_text())["model"] == "m"
    assert (tmp_path / "latest.json").exists() and html_path.name in (tmp_path / "latest.html").read_text()


def test_markdown_export_keeps_links(tmp_path):
    md = report.render(sample(), tmp_path)[0].read_text()
    assert "[[1]](#cyber-1)" in md and "https://ex.com/4" in md and "⚠ résumé sur extrait RSS" in md


def test_index_lists_reports(tmp_path):
    data = sample()
    _, html_path, _ = report.render(data, tmp_path)
    idx = report.render_index([{"data": json.dumps(data), "path_html": str(html_path)}], tmp_path).read_text()
    assert html_path.name in idx and "Titre 1" in idx and ">dernier<" in idx


def test_axis_colors_distinct_then_generated():
    colors = [report.axis_color(i) for i in range(8)]
    assert len(set(colors)) == 8 and colors[0] == "#1F5FD1" and colors[7].startswith("hsl(")


def test_executive_items_parsing():
    axes = {"cyber": {"color": "#000", "items": [{"title": "T1"}]}}
    items = report.executive_items("Intro ignorée\n- Fait **un** [cyber:1]\n* Fait deux [cyber:5]", axes)
    assert [str(i["html"]) for i in items] == ["Fait <strong>un</strong>", "Fait deux"]
    assert items[0]["cites"][0]["href"] == "#cyber-1" and items[1]["cites"] == []
    assert report.executive_items("Texte libre sans puce", axes)[0]["html"] == "Texte libre sans puce"


def test_parse_rss_atom_and_dates():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
      <entry><title>Hello &amp; <b>world</b></title><link href="https://www.ex.com/a/?utm_source=x"/>
      <updated>2026-10-01T10:00:00Z</updated><summary>&lt;p&gt;Corps&lt;/p&gt;</summary></entry>
      <entry><title></title><link href="https://ex.com/vide"/></entry></feed>"""
    items = collect.parse_rss(Feed(name="F", url="u", weight=1.5), atom)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Hello & world" and it["url"] == "https://ex.com/a" and it["summary"] == "Corps"
    assert it["published"].startswith("2026-10-01T10:00:00") and it["source_weight"] == 1.5


def test_grid_score_scale():
    full = {"on_topic": True, "new_fact": True, "concrete": True, "actionable": True, "major": True, "noise": False}
    assert process.grid_score(full) == 10
    assert process.grid_score({**full, "noise": True}) == 6
    assert process.grid_score({**full, "on_topic": False}) == 2
    assert process.grid_score({"on_topic": True}) == 2


@pytest.fixture
def setup(tmp_path):
    cfg = load_config(ROOT / "config.example.yaml")
    cfg.db_path, cfg.reports_dir = tmp_path / "v.db", tmp_path / "r"
    cfg.pipeline.fetch_full_text = False
    conn = db.connect(cfg.db_path)
    for i in range(3):
        it = {
            "url": f"https://ex.com/{i}",
            "title": f"Ransomware exploits CVE-2026-{i}",
            "summary": "s",
            "source": "S",
            "source_weight": 1.0,
            "published": NOW.isoformat(),
            "fetched_at": NOW.isoformat(),
        }
        db.link_axis(conn, db.upsert_article(conn, it), "cyber")
    conn.commit()
    return cfg, conn


def test_invalid_json_three_times_degrades_gracefully(setup, monkeypatch):
    cfg, conn = setup
    monkeypatch.setattr(LLM, "chat", lambda self, s, u, json_mode=False: "pas du json" if json_mode else "ok")
    data = process.run(cfg, conn, ["cyber"])
    assert data["axes"][0]["items"] == [] and data["axes"][0]["others"] == []  # rien noté, pas de crash


def test_cache_invalidated_when_model_changes(setup, monkeypatch):
    cfg, conn = setup
    calls = []

    def fake(self, s, u, json_mode=False):
        calls.append(self.cfg.model)
        if "- on_topic :" in u:
            return json.dumps({k: True for k in ("on_topic", "new_fact", "concrete", "actionable", "major")})
        return json.dumps({"tldr": "t"}) if json_mode else "synthèse"

    monkeypatch.setattr(LLM, "chat", fake)
    process.run(cfg, conn, ["cyber"])
    n1 = len(calls)
    process.run(cfg, conn, ["cyber"])
    assert len(calls) - n1 == 2  # cache chaud : synthèse + résumé exécutif seulement
    cfg.llm.model = "autre-modele"
    n2 = len(calls)
    data = process.run(cfg, conn, ["cyber"])
    assert len(calls) - n2 == 3 + 3 + 2  # tout est recalculé : 3 notes + 3 résumés + 2 synthèses
    assert data["axes"][0]["items"][0]["digest"]["text_source"] == "rss"


def test_collect_skips_old_items(setup, monkeypatch):
    cfg, conn = setup
    old = (NOW - timedelta(days=400)).isoformat()
    fresh = NOW.isoformat()
    monkeypatch.setattr(
        collect,
        "fetch_feed",
        lambda client, feed: [
            {
                "url": f"https://k/{feed.name}/old",
                "title": "vieux",
                "summary": "",
                "source": feed.name,
                "source_weight": 1,
                "published": old,
                "fetched_at": fresh,
            },
            {
                "url": f"https://k/{feed.name}/new",
                "title": "neuf",
                "summary": "",
                "source": feed.name,
                "source_weight": 1,
                "published": fresh,
                "fetched_at": fresh,
            },
        ],
    )
    collect.collect(cfg, conn)
    titles = {r["title"] for r in conn.execute("SELECT title FROM articles")}
    assert "neuf" in titles and "vieux" not in titles
