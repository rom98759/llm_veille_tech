"""Étape 4 : rendu du rapport (Markdown + HTML + JSON) à partir d'un template commun."""
from __future__ import annotations

import json
import re
from pathlib import Path

import markdown
from jinja2 import Environment, PackageLoader

env = Environment(loader=PackageLoader("veille", "templates"), keep_trailing_newline=True)
env.filters["cite"] = lambda text, axis: re.sub(r"\[(\d+)\]", rf"[[\1]](#{axis}-\1)", text or "")
env.filters["cite_global"] = lambda text: re.sub(r"\[([\w-]+):(\d+)\]", r"[[\1:\2]](#\1-\2)", text or "")
env.filters["md_cell"] = lambda text: (text or "").replace("|", "\\|").replace("\n", " ")
env.filters["tag"] = lambda t: f'<span class="tag">#{t}</span>'


def render(data: dict, out_dir: Path) -> tuple[Path, Path, Path]:
    date = data["generated_at"][:10]
    ctx = {
        **data,
        "date": date,
        "total_kept": sum(len(a["items"]) for a in data["axes"]),
        "total_collected": sum(a["total_collected"] for a in data["axes"]),
    }
    md = env.get_template("report.md.j2").render(**ctx)
    body = markdown.markdown(md, extensions=["tables", "md_in_html"])
    html = env.get_template("report.html.j2").render(date=date, body=body)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"veille-{data['generated_at'][:16].replace(':', '')}"
    paths = (out_dir / f"{stem}.md", out_dir / f"{stem}.html", out_dir / f"{stem}.json")
    paths[0].write_text(md, encoding="utf-8")
    paths[1].write_text(html, encoding="utf-8")
    paths[2].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "latest.html").write_text(html, encoding="utf-8")
    return paths
