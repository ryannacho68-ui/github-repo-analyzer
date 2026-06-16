from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests


DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_BASE_URL = "http://localhost:11434"


@dataclass
class OllamaClient:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 60
    enabled: bool = True
    last_call_log: dict[str, Any] = field(default_factory=dict)

    @property
    def generate_endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/generate"

    @property
    def tags_endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/tags"

    def available_models(self) -> list[str]:
        try:
            response = requests.get(self.tags_endpoint, timeout=min(self.timeout, 5))
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []
        names = []
        for item in data.get("models") or []:
            name = item.get("name") or item.get("model")
            if name:
                names.append(name)
        return sorted(set(names), key=str.lower)

    def generate_json(self, system_prompt: str, user_prompt: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        fallback_payload = dict(fallback or {})
        prompt = _json_prompt(system_prompt, user_prompt)
        base_log = self._base_log(prompt)
        if not self.enabled:
            self.last_call_log = {
                **base_log,
                "status": "disabled",
                "error_message": "LLM disabled by user option.",
            }
            return self._with_meta(fallback_payload, self.last_call_log)

        models = self.available_models()
        if models and self.model not in models:
            self.last_call_log = {
                **base_log,
                "status": "model_missing",
                "error_message": f"Model {self.model} is not installed. Available models: {', '.join(models)}",
            }
            return self._with_meta(fallback_payload, self.last_call_log)

        error_message = ""
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += "\n\nThe previous answer was not valid JSON. Return only one valid JSON object."
            try:
                text = self._post_generate(attempt_prompt, temperature=0.1)
                parsed = _parse_json_object(text)
                self.last_call_log = {
                    **base_log,
                    "llm_used": True,
                    "status": "ok",
                    "error_message": "",
                    "attempts": attempt + 1,
                    "response_length": len(text),
                }
                return self._with_meta(parsed, self.last_call_log)
            except Exception as exc:
                error_message = str(exc)

        self.last_call_log = {
            **base_log,
            "status": "fallback",
            "error_message": error_message,
            "attempts": 2,
        }
        return self._with_meta(fallback_payload, self.last_call_log)

    def generate_text(self, system_prompt: str, user_prompt: str, fallback: str = "") -> str:
        prompt = f"{system_prompt.strip()}\n\n{user_prompt.strip()}"
        base_log = self._base_log(prompt)
        if not self.enabled:
            self.last_call_log = {
                **base_log,
                "status": "disabled",
                "error_message": "LLM disabled by user option.",
            }
            return fallback
        try:
            text = self._post_generate(prompt, temperature=0.2)
            self.last_call_log = {
                **base_log,
                "llm_used": True,
                "status": "ok",
                "error_message": "",
                "response_length": len(text),
            }
            return text.strip() or fallback
        except Exception as exc:
            self.last_call_log = {
                **base_log,
                "status": "fallback",
                "error_message": str(exc),
            }
            return fallback

    def _post_generate(self, prompt: str, temperature: float) -> str:
        response = requests.post(
            self.generate_endpoint,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=self.timeout,
        )
        if response.status_code == 404:
            raise RuntimeError(f"Ollama returned 404. Model {self.model} may not be installed.")
        response.raise_for_status()
        data = response.json()
        text = (data.get("response") or "").strip()
        if not text:
            raise ValueError("Ollama returned an empty response.")
        return text

    def _base_log(self, prompt: str) -> dict[str, Any]:
        return {
            "llm_used": False,
            "model": self.model,
            "base_url": self.base_url,
            "prompt_length": len(prompt),
            "prompt_tokens_estimate": max(1, len(prompt) // 4),
            "status": "pending",
            "error_message": "",
        }

    @staticmethod
    def _with_meta(payload: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        result["_llm_meta"] = dict(meta)
        return result


def _json_prompt(system_prompt: str, user_prompt: str) -> str:
    return (
        f"{system_prompt.strip()}\n\n"
        f"{user_prompt.strip()}\n\n"
        "Return only one valid JSON object. Do not wrap it in Markdown fences."
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM JSON output must be an object.")
    return value
