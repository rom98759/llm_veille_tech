"""Client minimal pour un serveur compatible OpenAI (Ollama, llama.cpp, LM Studio, vLLM)."""

from __future__ import annotations

import json
import logging
import re

import httpx

from .config import LLMConfig

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.client = httpx.Client(
            base_url=cfg.base_url.rstrip("/"),
            timeout=cfg.timeout,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
        )

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        body = {
            "model": self.cfg.model,
            "temperature": self.cfg.temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(self.cfg.extra_body)
        log.debug("--- requête LLM ---\n[system]\n%s\n[user]\n%s", system, user)
        resp = self.client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        log.debug("--- réponse LLM brute (avec réflexion éventuelle) ---\n%s", content)
        usage, timings = data.get("usage"), data.get("timings")
        if usage:
            log.debug(
                "--- usage : %s tokens prompt, %s tokens générés (%s total)",
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
        if timings:  # extension llama.cpp (absent sur Ollama/vLLM) : tokens/s réels côté serveur
            log.debug(
                "--- vitesse : prompt %.1f tok/s (%d tok) · génération %.1f tok/s (%d tok)",
                timings.get("prompt_per_second", 0),
                timings.get("prompt_n", 0),
                timings.get("predicted_per_second", 0),
                timings.get("predicted_n", 0),
            )
        # modèles « raisonnants » (qwen3, deepseek-r1…) : retirer le bloc de réflexion s'il est renvoyé
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    def chat_json(self, system: str, user: str, retries: int = 2) -> dict:
        """Les petits modèles cassent parfois le JSON : on extrait le premier objet et on réessaie."""
        last = ""
        for _ in range(retries + 1):
            last = self.chat(system, user, json_mode=True)
            try:
                return parse_json(last)
            except ValueError:
                log.debug("JSON invalide, nouvel essai : %s", last[:200])
        raise ValueError(f"réponse JSON invalide : {last[:300]}")


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("pas de JSON")
