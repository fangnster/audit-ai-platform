"""
LLM Provider — MiniMax-first, OpenAI-compatible generic adapter.

MiniMax exposes an OpenAI-compatible /v1/chat/completions endpoint,
so we use the openai SDK with a custom base_url.  The same class can
drive Claude, GPT-4o, Gemini (via LiteLLM) or any OpenAI-compat API.
"""
from __future__ import annotations

import time
import logging
import re
import hashlib
import json
from dataclasses import dataclass
from typing import Optional

import httpx
from app.config import settings
from app.services.cache import get_json, set_json

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    base_url: str
    model: str


class LLMProviderError(RuntimeError):
    """Raised when an upstream LLM provider returns an invalid response."""


def strip_think_tags(value: str) -> str:
    """Remove reasoning blocks returned by thinking models before storing/displaying text."""
    if not value:
        return ""
    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"^\s*<think\b[^>]*>.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


class LLMService:
    """
    Unified LLM call interface.

    Priority for model/key selection:
      explicit args  >  saved model settings  >  env config  >  defaults
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider or settings.LLM_PROVIDER
        self.api_key = api_key or settings.LLM_API_KEY
        self.base_url = base_url or settings.LLM_BASE_URL
        self.model = model or settings.LLM_MODEL

    @classmethod
    def from_org_settings(cls, org_settings: Optional[dict] = None) -> "LLMService":
        """Compatibility alias for saved model settings."""
        org_settings = org_settings or {}
        return cls(
            provider=org_settings.get("llm_provider"),
            api_key=org_settings.get("api_key"),
            base_url=org_settings.get("llm_base_url"),
            model=org_settings.get("llm_model"),
        )

    def _resolve_config(
        self,
        org_settings: Optional[dict] = None,
        *,
        model: Optional[str] = None,
    ) -> LLMConfig:
        org_settings = org_settings or {}
        provider = (org_settings.get("llm_provider") or self.provider or "openai").strip()
        api_key = (org_settings.get("api_key") or self.api_key or "").strip()
        base_url = (org_settings.get("llm_base_url") or self.base_url or "https://api.openai.com/v1").strip().rstrip("/")
        resolved_model = (model or org_settings.get("llm_model") or self.model or "").strip()

        if not resolved_model:
            raise LLMProviderError("LLM model is not configured")
        if not api_key and provider not in {"ollama", "local"}:
            raise LLMProviderError("LLM API key is not configured")

        return LLMConfig(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=resolved_model,
        )

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------
    async def generate(
        self,
        prompt: str,
        system: str = "You are a professional immigration lawyer assistant.",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        org_settings: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        model_key: Optional[str] = None,
    ) -> str:
        """Generate text. Returns the assistant message content string."""
        resolved_system = system_prompt or system
        config = self._resolve_config(org_settings, model=model_key)
        cache_key = self._cache_key(config, prompt, resolved_system, temperature, max_tokens)
        cached = await get_json(cache_key) if settings.LLM_CACHE_ENABLED else None
        if isinstance(cached, str):
            logger.info("LLM [%s/%s] CACHE_HIT prompt_len=%s", config.provider, config.model, len(prompt))
            return cached
        start = time.time()
        try:
            result = await self._call_openai_compat(config, prompt, resolved_system, temperature, max_tokens)
            elapsed = int((time.time() - start) * 1000)
            logger.info("LLM [%s/%s] OK %sms prompt_len=%s", config.provider, config.model, elapsed, len(prompt))
            cleaned = strip_think_tags(result)
            if not cleaned.strip():
                raise LLMProviderError("LLM returned no visible content after reasoning tags were removed")
            if settings.LLM_CACHE_ENABLED:
                await set_json(cache_key, cleaned, settings.LLM_CACHE_TTL_SECONDS)
            return cleaned
        except Exception as e:
            logger.error("LLM [%s] ERROR: %s", config.model, e)
            raise

    @staticmethod
    def _cache_key(
        config: LLMConfig,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "system": system,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        return f"llm:{digest}"

    async def _call_openai_compat(
        self,
        config: LLMConfig,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """
        Call any OpenAI-compatible endpoint (MiniMax, OpenAI, Ollama, Azure…).
        Uses raw httpx to avoid extra SDK dependencies.
        """
        url = f"{config.base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
        }
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        payload = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise LLMProviderError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
            return self._extract_chat_content(resp.json())

    @staticmethod
    def _extract_chat_content(data: dict) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"Invalid LLM response shape: {data}") from exc
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {None, "text"}
            ]
            content = "".join(text_parts)
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("LLM returned empty content")
        return content.strip()

    # ------------------------------------------------------------------
    # Convenience methods used by agents
    # ------------------------------------------------------------------
    async def extract_json(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        """Call LLM expecting JSON output. Strips reasoning tags automatically."""
        json_system = (system or "You are a data extraction assistant.") + \
                      "\nAlways respond with valid JSON only, no markdown fences, no explanations."
        result = await self.generate(prompt, system=json_system, temperature=0.0, max_tokens=max_tokens)
        return strip_think_tags(result)

    async def translate(
        self,
        content: str,
        source_lang: str,
        target_lang: str,
        glossary: Optional[dict] = None,
        org_settings: Optional[dict] = None,
    ) -> str:
        """Legal-quality translation."""
        gloss_str = ""
        if glossary:
            gloss_str = "\n\nMandatory glossary (use these exact terms):\n" + \
                        "\n".join(f"  {k} → {v}" for k, v in glossary.items())

        system = (
            "You are a professional legal translator specializing in US immigration documents. "
            "Preserve all legal terminology precisely. Keep proper nouns unchanged. "
            "Maintain formal legal writing tone."
        )
        prompt = (
            f"Translate the following from {source_lang} to {target_lang}."
            f"{gloss_str}\n\n"
            f"--- Content ---\n{content}\n--- End ---\n\n"
            f"Return ONLY the translated text, no explanations."
        )
        max_tokens = min(4096, max(1024, len(content) + 512))
        return await self.generate(
            prompt,
            system=system,
            temperature=0.0,
            max_tokens=max_tokens,
            org_settings=org_settings,
        )


# Module-level singleton — use this in agents
llm_service = LLMService()
