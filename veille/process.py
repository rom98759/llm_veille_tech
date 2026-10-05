"""Étape 2b/3 : jugement LLM, extraction du texte, résumé par article, synthèse par axe.

Tout résultat LLM est mis en cache en base : relancer le pipeline ne refait que ce qui manque.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import trafilatura

from . import db, prompts
from .collect import USER_AGENT
from .config import Axis, Config
from .llm import LLM
from .rank import preselect

log = logging.getLogger(__name__)


JUDGE_WEIGHTS = {"on_topic": 2.0, "new_fact": 2.0, "concrete": 1.5, "actionable": 2.0, "major": 2.5}
NOISE_PENALTY = 4.0
CRITERIA_LABELS = {"on_topic": "dans l'axe", "new_fact": "fait nouveau", "concrete": "concret",
                   "actionable": "actionnable", "major": "impact large", "noise": "bruit"}


def extract_text(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("texte complet indisponible (%s) : %s", e.__class__.__name__, url)
        return None
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
    if not text:
        log.warning("texte complet non extractible (page vide ou JS) : %s", url)
    return text


def _bool(v) -> bool:
    return v is True or str(v).strip().lower() in {"true", "oui", "yes", "1"}


def grid_score(criteria: dict) -> float:
    """Note 0-10 calculée à partir des critères oui/non, pour une échelle stable quel que soit le modèle."""
    score = sum(w for k, w in JUDGE_WEIGHTS.items() if criteria.get(k))
    if criteria.get("noise"):
        score -= NOISE_PENALTY
    if not criteria.get("on_topic"):
        score = min(score, 2.0)
    return round(max(0.0, min(10.0, score)), 1)


def judge(llm: LLM, cfg: Config, axis: Axis, item: dict) -> tuple[float, str, dict]:
    data = llm.chat_json(
        prompts.JUDGE_SYSTEM,
        prompts.JUDGE_USER.format(
            profile=cfg.profile or "(non précisé)",
            axis_title=axis.title,
            axis_description=axis.description,
            title=item["title"],
            source=item["source"],
            summary=(item.get("summary") or "")[:800],
        ),
    )
    criteria = {k: _bool(data.get(k)) for k in CRITERIA_LABELS}
    return grid_score(criteria), str(data.get("reason", "")), criteria


def summarize(llm: LLM, cfg: Config, item: dict) -> dict:
    text = (item.get("content") or item.get("summary") or item["title"])[: cfg.llm.max_input_chars]
    data = llm.chat_json(
        prompts.SUMMARY_SYSTEM.format(language=cfg.pipeline.language),
        prompts.SUMMARY_USER.format(title=item["title"], source=item["source"], text=text),
    )
    return {
        "tldr": str(data.get("tldr", "")),
        "key_points": [str(p) for p in data.get("key_points", [])][:3],
        "why_it_matters": str(data.get("why_it_matters", "")),
        "tags": [str(t) for t in data.get("tags", [])][:6],
    }


def synthesize(llm: LLM, cfg: Config, axis: Axis, kept: list[dict]) -> str:
    if not kept:
        return ""
    lines = [
        f"[{i}] {it['title']} ({it['source']}) — {it['digest']['tldr']} {it['digest']['why_it_matters']}"
        for i, it in enumerate(kept, 1)
    ]
    return llm.chat(
        prompts.SYNTH_SYSTEM.format(language=cfg.pipeline.language),
        prompts.SYNTH_USER.format(axis_title=axis.title, items="\n".join(lines)),
    )


def executive_summary(llm: LLM, cfg: Config, axes: list[dict]) -> str:
    blocks = []
    for a in axes:
        if a["synthesis"]:
            # [3] -> [cyber:3] pour garder des références non ambiguës entre axes
            text = re.sub(r"\[(\d+)\]", rf"[{a['key']}:\1]", a["synthesis"])
            blocks.append(f"## {a['title']}\n{text}")
    if not blocks:
        return ""
    return llm.chat(
        prompts.EXEC_SYSTEM.format(language=cfg.pipeline.language),
        prompts.EXEC_USER.format(syntheses="\n\n".join(blocks)),
    )


def _parallel(fn, items: list, workers: int) -> list:
    """Appels LLM en parallèle ; renvoie (item, résultat | exception). Les écritures en base restent au thread appelant."""
    def safe(it):
        try:
            return it, fn(it)
        except (ValueError, httpx.HTTPError) as e:
            return it, e
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(safe, items))


def process_axis(llm: LLM, cfg: Config, conn: sqlite3.Connection, axis: Axis, since: str) -> dict:
    p = cfg.pipeline
    judge_key = f"{cfg.llm.model}|{prompts.JUDGE_VERSION}"
    summary_key = f"{cfg.llm.model}|{prompts.SUMMARY_VERSION}"
    rows = [dict(r) for r in db.articles_for_axis(conn, axis.key, since)]
    candidates = preselect(rows, axis.keywords, p.candidates_per_axis)
    log.info("[%s] %d articles collectés, %d candidats", axis.key, len(rows), len(candidates))

    # 1. notation (cache invalidé si le modèle ou la grille change)
    for it in candidates:
        it["criteria"] = json.loads(it["llm_detail"]) if it.get("llm_detail") else None
        if it.get("llm_model") != judge_key:
            it["llm_score"] = None
    todo = [it for it in candidates if it["llm_score"] is None]
    for it, res in _parallel(lambda it: judge(llm, cfg, axis, it), todo, cfg.llm.max_workers):
        if isinstance(res, Exception):
            log.warning("notation échouée « %s » : %s", it["title"], res)
            continue
        it["llm_score"], it["llm_reason"], it["criteria"] = res
        it["llm_model"] = judge_key
    for it in candidates:
        conn.execute(
            """UPDATE article_axes SET heuristic = ?, llm_score = ?, llm_reason = ?, llm_detail = ?, llm_model = ?
               WHERE article_id = ? AND axis = ?""",
            (it["score_h"], it["llm_score"], it["llm_reason"],
             json.dumps(it["criteria"]) if it["criteria"] else None, it.get("llm_model"), it["id"], axis.key),
        )
    conn.commit()

    scored = [it for it in candidates if it["llm_score"] is not None]
    scored.sort(key=lambda it: (it["llm_score"], it["score_h"]), reverse=True)
    kept = [it for it in scored if it["llm_score"] >= p.min_llm_score][: p.keep_per_axis]
    kept_ids = {it["id"] for it in kept}
    dist = sorted((it["llm_score"] for it in scored), reverse=True)
    log.info("[%s] notes : %s → %d retenus (seuil %s)", axis.key, dist, len(kept), p.min_llm_score)

    # 2. texte complet + résumé
    for it in kept:
        cached = json.loads(it["llm_summary"]) if it["llm_summary"] else None
        it["digest"] = cached if cached and cached.get("cache_key") == summary_key else None
        if it["digest"] is None and p.fetch_full_text and not it["content"]:
            it["content"] = extract_text(it["url"])
            conn.execute("UPDATE articles SET content = ? WHERE id = ?", (it["content"], it["id"]))
    conn.commit()

    todo = [it for it in kept if it["digest"] is None]
    for it, res in _parallel(lambda it: summarize(llm, cfg, it), todo, cfg.llm.max_workers):
        if isinstance(res, Exception):
            log.warning("résumé échoué « %s » : %s", it["title"], res)
            it["digest"] = {"tldr": (it.get("summary") or "")[:300], "key_points": [], "why_it_matters": "",
                            "tags": [], "text_source": "rss", "failed": True}
            continue
        res["text_source"] = "page" if it["content"] else "rss"
        res["cache_key"] = summary_key
        it["digest"] = res
        conn.execute("UPDATE articles SET llm_summary = ? WHERE id = ?",
                     (json.dumps(res, ensure_ascii=False), it["id"]))
    conn.commit()
    for it in kept:
        if it["digest"].get("text_source") == "rss":
            log.warning("[%s] résumé fait sur l'extrait RSS seulement : %s", axis.key, it["title"])
        log.info("[%s] ✓ %.1f/10 %s", axis.key, it["llm_score"], it["title"])

    synthesis = synthesize(llm, cfg, axis, kept)

    def card(it: dict) -> dict:
        return {k: it.get(k) for k in ("id", "title", "url", "source", "published", "llm_score", "llm_reason",
                                       "criteria", "score_h", "coverage", "related", "digest")}

    return {
        "key": axis.key,
        "title": axis.title,
        "description": axis.description,
        "synthesis": synthesis,
        "items": [card(it) for it in kept],
        "others": [card(it) for it in scored if it["id"] not in kept_ids],
        "total_collected": len(rows),
    }


def run(cfg: Config, conn: sqlite3.Connection, only_axes: list[str] | None = None) -> dict:
    llm = LLM(cfg.llm)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=cfg.pipeline.lookback_days)).isoformat()
    axes = [
        process_axis(llm, cfg, conn, axis, since)
        for key, axis in cfg.axes.items()
        if not only_axes or key in only_axes
    ]
    return {
        "generated_at": now.isoformat(timespec="minutes"),
        "since": since[:16],
        "model": cfg.llm.model,
        "executive_summary": executive_summary(llm, cfg, axes),
        "axes": axes,
    }
