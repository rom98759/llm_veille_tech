"""Étape 2b/3 : jugement LLM, extraction du texte, résumé par article, synthèse par axe.

Tout résultat LLM est mis en cache en base : relancer le pipeline ne refait que ce qui manque.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import trafilatura

from . import db, prompts
from .collect import USER_AGENT
from .config import Axis, Config
from .llm import LLM
from .rank import preselect

log = logging.getLogger(__name__)


def extract_text(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.debug("extraction impossible %s : %s", url, e)
        return None
    return trafilatura.extract(resp.text, include_comments=False, include_tables=False)


def judge(llm: LLM, cfg: Config, axis: Axis, item: dict) -> tuple[float, str]:
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
    score = max(0.0, min(10.0, float(data.get("score", 0))))
    return score, str(data.get("reason", ""))


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


def process_axis(llm: LLM, cfg: Config, conn: sqlite3.Connection, axis: Axis, since: str) -> dict:
    p = cfg.pipeline
    rows = [dict(r) for r in db.articles_for_axis(conn, axis.key, since)]
    candidates = preselect(rows, axis.keywords, p.candidates_per_axis)
    log.info("[%s] %d articles collectés, %d candidats", axis.key, len(rows), len(candidates))

    for it in candidates:
        if it["llm_score"] is None:
            try:
                it["llm_score"], it["llm_reason"] = judge(llm, cfg, axis, it)
            except (ValueError, httpx.HTTPError) as e:
                log.warning("jugement échoué « %s » : %s", it["title"], e)
                continue
        conn.execute(
            "UPDATE article_axes SET heuristic = ?, llm_score = ?, llm_reason = ? WHERE article_id = ? AND axis = ?",
            (it["score_h"], it["llm_score"], it["llm_reason"], it["id"], axis.key),
        )
    conn.commit()

    scored = [it for it in candidates if it["llm_score"] is not None]
    scored.sort(key=lambda it: (it["llm_score"], it["score_h"]), reverse=True)
    kept = [it for it in scored if it["llm_score"] >= p.min_llm_score][: p.keep_per_axis]
    kept_ids = {it["id"] for it in kept}

    for it in kept:
        if p.fetch_full_text and not it["content"]:
            it["content"] = extract_text(it["url"])
            conn.execute("UPDATE articles SET content = ? WHERE id = ?", (it["content"], it["id"]))
        if it["llm_summary"]:
            it["digest"] = json.loads(it["llm_summary"])
        else:
            try:
                it["digest"] = summarize(llm, cfg, it)
            except (ValueError, httpx.HTTPError) as e:
                log.warning("résumé échoué « %s » : %s", it["title"], e)
                it["digest"] = {"tldr": it.get("summary", "")[:300], "key_points": [], "why_it_matters": "", "tags": []}
            else:
                conn.execute(
                    "UPDATE articles SET llm_summary = ? WHERE id = ?",
                    (json.dumps(it["digest"], ensure_ascii=False), it["id"]),
                )
        conn.commit()
        log.info("[%s] ✓ %.0f/10 %s", axis.key, it["llm_score"], it["title"])

    synthesis = synthesize(llm, cfg, axis, kept)

    def card(it: dict) -> dict:
        return {k: it.get(k) for k in ("id", "title", "url", "source", "published", "llm_score",
                                       "llm_reason", "score_h", "coverage", "related", "digest")}

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
