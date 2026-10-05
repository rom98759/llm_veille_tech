"""Stockage SQLite : tout ce qui est collecté est conservé (liens, scores, résumés)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY,
    url          TEXT NOT NULL UNIQUE,      -- URL normalisée
    title        TEXT NOT NULL,
    summary      TEXT,                      -- extrait du flux RSS
    content      TEXT,                      -- texte complet extrait
    source       TEXT NOT NULL,
    source_weight REAL DEFAULT 1.0,
    published    TEXT NOT NULL,             -- ISO 8601 UTC
    fetched_at   TEXT NOT NULL,
    llm_summary  TEXT                       -- JSON {tldr, key_points, why_it_matters, tags}
);
CREATE TABLE IF NOT EXISTS article_axes (
    article_id   INTEGER NOT NULL REFERENCES articles(id),
    axis         TEXT NOT NULL,
    heuristic    REAL,                      -- score de pré-tri
    llm_score    REAL,                      -- pertinence jugée par le LLM pour cet axe
    llm_reason   TEXT,
    llm_detail   TEXT,                      -- JSON des critères de la grille
    llm_model    TEXT,                      -- clé de cache « modèle|version de prompt »
    PRIMARY KEY (article_id, axis)
);
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    path_md      TEXT,
    path_html    TEXT,
    data         TEXT                       -- JSON complet du rapport
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
"""


MIGRATIONS = {  # colonnes ajoutées après coup : (table, colonne) -> type
    ("article_axes", "llm_detail"): "TEXT",
    ("article_axes", "llm_model"): "TEXT",
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for (table, col), typ in MIGRATIONS.items():
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return conn


def upsert_article(conn: sqlite3.Connection, a: dict) -> int:
    """Insère l'article s'il est nouveau, renvoie son id."""
    cur = conn.execute(
        """INSERT INTO articles (url, title, summary, source, source_weight, published, fetched_at)
           VALUES (:url, :title, :summary, :source, :source_weight, :published, :fetched_at)
           ON CONFLICT(url) DO NOTHING""",
        a,
    )
    if cur.lastrowid and cur.rowcount:
        return cur.lastrowid
    return conn.execute("SELECT id FROM articles WHERE url = ?", (a["url"],)).fetchone()["id"]


def link_axis(conn: sqlite3.Connection, article_id: int, axis: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO article_axes (article_id, axis) VALUES (?, ?)", (article_id, axis)
    )


def articles_for_axis(conn: sqlite3.Connection, axis: str, since_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, aa.heuristic, aa.llm_score, aa.llm_reason, aa.llm_detail, aa.llm_model FROM articles a
           JOIN article_axes aa ON aa.article_id = a.id
           WHERE aa.axis = ? AND a.published >= ?
           ORDER BY a.published DESC""",
        (axis, since_iso),
    ).fetchall()


def prune(conn: sqlite3.Connection, before_iso: str) -> int:
    """Supprime les articles publiés avant la date (les rapports gardent leur JSON complet)."""
    conn.execute(
        "DELETE FROM article_axes WHERE article_id IN (SELECT id FROM articles WHERE published < ?)", (before_iso,)
    )
    n = conn.execute("DELETE FROM articles WHERE published < ?", (before_iso,)).rowcount
    conn.commit()
    conn.execute("VACUUM")
    return n


def save_report(conn: sqlite3.Connection, created_at: str, md: str, html: str, data: dict) -> None:
    conn.execute(
        "INSERT INTO reports (created_at, path_md, path_html, data) VALUES (?, ?, ?, ?)",
        (created_at, md, html, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
