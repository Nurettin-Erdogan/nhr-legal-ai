from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Protocol


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


def create_provider(*, provider_name: str, api_key: str | None, model: str) -> AIProvider:
    if provider_name == "gemini":
        if not api_key:
            raise AIProviderError("GEMINI_API_KEY tanımlı değil")
        return GeminiProvider(api_key=api_key, model=model)
    raise AIProviderError(f"Desteklenmeyen AI sağlayıcısı: {provider_name}")
