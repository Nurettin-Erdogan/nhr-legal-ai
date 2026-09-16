from __future__ import annotations

import re
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit

import httpx


class AIProviderError(RuntimeError):
    """An AI provider could not generate a usable response."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class AIProvider(Protocol):
    name: str
    model: str

    def generate(self, *, system_instruction: str, prompt: str) -> str: ...


LOCAL_OLLAMA_PROVIDERS = frozenset({"deepseek", "ollama"})
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_AVAILABILITY_TTL_SECONDS = 30.0
_availability_cache: dict[tuple[str, str], tuple[float, bool]] = {}


def _visible_answer(content: object) -> str:
    if not isinstance(content, str):
        return ""
    return _THINK_BLOCK.sub("", content).strip()


@dataclass(slots=True)
class OllamaProvider:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120.0
    max_output_tokens: int = 384
    num_ctx: int = 1536
    keep_alive: str = "30m"
    name: str = "deepseek"
    transport: httpx.BaseTransport | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise AIProviderError("OLLAMA_BASE_URL geçerli bir sunucu adresi olmalı", status_code=503)

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=timeout,
            transport=self.transport,
            trust_env=False,
        )

    def is_available(self) -> bool:
        key = (self.base_url.rstrip("/"), self.model)
        cached = _availability_cache.get(key)
        now = monotonic()
        if cached is not None and now - cached[0] < _AVAILABILITY_TTL_SECONDS:
            return cached[1]
        try:
            with self._client(min(self.timeout_seconds, 0.8)) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                models = response.json()["models"]
            expected = self.model if ":" in self.model else f"{self.model}:latest"
            available = any(
                isinstance(item, dict)
                and (item.get("name") == expected or item.get("model") == expected)
                for item in models
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            available = False
        _availability_cache[key] = (now, available)
        return available

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        if "r1" in self.model.lower():
            return self._generate_r1(system_instruction=system_instruction, prompt=prompt)
        return self._generate_chat(system_instruction=system_instruction, prompt=prompt)

    def _chat_payload(self, *, system_instruction: str, prompt: str) -> dict[str, object]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": self._options(),
        }

    def _options(self) -> dict[str, int | float]:
        return {
            "temperature": 0.15,
            "num_predict": self.max_output_tokens,
            "num_ctx": self.num_ctx,
        }

    def _generate_r1(self, *, system_instruction: str, prompt: str) -> str:
        # This local DeepSeek-R1 model uses DeepSeek-specific role tokens,
        # not ChatML. Close its reasoning block before answer generation.
        raw_prompt = (
            "<｜begin▁of▁sentence｜>"
            f"{system_instruction}<｜User｜>"
            f"{prompt}<｜Assistant｜>"
            "<think>\n</think>\n"
        )
        return self._complete(
            "/api/generate",
            {
                "model": self.model,
                "prompt": raw_prompt,
                "raw": True,
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {
                    **self._options(),
                    "stop": ["<｜end▁of▁sentence｜>", "<｜User｜>", "<｜Assistant｜>"],
                },
            },
            answer_key="response",
        )

    def _generate_chat(self, *, system_instruction: str, prompt: str) -> str:
        return self._complete(
            "/api/chat",
            self._chat_payload(system_instruction=system_instruction, prompt=prompt),
            answer_key="message",
        )

    def _complete(self, path: str, payload: dict[str, object], *, answer_key: str) -> str:
        try:
            with self._client(self.timeout_seconds) as client:
                response = client.post(path, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise AIProviderError("Ollama yanıt süresini aştı", status_code=504) from exc
        except httpx.ConnectError as exc:
            raise AIProviderError("Ollama sunucusuna bağlanılamadı", status_code=503) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise AIProviderError(
                    f"Ollama modeli bulunamadı: {self.model}. Önce ollama pull {self.model} çalıştırın.",
                    status_code=503,
                ) from exc
            raise AIProviderError("Ollama yanıt üretemedi") from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise AIProviderError("Ollama yanıtı okunamadı") from exc
        if isinstance(body, dict) and body.get("done_reason") == "length":
            raise AIProviderError("Ollama yanıtı token sınırında kesildi; çıktı sınırını artırın")
        if answer_key == "message":
            message = body.get("message") if isinstance(body, dict) else None
            content = message.get("content") if isinstance(message, dict) else ""
        else:
            content = body.get("response") if isinstance(body, dict) else ""
        answer = _visible_answer(content)
        if not answer:
            raise AIProviderError("Ollama boş bir yanıt döndürdü")
        return answer


DeepSeekProvider = OllamaProvider


def create_provider(
    *,
    provider_name: str,
    model: str,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_timeout_seconds: float = 120.0,
    ollama_max_output_tokens: int = 384,
    ollama_num_ctx: int = 1536,
    ollama_keep_alive: str = "30m",
) -> AIProvider:
    if provider_name in LOCAL_OLLAMA_PROVIDERS:
        return OllamaProvider(
            model=model,
            name=provider_name,
            base_url=ollama_base_url,
            timeout_seconds=ollama_timeout_seconds,
            max_output_tokens=ollama_max_output_tokens,
            num_ctx=ollama_num_ctx,
            keep_alive=ollama_keep_alive,
        )
    raise AIProviderError(f"Desteklenmeyen AI sağlayıcısı: {provider_name}")
