from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(slots=True)
class OllamaProvider:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 180.0
    max_output_tokens: int = 512
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
        try:
            with self._client(min(self.timeout_seconds, 2.0)) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                models = response.json()["models"]
            expected = self.model if ":" in self.model else f"{self.model}:latest"
            return any(
                isinstance(item, dict)
                and (item.get("name") == expected or item.get("model") == expected)
                for item in models
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return False

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        try:
            with self._client(self.timeout_seconds) as client:
                response = client.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                        "think": False,
                        "options": {
                            "temperature": 0.15,
                            "num_predict": self.max_output_tokens,
                        },
                    },
                )
                response.raise_for_status()
                answer = response.json()["message"]["content"]
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
        if not isinstance(answer, str) or not answer.strip():
            raise AIProviderError("Ollama boş bir yanıt döndürdü")
        return answer.strip()


DeepSeekProvider = OllamaProvider


def create_provider(
    *,
    provider_name: str,
    model: str,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_timeout_seconds: float = 180.0,
    ollama_max_output_tokens: int = 512,
) -> AIProvider:
    if provider_name in LOCAL_OLLAMA_PROVIDERS:
        return OllamaProvider(
            model=model,
            name=provider_name,
            base_url=ollama_base_url,
            timeout_seconds=ollama_timeout_seconds,
            max_output_tokens=ollama_max_output_tokens,
        )
    raise AIProviderError(f"Desteklenmeyen AI sağlayıcısı: {provider_name}")
