import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from veille import db, process, report
from veille.collect import normalize_url
from veille.config import load_config
from veille.llm import LLM, parse_json
from veille.rank import matches_keywords, preselect

ROOT = Path(__file__).resolve().parents[1]


def test_normalize_url_strips_tracking():
    assert normalize_url("https://www.Example.com/a/?utm_source=x&id=3#frag") == "https://example.com/a?id=3"


def test_keywords_word_boundary():
    assert matches_keywords("New RAG pipeline", ["rag"]) == ["rag"]
    assert matches_keywords("Object storage", ["rag"]) == []


def test_parse_json_tolerant():
    assert parse_json('```json\n{"score": 7}\n```') == {"score": 7}
    assert parse_json('Voici : {"score": 3, "reason": "x"} fin') == {"score": 3, "reason": "x"}


def _item(title, source, hours=1, weight=1.0):
    return {"title": title, "summary": "", "source": source, "source_weight": weight,
            "url": f"https://{source}/{title}",
            "published": (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}


def test_preselect_clusters_same_story():
    items = [
        _item("OpenSSL critical vulnerability CVE-2026-1234 patched", "a"),
        _item("Critical OpenSSL vulnerability CVE-2026-1234 patched now", "b", weight=1.5),
        _item("Kubernetes 1.40 released", "c"),
    ]
    out = preselect(items, ["cve", "vulnerability"], 10)
    assert len(out) == 2
    top = out[0]
    assert top["source"] == "b" and top["coverage"] == 2 and len(top["related"]) == 1


def test_end_to_end_with_fake_llm(tmp_path, monkeypatch):
    cfg = load_config(ROOT / "config.example.yaml")
    cfg.db_path, cfg.reports_dir = tmp_path / "v.db", tmp_path / "reports"
    cfg.pipeline.fetch_full_text = False
    conn = db.connect(cfg.db_path)
    for i in range(4):
        it = _item(f"Ransomware campaign {i} exploits CVE-2026-{i}", "BleepingComputer", hours=i)
        it["fetched_at"] = it["published"]
        db.link_axis(conn, db.upsert_article(conn, it), "cyber")
    conn.commit()

    def fake_chat(self, system, user, json_mode=False):
        if "Note de 0 à 10" in user:
            return json.dumps({"score": 8 if "campaign 0" in user or "campaign 1" in user else 3, "reason": "ok"})
        if json_mode:
            return json.dumps({"tldr": "Résumé.", "key_points": ["a", "b"], "why_it_matters": "Patcher.", "tags": ["cve"]})
        if "résumé exécutif" in user:
            return "- Point clé [cyber:1]"
        return "Deux campagnes actives [1][2]."

    monkeypatch.setattr(LLM, "chat", fake_chat)
    data = process.run(cfg, conn, ["cyber"])
    cyber = data["axes"][0]
    assert len(cyber["items"]) == 2 and len(cyber["others"]) == 2

    md, html, js = report.render(data, cfg.reports_dir)
    text = md.read_text()
    assert "[[1]](#cyber-1)" in text and "[[cyber:1]](#cyber-1)" in text
    assert 'id="cyber-2"' in html.read_text()
    assert all(it["url"] in text for it in cyber["items"] + cyber["others"])

    # le cache évite de rappeler le LLM pour le jugement/résumé
    calls = []
    monkeypatch.setattr(LLM, "chat", lambda self, s, u, json_mode=False: calls.append(json_mode) or fake_chat(self, s, u, json_mode))
    process.run(cfg, conn, ["cyber"])
    assert not any(calls)
