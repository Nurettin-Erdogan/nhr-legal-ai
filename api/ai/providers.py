from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AIProviderError(RuntimeError):
    """An AI provider could not generate a usable response."""


class AIProvider(Protocol):
    name: str
    model: str

    def generate(self, *, system_instruction: str, prompt: str) -> str: ...


@dataclass(slots=True)
class GeminiProvider:
    api_key: str
    model: str
    name: str = "gemini"

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.15,
                    max_output_tokens=1800,
                ),
            )
        except Exception as exc:
            raise AIProviderError(f"Gemini isteği başarısız: {exc}") from exc

        answer = (response.text or "").strip()
        if not answer:
            raise AIProviderError("Gemini boş bir yanıt döndürdü")
        return answer


def create_provider(*, provider_name: str, api_key: str | None, model: str) -> AIProvider:
    if provider_name == "gemini":
        if not api_key:
            raise AIProviderError("GEMINI_API_KEY tanımlı değil")
        return GeminiProvider(api_key=api_key, model=model)
    raise AIProviderError(f"Desteklenmeyen AI sağlayıcısı: {provider_name}")
