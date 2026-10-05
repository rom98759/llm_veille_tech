"""Étape 4 : rendu du rapport à partir des données (Markdown, HTML autonome, JSON) + index historique.

Le HTML est rendu directement depuis les données (plus dérivé du Markdown) : chaque article est un
<article> avec ses attributs data-*, ce qui permet cartes, couleurs par axe et filtres côté client.
"""

from __future__ import annotations

import copy
import html as htmllib
import json
import re
import shutil
import zlib
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


def score_class(score: float | None) -> str:
    if score is None:
        return "low"
    return "high" if score >= 9 else "mid" if score >= 7 else "low"


env.filters["md_inline"] = md_inline
env.filters["score_class"] = score_class
env.filters["fmt_score"] = lambda s: "–" if s is None else (f"{s:.0f}" if float(s).is_integer() else f"{s:.1f}")


def axis_hue(key: str, index: int | None = None) -> int:
    """Teinte par axe, pour tout axe ajouté dans config.yaml.

    Avec la position de l'axe : angle d'or depuis le bleu, teintes bien séparées pour les premiers axes.
    Sans : dérivée d'un hash de la clé (stable mais collisions possibles).
    """
    if index is not None:
        return round(215 + index * 137.508) % 360
    return zlib.crc32(key.encode()) % 360


def _cite_link(axis: str, n: int, item: dict, seen: set[str], label: str) -> str:
    ref = f"{axis}-{n}"
    attrs = f'class="cite" href="#{ref}" title="{htmllib.escape(item["title"])} — {htmllib.escape(item["source"])}"'
    if ref not in seen:  # première citation : ancre de retour depuis la fiche
        seen.add(ref)
        attrs += f' id="cite-{ref}"'
        item["cited_from"] = f"cite-{ref}"
    return f"<a {attrs}>{label}</a>"


def link_citations(html: str, axes: dict[str, dict], default_axis: str | None, seen: set[str]) -> Markup:
    """[n] (synthèse d'axe) et [axe:n] (résumé exécutif) -> pastilles cliquables avec aperçu."""

    def repl(m: re.Match) -> str:
        axis, n = (m.group(1) or default_axis), int(m.group(2))
        items = axes.get(axis, {}).get("items", []) if axis else []
        if not 1 <= n <= len(items):
            return m.group(0)
        label = f"{n}" if m.group(1) is None else f"{axis} {n}"
        return _cite_link(axis, n, items[n - 1], seen, label)

    return Markup(re.sub(r"\[(?:([\w-]+):)?(\d+)\]", repl, html))


def _context(data: dict) -> dict:
    data = copy.deepcopy(data)  # ne pas polluer le JSON exporté avec les champs de présentation
    axes = data["axes"]
    by_key = {a["key"]: a for a in axes}
    seen: set[str] = set()
    for i, a in enumerate(axes):
        a["hue"] = axis_hue(a["key"], i)
        for i, it in enumerate(a["items"], 1):
            it["anchor"] = f"{a['key']}-{i}"
            crit = it.get("criteria") or {}
            it["criteria_labels"] = [label for k, label in CRITERIA_LABELS.items() if crit.get(k)]
        a["synthesis_html"] = link_citations(md_inline(a["synthesis"]), by_key, a["key"], seen)
    exec_html = link_citations(
        markdown.markdown(htmllib.escape(data.get("executive_summary") or "")), by_key, None, seen
    )
    sources = sorted({it["source"] for a in axes for it in a["items"] + a["others"]})
    plain_exec = re.sub(r"\[[\w-]*:?\d+\]|^[-*]\s*", "", data.get("executive_summary") or "", flags=re.M)
    return {
        **data,
        "date": data["generated_at"][:10],
        "total_kept": sum(len(a["items"]) for a in axes),
        "total_collected": sum(a["total_collected"] for a in axes),
        "executive_html": exec_html,
        "sources": sources,
        "description": " ".join(plain_exec.split())[:200],
    }


def render(data: dict, out_dir: Path) -> tuple[Path, Path, Path]:
    ctx = _context(data)
    md = env.get_template("report.md.j2").render(**ctx)
    html = env.get_template("report.html.j2").render(**ctx)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"veille-{data['generated_at'][:16].replace(':', '')}"
    paths = (out_dir / f"{stem}.md", out_dir / f"{stem}.html", out_dir / f"{stem}.json")
    paths[0].write_text(md, encoding="utf-8")
    paths[1].write_text(html, encoding="utf-8")
    paths[2].write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    shutil.copyfile(paths[2], out_dir / "latest.json")
    (out_dir / "latest.html").write_text(
        env.get_template("redirect.html.j2").render(target=paths[1].name), encoding="utf-8"
    )
    return paths


def render_index(reports: list[dict], out_dir: Path) -> Path:
    """Index de l'historique à partir de la table `reports` (le JSON complet de chaque rapport y est gardé)."""
    entries = []
    for r in reports:
        data = json.loads(r["data"])
        items = [(it["llm_score"] or 0, it["title"], a["title"]) for a in data["axes"] for it in a["items"]]
        entries.append(
            {
                "file": Path(r["path_html"]).name,
                "date": data["generated_at"][:16].replace("T", " "),
                "model": data.get("model", ""),
                "kept": len(items),
                "axes": [
                    {"title": a["title"], "n": len(a["items"]), "hue": axis_hue(a["key"], i)}
                    for i, a in enumerate(data["axes"])
                ],
                "top": [t for _, t, _ in sorted(items, key=lambda x: -x[0])[:3]],
            }
        )
    path = out_dir / "index.html"
    path.write_text(env.get_template("index.html.j2").render(entries=entries), encoding="utf-8")
    return path
