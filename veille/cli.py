from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from . import collect, db, process, report
from .config import load_config


def cmd_collect(cfg, conn, args):
    n = collect.collect(cfg, conn)
    print(f"{n} liens article/axe enregistrés")


def cmd_report(cfg, conn, args):
    data = process.run(cfg, conn, args.axis)
    md, html, js = report.render(data, cfg.reports_dir)
    db.save_report(conn, data["generated_at"], str(md), str(html), data)
    print(f"Rapport : {html}\n          {md}\n          {js}")


def cmd_run(cfg, conn, args):
    cmd_collect(cfg, conn, args)
    cmd_report(cfg, conn, args)


def cmd_links(cfg, conn, args):
    """Recherche dans tout l'historique collecté, pour creuser un sujet."""
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    sql = """SELECT a.published, a.source, aa.axis, aa.llm_score, a.title, a.url
             FROM articles a JOIN article_axes aa ON aa.article_id = a.id
             WHERE a.published >= ?"""
    params: list = [since]
    if args.axis:
        sql += f" AND aa.axis IN ({','.join('?' * len(args.axis))})"
        params += args.axis
    if args.query:
        sql += " AND (a.title LIKE ? OR a.summary LIKE ? OR a.content LIKE ?)"
        params += [f"%{args.query}%"] * 3
    if args.min_score is not None:
        sql += " AND aa.llm_score >= ?"
        params.append(args.min_score)
    sql += " ORDER BY a.published DESC LIMIT ?"
    params.append(args.limit)
    for r in conn.execute(sql, params):
        score = "  -" if r["llm_score"] is None else f"{r['llm_score']:3.0f}"
        print(f"{r['published'][:10]} {score} {r['axis']:<8} {r['source'][:18]:<18} {r['title'][:80]}\n{'':>12}{r['url']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="veille", description="Veille technologique avec LLM local")
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collect", help="récupérer les flux")
    for name, fn in (("report", cmd_report), ("run", cmd_run)):
        sp = sub.add_parser(name, help="trier + résumer + générer le rapport" + (" (après collecte)" if name == "run" else ""))
        sp.add_argument("--axis", action="append", help="limiter à un axe (répétable)")
        sp.set_defaults(fn=fn)

    lp = sub.add_parser("links", help="rechercher dans les liens collectés")
    lp.add_argument("query", nargs="?")
    lp.add_argument("--axis", action="append")
    lp.add_argument("--days", type=int, default=30)
    lp.add_argument("--min-score", type=float)
    lp.add_argument("--limit", type=int, default=50)
    lp.set_defaults(fn=cmd_links)
    sub.choices["collect"].set_defaults(fn=cmd_collect)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    conn = db.connect(cfg.db_path)
    args.fn(cfg, conn, args)
