"""Étape 4 : rendu du rapport à partir des données (Markdown, HTML autonome, JSON) + index historique.

Le HTML est rendu directement depuis les données : chaque article est un <article> avec ses attributs
data-*, ce qui permet cartes, couleurs par axe et filtres côté client. La hiérarchie de lecture met en
avant le titre et le résumé ; la note de pertinence reste une information secondaire.
"""

from __future__ import annotations

import copy
import html as htmllib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import markdown
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

env = Environment(
    loader=PackageLoader("veille", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False),
    keep_trailing_newline=True,
)

CRITERIA_LABELS = {
    "new_fact": "fait nouveau",
    "concrete": "concret",
    "actionable": "actionnable",
    "major": "impact large",
}
# Couleurs des premiers axes (teintes et clartés distinctes), puis angle d'or pour les suivants.
AXIS_COLORS = ["#1F5FD1", "#A34A0B", "#0E7268", "#7A3EB8", "#B0265E", "#5A6B00"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


# ---------- filtres Markdown (export texte) ----------
env.filters["cite"] = lambda text, axis: re.sub(r"\[(\d+)\]", rf"[[\1]](#{axis}-\1)", text or "")
env.filters["cite_global"] = lambda text: re.sub(r"\[([\w-]+):(\d+)\]", r"[[\1:\2]](#\1-\2)", text or "")
env.filters["md_cell"] = lambda text: (text or "").replace("|", "\\|").replace("\n", " ")
env.filters["tag"] = lambda t: f"#{t}"


# ---------- filtres HTML ----------
def md_inline(text: str | None) -> Markup:
    """Texte libre du LLM -> HTML sûr : échappé d'abord, puis Markdown minimal (gras, italique, listes)."""
    out = markdown.markdown(htmllib.escape(text or ""))
    m = re.fullmatch(r"<p>(.*)</p>", out.strip(), re.S)
    return Markup(m.group(1) if m else out)


def md_block(text: str | None) -> Markup:
    """Comme md_inline mais garde les paragraphes (résumé long)."""
    return Markup(markdown.markdown(htmllib.escape(text or "")))


def fmt_score(s) -> str:
    if s is None:
        return "–"
    return f"{s:.0f}" if float(s).is_integer() else f"{s:.1f}".replace(".", ",")


def long_date(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def short_date(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{DAYS[d.weekday()][:3]}. {d.day} {MONTHS[d.month - 1]}"


env.filters["md_inline"] = md_inline
env.filters["md_block"] = md_block
env.filters["fmt_score"] = fmt_score


def axis_color(index: int) -> str:
    if index < len(AXIS_COLORS):
        return AXIS_COLORS[index]
    return f"hsl({round(215 + index * 137.508) % 360} 60% 38%)"


def _cite_link(axis: str, n: int, item: dict, seen: set[str], label: str) -> str:
    ref = f"{axis}-{n}"
    attrs = f'class="cite" href="#{ref}" title="{htmllib.escape(item["title"])} — {htmllib.escape(item["source"])}"'
    if ref not in seen:  # première citation : ancre de retour depuis la fiche
        seen.add(ref)
        attrs += f' id="cite-{ref}"'
        item["cited_from"] = f"cite-{ref}"
    return f"<a {attrs}>{label}</a>"


def link_citations(html: str, axes: dict[str, dict], default_axis: str | None, seen: set[str]) -> Markup:
    """[n] (synthèse d'axe) -> pastilles cliquables avec aperçu au survol et ancre de retour."""

    def repl(m: re.Match) -> str:
        axis, n = (m.group(1) or default_axis), int(m.group(2))
        items = axes.get(axis, {}).get("items", []) if axis else []
        if not 1 <= n <= len(items):
            return m.group(0)
        label = f"{n}" if m.group(1) is None else f"{axis} {n}"
        return _cite_link(axis, n, items[n - 1], seen, label)

    return Markup(re.sub(r"\[(?:([\w-]+):)?(\d+)\]", repl, html))


def executive_items(text: str | None, axes: dict[str, dict]) -> list[dict]:
    """Puces du résumé exécutif -> [{html, cites: [{href, label, color, title}]}]."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    bullet = re.compile(r"^([-*•]|\d+[.)])\s+")
    bullets = [bullet.sub("", ln) for ln in lines if bullet.match(ln)]
    out = []
    for b in bullets or ([" ".join(lines)] if lines else []):
        cites = []
        for axis, n in re.findall(r"\[([\w-]+):(\d+)\]", b):
            items = axes.get(axis, {}).get("items", [])
            if 1 <= int(n) <= len(items):
                cites.append(
                    {
                        "href": f"#{axis}-{n}",
                        "label": f"{axis} {n}",
                        "color": axes[axis]["color"],
                        "title": items[int(n) - 1]["title"],
                    }
                )
        clean = re.sub(r"\s*\[[\w-]+:\d+\]", "", b).strip()
        out.append({"html": md_inline(clean), "cites": cites})
    return out


def _context(data: dict, prev: str | None = None, number: int | None = None) -> dict:
    data = copy.deepcopy(data)  # ne pas polluer le JSON exporté avec les champs de présentation
    axes = data["axes"]
    by_key = {a["key"]: a for a in axes}
    seen: set[str] = set()
    for i, a in enumerate(axes):
        a["color"] = axis_color(i)
        for j, it in enumerate(a["items"], 1):
            it["anchor"] = f"{a['key']}-{j}"
            crit = it.get("criteria") or {}
            it["criteria_labels"] = [label for k, label in CRITERIA_LABELS.items() if crit.get(k)]
        a["synthesis_html"] = link_citations(md_inline(a["synthesis"]), by_key, a["key"], seen)
    sources = sorted({it["source"] for a in axes for it in a["items"] + a["others"]})
    plain_exec = re.sub(r"\[[\w-]*:?\d+\]|^[-*]\s*", "", data.get("executive_summary") or "", flags=re.M)
    return {
        **data,
        "date": data["generated_at"][:10],
        "date_long": long_date(data["generated_at"]),
        "since_label": short_date(data["since"]) if data.get("since") else "",
        "until_label": short_date(data["generated_at"]),
        "number": number,
        "prev": prev,
        "total_kept": sum(len(a["items"]) for a in axes),
        "total_scored": sum(len(a["items"]) + len(a["others"]) for a in axes),
        "total_collected": sum(a["total_collected"] for a in axes),
        "exec_items": executive_items(data.get("executive_summary"), by_key),
        "sources": sources,
        "description": " ".join(plain_exec.split())[:200],
    }


def render(data: dict, out_dir: Path, prev: str | None = None, number: int | None = None) -> tuple[Path, Path, Path]:
    """Écrit le rapport en .md/.html/.json. `prev` : nom du fichier HTML du rapport précédent (navigation)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"veille-{data['generated_at'][:16].replace(':', '')}"
    paths = (out_dir / f"{stem}.md", out_dir / f"{stem}.html", out_dir / f"{stem}.json")
    ctx = _context(data, prev, number)
    ctx["files"] = {"md": paths[0].name, "json": paths[2].name}
    paths[0].write_text(env.get_template("report.md.j2").render(**ctx), encoding="utf-8")
    paths[1].write_text(env.get_template("report.html.j2").render(**ctx), encoding="utf-8")
    paths[2].write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    shutil.copyfile(paths[2], out_dir / "latest.json")
    (out_dir / "latest.html").write_text(
        env.get_template("redirect.html.j2").render(target=paths[1].name), encoding="utf-8"
    )
    return paths


def render_index(reports: list[dict], out_dir: Path) -> Path:
    """Index de l'historique depuis la table `reports` (du plus récent au plus ancien)."""
    months: list[dict] = []
    legend: dict[str, str] = {}
    for pos, r in enumerate(reports):
        data = json.loads(r["data"])
        items = [(it["llm_score"] or 0, it["title"]) for a in data["axes"] for it in a["items"]]
        d = datetime.fromisoformat(data["generated_at"])
        month = f"{MONTHS[d.month - 1]} {d.year}"
        if not months or months[-1]["label"] != month:
            months.append({"label": month, "entries": []})
        axes = [
            {"title": a["title"], "key": a["key"], "n": len(a["items"]), "color": axis_color(i)}
            for i, a in enumerate(data["axes"])
        ]
        for a in axes:
            legend.setdefault(a["title"], a["color"])
        months[-1]["entries"].append(
            {
                "file": Path(r["path_html"]).name,
                "date": short_date(data["generated_at"]),
                "time": data["generated_at"][11:16],
                "model": data.get("model", ""),
                "kept": len(items),
                "latest": pos == 0,
                "axes": axes,
                "top": [t for _, t in sorted(items, key=lambda x: -x[0])[:3]],
            }
        )
    path = out_dir / "index.html"
    path.write_text(
        env.get_template("index.html.j2").render(months=months, count=len(reports), legend=legend),
        encoding="utf-8",
    )
    return path
