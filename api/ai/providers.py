from __future__ import annotations

from dataclasses import dataclass
from time import sleep
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


@dataclass(slots=True)
class GeminiProvider:
    api_key: str
    model: str
    name: str = "gemini"
    max_attempts: int = 3

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        message = str(exc).lower()
        if "prepayment credits are depleted" in message:
            return False
        code = getattr(exc, "code", None)
        if code in {429, 500, 502, 503, 504}:
            return True
        return any(
            marker in message
            for marker in ("429", "500", "502", "503", "504", "high demand", "unavailable")
        )

    @staticmethod
    def _public_error(exc: Exception) -> AIProviderError:
        message = str(exc).lower()
        if "prepayment credits are depleted" in message:
            return AIProviderError(
                "Gemini kullanım kredisi tükenmiş. Google AI Studio'da projeye kredi "
                "ekleyin veya ücretsiz kotası bulunan başka bir proje anahtarı kullanın.",
                status_code=429,
            )
        if getattr(exc, "code", None) == 429 or "resource_exhausted" in message:
            return AIProviderError(
                "Gemini kullanım kotasına ulaşıldı. Bir süre sonra yeniden deneyin.",
                status_code=429,
            )
        if getattr(exc, "code", None) in {401, 403} or "api key" in message:
            return AIProviderError(
                "Gemini API anahtarı geçersiz veya bu model için yetkisiz.",
                status_code=503,
            )
        return AIProviderError(
            "Gemini şu anda yanıt üretemedi. Lütfen daha sonra yeniden deneyin.",
            status_code=502,
        )

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.15,
                        max_output_tokens=1800,
                    ),
                )
                break
            except Exception as exc:
                if attempt == self.max_attempts or not self._is_transient(exc):
                    raise self._public_error(exc) from exc
                sleep(1.5 * (2 ** (attempt - 1)))

        answer = (response.text or "").strip() if response else ""
        if not answer:
            raise AIProviderError("Gemini boş bir yanıt döndürdü")
        return answer


@dataclass(slots=True)
class QwenProvider:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120.0
    name: str = "qwen"
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
                        "options": {"temperature": 0.15, "num_predict": 1800},
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


def create_provider(
    *, provider_name: str, api_key: str | None, model: str,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_timeout_seconds: float = 120.0,
) -> AIProvider:
    if provider_name == "gemini":
        if not api_key:
            raise AIProviderError("GEMINI_API_KEY tanımlı değil")
        return GeminiProvider(api_key=api_key, model=model)
    if provider_name == "qwen":
        return QwenProvider(
            model=model,
            base_url=ollama_base_url,
            timeout_seconds=ollama_timeout_seconds,
        )
    raise AIProviderError(f"Desteklenmeyen AI sağlayıcısı: {provider_name}")
