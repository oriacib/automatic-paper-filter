from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import requests

from app.config import DeepSeekConfig
from app.utils.file_ops import atomic_write_json, read_json
from app.utils.retry import run_with_retry


class DeepSeekClient:
    """
    Backward-compatible class name.
    It now supports multiple providers via cfg.provider:
    deepseek / kimi / qwen / gpt / gemini / openai_compatible / local.
    """

    def __init__(self, cfg: DeepSeekConfig, cache_dir: Path, logger) -> None:
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.logger = logger
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    @property
    def enabled(self) -> bool:
        if not self.cfg.enabled:
            return False
        if self.cfg.requires_key and not self.cfg.api_key:
            return False
        return True

    def _cache_key(self, title: str, summary: str, keywords: list[str]) -> str:
        payload = (
            f"{self.cfg.provider}|{self.cfg.model}|{title.strip()}||{summary.strip()}||"
            f"{'|'.join(sorted(set(keywords)))}"
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _cache_file(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _normalize_result(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": float(max(0.0, min(1.0, float(data.get("score", 0.0))))),
            "label": str(data.get("label", "irrelevant")),
            "reason": str(data.get("reason", ""))[:500],
        }

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _build_prompt(self, title: str, summary: str, keywords: list[str]) -> str:
        keyword_text = ", ".join(keywords[:30]) if keywords else ""
        compact_summary = summary.strip().replace("\n", " ")[: self.cfg.max_input_chars]
        return (
            "You are a paper relevance scorer.\n"
            "Return strict JSON with keys: score(0..1), label(high|medium|irrelevant), reason.\n"
            "Judge relevance against the user's interest keywords.\n\n"
            f"Keywords: {keyword_text}\n"
            f"Title: {title}\n"
            f"Summary: {compact_summary}\n"
        )

    def _call_openai_compatible(self, prompt: str) -> dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        def _post(payload: dict[str, Any]) -> dict[str, Any]:
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.cfg.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()

        def _call() -> dict[str, Any]:
            base_payload = {
                "model": self.cfg.model,
                "temperature": 0.0,
                "messages": [{"role": "user", "content": prompt}],
            }
            try:
                payload = {**base_payload, "response_format": {"type": "json_object"}}
                raw = _post(payload)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                # Some providers/local endpoints do not support response_format.
                if status in (400, 404, 415, 422):
                    raw = _post(base_payload)
                else:
                    raise

            content = raw["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
            parsed = self._parse_json_content(str(content))
            return self._normalize_result(parsed)

        return run_with_retry(
            _call,
            max_attempts=self.cfg.max_attempts,
            base_delay=1.0,
            max_delay=10.0,
            retry_exceptions=(requests.RequestException, KeyError, ValueError, json.JSONDecodeError),
        )

    def _call_gemini(self, prompt: str) -> dict[str, Any]:
        base = self.cfg.base_url.rstrip("/")
        url = f"{base}/v1beta/models/{self.cfg.model}:generateContent"

        def _call() -> dict[str, Any]:
            response = self.session.post(
                url,
                params={"key": self.cfg.api_key},
                json={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {"temperature": 0.0},
                },
                timeout=self.cfg.timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
            candidates = raw.get("candidates", [])
            if not candidates:
                raise ValueError("gemini empty candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("gemini empty content parts")
            text = str(parts[0].get("text", ""))
            parsed = self._parse_json_content(text)
            return self._normalize_result(parsed)

        return run_with_retry(
            _call,
            max_attempts=self.cfg.max_attempts,
            base_delay=1.0,
            max_delay=10.0,
            retry_exceptions=(requests.RequestException, KeyError, ValueError, json.JSONDecodeError),
        )

    def score(self, title: str, summary: str, keywords: list[str]) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        key = self._cache_key(title, summary, keywords)
        cache_path = self._cache_file(key)
        cached = read_json(cache_path, default=None)
        if cached is not None:
            return cached

        prompt = self._build_prompt(title, summary, keywords)

        try:
            if self.cfg.api_format == "gemini" or self.cfg.provider == "gemini":
                result = self._call_gemini(prompt)
            else:
                result = self._call_openai_compatible(prompt)
            atomic_write_json(cache_path, result)
            return result
        except Exception as exc:
            self.logger.warning("%s scoring failed: %s", self.cfg.provider, exc)
            return None
