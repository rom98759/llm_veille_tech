from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Feed:
    name: str
    url: str
    weight: float = 1.0
    kind: str = "rss"  # rss (RSS/Atom) | cisa_kev (catalogue JSON CISA)
    note: str = ""


@dataclass
class Axis:
    key: str
    title: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    feeds: list[Feed] = field(default_factory=list)


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "qwen2.5:7b-instruct"
    temperature: float = 0.2
    timeout: float = 300
    max_input_chars: int = 6000


@dataclass
class PipelineConfig:
    lookback_days: int = 2
    candidates_per_axis: int = 25
    keep_per_axis: int = 8
    min_llm_score: int = 6
    fetch_full_text: bool = True
    language: str = "français"


@dataclass
class Config:
    llm: LLMConfig
    pipeline: PipelineConfig
    db_path: Path
    reports_dir: Path
    profile: str
    axes: dict[str, Axis]
    shared_feeds: list[Feed]


def _feeds(raw: list[dict] | None) -> list[Feed]:
    fields = Feed.__dataclass_fields__
    return [Feed(**{k: v for k, v in f.items() if k in fields}) for f in raw or []]


def load_catalog(path: str | Path) -> dict[str, list[Feed]]:
    """Catalogue de sources candidates : {groupe: [Feed]}."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {group: _feeds(feeds) for group, feeds in raw.items()}


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    storage = raw.get("storage", {})
    axes = {
        key: Axis(
            key=key,
            title=a.get("title", key),
            description=a.get("description", ""),
            keywords=[k.lower() for k in a.get("keywords", [])],
            feeds=_feeds(a.get("feeds")),
        )
        for key, a in (raw.get("axes") or {}).items()
    }
    if not axes:
        raise ValueError("config: au moins un axe est requis")
    return Config(
        llm=LLMConfig(**raw.get("llm", {})),
        pipeline=PipelineConfig(**raw.get("pipeline", {})),
        db_path=Path(storage.get("db_path", "data/veille.db")),
        reports_dir=Path(storage.get("reports_dir", "reports")),
        profile=raw.get("profile", "").strip(),
        axes=axes,
        shared_feeds=_feeds(raw.get("shared_feeds")),
    )
