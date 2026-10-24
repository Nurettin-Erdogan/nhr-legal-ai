"""Bulut dil modeli (Anthropic / OpenAI / DeepSeek) — yerel modelin yanında, isteğe bağlı ve varsayılanı KAPALI.

Neden: dizüstündeki 6 GB ekran kartına en çok 4 milyar parametrelik model sığıyor; kanun sorularında çelişkili cevap
yazıyor ve denetim onu eleyince kullanıcıya ham madde metni kalıyor (ölçüldü: 2026-10-19, TBK m. 344 sorusu).

Sınırlar (kod tarafında, prompt'ta değil):

* Yalnız genel hukuk sorusu gider. Dava, proje ya da seçili belge kapsamındaki soru ve kullanıcı belgesi içeren
  kaynak listesi hiçbir zaman buluta gönderilmez (`api.ai.pipeline` yönlendirir).
* Model yalnız bizim gönderdiğimiz kaynak metnini görür; doğal cevap iddiaları `api.ai.synthesis`
  içindeki kanıt ve anlam denetiminden geçer; tam alıntı geri dönüşü `api.ai.verification` ile denetlenir.
  Bulut modeli internette arama yapmaz, dışarıdan veri çekmez.
* Gönderilmeden önce kimlik numarası, telefon, e-posta ve IBAN maskelenir (`mask_personal_data`).
* Bulut hata verirse (ağ, kota, anahtar) aynı istek yerel modelle sürer (`FallbackProvider`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from typing import ClassVar

import httpx

from api.ai.providers import AIProvider, AIProviderError, GenerationUsage

logger = logging.getLogger(__name__)

CLOUD_PROVIDERS = frozenset({"anthropic", "openai", "deepseek", "openrouter"})
DEEPSEEK_DEFAULT_MODEL = "deepseek-flash"
DEEPSEEK_REASONING_EFFORTS = frozenset({"none", "low", "high", "max"})
# Resmî API teknik üst sınırı; uygulama/kullanıcı kotası değildir.
# https://api-docs.deepseek.com/api/create-chat-completion/ (21.10.2026)
DEEPSEEK_MAX_COMPLETION_TOKENS = 393216

_PERSONAL = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[e-posta]"),
    (re.compile(r"\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE), "[IBAN]"),
    (re.compile(r"(?<![\d/.-])[1-9]\d{10}(?![\d/.-])"), "[kimlik no]"),
    (re.compile(r"(?<![\d/.-])(?:\+90[\s-]?|0)?5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?![\d/.-])"), "[telefon]"),
)


def mask_personal_data(text: str) -> str:
    """Kimlik no (11 hane), telefon, e-posta ve IBAN'ı yer tutucuyla değiştirir; kanun/esas/karar numaralarına dokunmaz."""
    for pattern, placeholder in _PERSONAL:
        text = pattern.sub(placeholder, text)
    return text


def _wants_json(system_instruction: str) -> bool:
    return "yalnız json" in system_instruction.lower()


def _error_for(provider: str, exc: httpx.HTTPStatusError) -> AIProviderError:
    status = exc.response.status_code
    if status in {401, 403}:
        return AIProviderError(f"{provider} API anahtarı geçersiz ya da yetkisiz", status_code=503)
    if status == 402:
        return AIProviderError(f"{provider} API bakiyesi yetersiz", status_code=503)
    if status == 429:
        return AIProviderError(f"{provider} kullanım sınırı ya da bakiyesi doldu", status_code=503)
    if status >= 500:
        return AIProviderError(f"{provider} şu anda yanıt veremiyor", status_code=502)
    return AIProviderError(f"{provider} isteği reddetti ({status})", status_code=502)


def _rejects_param(exc: httpx.HTTPStatusError, name: str) -> bool:
    """Bazı yeni modeller `temperature` gibi ayarları kabul etmiyor: hata o ayarı anıyorsa ayarsız yeniden denenir."""
    if exc.response.status_code != 400:
        return False
    try:
        return name in exc.response.text
    except Exception:  # noqa: BLE001
        return False


@dataclass(slots=True)
class _CloudBase:
    optional_parameters: ClassVar[tuple[str, ...]] = ("temperature", "reasoning_effort")
    model: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 60.0
    max_output_tokens: int = 1024
    transport: httpx.BaseTransport | None = None
    last_usage: GenerationUsage | None = None

    def _post(self, url: str, headers: dict[str, str], payload: dict) -> dict:
        label = self.name.capitalize()  # type: ignore[attr-defined]
        with httpx.Client(timeout=self.timeout_seconds, transport=self.transport, trust_env=False) as client:
            for _attempt in range(3):
                try:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise AIProviderError(f"{label} yanıtı okunamadı")
                    return body
                except httpx.HTTPStatusError as exc:
                    dropped = next((name for name in self.optional_parameters
                                    if name in payload and _rejects_param(exc, name)), None)
                    if dropped is None:
                        raise _error_for(label, exc) from exc
                    payload = {key: value for key, value in payload.items() if key != dropped}
                except httpx.TimeoutException as exc:
                    raise AIProviderError(f"{label} yanıt süresini aştı", status_code=504) from exc
                except httpx.HTTPError as exc:
                    raise AIProviderError(f"{label} sunucusuna bağlanılamadı", status_code=503) from exc
                except ValueError as exc:
                    raise AIProviderError(f"{label} yanıtı okunamadı") from exc
        raise AIProviderError(f"{label} isteği reddetti")


_CLAUDE_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_CLAUDE_DEFAULT_MAX_TOKENS = 16000


@dataclass(slots=True)
class AnthropicProvider(_CloudBase):
    name: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    reasoning_effort: str = "low"

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        # Current Claude models: sampling parameters (temperature/top_p/top_k) are rejected with a 400 since 2026-10-21,
        # thinking is adaptive and depth is set with output_config.effort; max_tokens is mandatory (0 = "no app cap" in
        # .env means a generous ceiling here). Thinking blocks are never shown — only text blocks are read below.
        effort = self.reasoning_effort if self.reasoning_effort in _CLAUDE_EFFORTS else "low"
        payload = {
            "model": self.model,
            "max_tokens": self.max_output_tokens if self.max_output_tokens > 0 else _CLAUDE_DEFAULT_MAX_TOKENS,
            "output_config": {"effort": effort},
            "system": mask_personal_data(system_instruction),
            "messages": [{"role": "user", "content": mask_personal_data(prompt)}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = self._post(f"{self.base_url}/v1/messages", headers, payload)
        text = "".join(block.get("text", "") for block in body.get("content") or []
                       if isinstance(block, dict) and block.get("type") == "text").strip()
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        stop = body.get("stop_reason") if isinstance(body.get("stop_reason"), str) else None
        self.last_usage = GenerationUsage(prompt_eval_count=usage.get("input_tokens"), eval_count=usage.get("output_tokens"),
                                          done_reason=stop, num_predict=self.max_output_tokens)
        if stop == "refusal":
            raise AIProviderError("Anthropic isteği güvenlik nedeniyle yanıtlamadı")
        if stop == "max_tokens":
            raise AIProviderError("Anthropic yanıtı token sınırında kesildi", partial=text)
        if not text:
            raise AIProviderError("Anthropic boş bir yanıt döndürdü")
        return text


@dataclass(slots=True)
class OpenAIProvider(_CloudBase):
    name: str = "openai"
    base_url: str = "https://api.openai.com"
    max_tokens_field: str = "max_completion_tokens"
    json_mode: ClassVar[bool] = True

    def _generation_options(self) -> dict:
        options: dict = {"temperature": 0}
        if self.model.lower().startswith(("gpt-5", "o")):
            options["reasoning_effort"] = "low"
        return options

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        self.last_usage = None
        payload: dict = {
            "model": self.model,
            **({self.max_tokens_field: self.max_output_tokens} if self.max_output_tokens > 0 else {}),
            **self._generation_options(),
            "messages": [
                {"role": "system", "content": mask_personal_data(system_instruction)},
                {"role": "user", "content": mask_personal_data(prompt)},
            ],
        }
        if self.json_mode and _wants_json(system_instruction):
            payload["response_format"] = {"type": "json_object"}
        headers = {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        body = self._post(f"{self.base_url}/v1/chat/completions", headers, payload)
        choices = body.get("choices")
        if not isinstance(choices, list):
            raise AIProviderError(f"{self.name} yanıtı okunamadı")
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = (message.get("content") or "").strip() if isinstance(message.get("content"), str) else ""
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        finish = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
        self.last_usage = GenerationUsage(prompt_eval_count=usage.get("prompt_tokens"),
                                          eval_count=usage.get("completion_tokens"),
                                          done_reason=finish, num_predict=self.max_output_tokens or None)
        if finish == "length":
            raise AIProviderError(f"{self.name} yanıtı token sınırında kesildi", partial=text)
        if not text:
            # reasoning_content iç yanıt değildir; kullanıcıya veya doğrulayıcıya aktarılmaz.
            raise AIProviderError(f"{self.name} boş bir yanıt döndürdü")
        if finish != "stop":
            raise AIProviderError(f"{self.name} tamamlanmamış bir yanıt döndürdü")
        return text


@dataclass(slots=True)
class DeepSeekCloudProvider(OpenAIProvider):
    """DeepSeek API (OpenAI uyumlu uç nokta). Sunucuları Çin'dedir: yalnız genel soru gider, kimlik bilgileri maskelenir.

    Yerel Ollama'daki DeepSeek modelinden (`AI_PROVIDER=deepseek`) ayrıdır; bu sınıf DeepSeek'in kendi sunucusunu kullanır.
    """

    name: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    max_tokens_field: str = "max_tokens"
    # 0: uygulama çıktı kotası koymaz; API'nin model/mod varsayılanı kullanılır.
    max_output_tokens: int = 0
    reasoning_effort: str = "low"
    # Belirlenen bütçe/mod ayarını sessizce düşürüp sağlayıcının high varsayılanına geçme.
    optional_parameters: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        if self.reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
            raise AIProviderError("DeepSeek düşünme seviyesi none, low, high veya max olmalı", status_code=503)
        if not 0 <= self.max_output_tokens <= DEEPSEEK_MAX_COMPLETION_TOKENS:
            raise AIProviderError("DeepSeek çıktı ayarı sağlayıcının teknik aralığında olmalı", status_code=503)

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        try:
            return OpenAIProvider.generate(self, system_instruction=system_instruction, prompt=prompt)
        except AIProviderError:
            first_usage = self.last_usage
            if self.max_output_tokens != 0 or first_usage is None or first_usage.done_reason != "length":
                raise
        # Varsayılan pencere yetmediyse aynı kanıt/isteği teknik azami kapasiteyle
        # bir kez yeniden üret. JSON/kaynak cümleleri yarım yanıtla birleştirilmez.
        # Ağ/yetki/bakiye hatası yeniden denenmez; sonsuz üretim döngüsü yoktur.
        expanded = replace(self, max_output_tokens=DEEPSEEK_MAX_COMPLETION_TOKENS)
        try:
            return OpenAIProvider.generate(expanded, system_instruction=system_instruction, prompt=prompt)
        finally:
            last = expanded.last_usage
            if last is not None:
                self.last_usage = replace(last,
                    prompt_eval_count=(first_usage.prompt_eval_count + last.prompt_eval_count
                        if first_usage.prompt_eval_count is not None and last.prompt_eval_count is not None else None),
                    eval_count=(first_usage.eval_count + last.eval_count
                        if first_usage.eval_count is not None and last.eval_count is not None else None))
            else:
                self.last_usage = replace(first_usage, done_reason=None)

    def _generation_options(self) -> dict:
        return {
            "thinking": {"type": "disabled" if self.reasoning_effort == "none" else "enabled"},
            "reasoning_effort": self.reasoning_effort,
        }

    def generate_auxiliary(self, *, system_instruction: str, prompt: str) -> str:
        # Kısa özet/JSON kontrolü için max düşünme 16K tokenı tüketebiliyor
        # (canlı ölçüm: 20.10.2026, 102 sn). Model aynı Pro kalır; yalnız yardımcı
        # çağrının düşünmesi kapanır. 21.10.2026: yanıtı kesen ayrı 2048 token /
        # 45 sn yardımcı tavanı kaldırıldı; ana çağrının çıktı politikası korunur.
        auxiliary = replace(self, reasoning_effort="none")
        try:
            return auxiliary.generate(system_instruction=system_instruction, prompt=prompt)
        finally:
            self.last_usage = auxiliary.last_usage


OPENROUTER_PREFERRED_HOSTS = ("Azure", "Parasail", "DeepInfra")


@dataclass(slots=True)
class OpenRouterDeepSeekProvider(DeepSeekCloudProvider):
    """The same DeepSeek models through OpenRouter (OpenAI-compatible; a Turkish card could not top up DeepSeek directly,
    2026-10-23). Same guards as the DeepSeek pilot: only general questions, masked identifiers, local fallback. Reasoning
    is set with OpenRouter's unified ``reasoning`` field instead of DeepSeek's own ``thinking`` parameters."""

    name: str = "openrouter"
    base_url: str = "https://openrouter.ai/api"
    # Azure (the fastest host) returns EMPTY content when response_format=json_object is set, and valid JSON without it
    # (2026-10-24). The instruction already demands JSON and every output is parsed and checked server-side.
    json_mode: ClassVar[bool] = False

    def _generation_options(self) -> dict:
        # Preferred hosts, measured 2026-10-24 on the same legal prompt: Azure 4.8 s (835 tokens, 172 tk/s), Parasail 4.7 s,
        # DeepInfra 11.9 s. "Sort by throughput" picked hosts that ignore effort=low and think 4-6k tokens (Wafer 46 s,
        # DigitalOcean 61 s). Others stay as fallbacks within the account's privacy settings; no host in China is preferred.
        routing = {"provider": {"order": list(OPENROUTER_PREFERRED_HOSTS)}}
        if self.reasoning_effort == "none":
            return {"reasoning": {"enabled": False}, **routing}
        return {"reasoning": {"effort": "high" if self.reasoning_effort == "max" else self.reasoning_effort}, **routing}


OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


@dataclass(slots=True)
class FallbackProvider:
    """Bulut hata verirse bu isteğin kalan çağrıları yerelde kalır; gerçek sağlayıcı raporlanır."""

    primary: AIProvider
    fallback: AIProvider
    fell_back: bool = False

    @property
    def name(self) -> str:
        return (self.fallback if self.fell_back else self.primary).name

    @property
    def model(self) -> str:
        return (self.fallback if self.fell_back else self.primary).model

    @property
    def last_usage(self) -> GenerationUsage | None:
        source = self.fallback if self.fell_back else self.primary
        return getattr(source, "last_usage", None)

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        return self._generate(system_instruction=system_instruction, prompt=prompt, auxiliary=False)

    def generate_auxiliary(self, *, system_instruction: str, prompt: str) -> str:
        return self._generate(system_instruction=system_instruction, prompt=prompt, auxiliary=True)

    def _generate(self, *, system_instruction: str, prompt: str, auxiliary: bool) -> str:
        if self.fell_back:
            return self._generate_local(system_instruction=system_instruction, prompt=prompt)
        try:
            generate = (getattr(self.primary, "generate_auxiliary", self.primary.generate)
                        if auxiliary else self.primary.generate)
            return generate(system_instruction=system_instruction, prompt=prompt)
        except AIProviderError as exc:
            if exc.partial:
                raise  # kesilen çıktı çağırana bırakılır (madde özeti tamamlanmış satırları kullanır)
            logger.warning("Bulut modeli kullanılamadı (%s); yerel modelle sürüyor", exc)
            self.fell_back = True
            return self._generate_local(system_instruction=system_instruction, prompt=prompt)

    def _generate_local(self, *, system_instruction: str, prompt: str) -> str:
        from api.embed_pause import local_generation_pause
        with local_generation_pause():
            return self.fallback.generate(system_instruction=system_instruction, prompt=prompt)


@dataclass(slots=True)
class AuxiliaryProvider:
    """Aynı sağlayıcı/model, yardımcı işlere özel sınırlı çağrı; yerelde davranış değişmez."""

    base: AIProvider

    @property
    def name(self) -> str:
        return self.base.name

    @property
    def model(self) -> str:
        return self.base.model

    @property
    def last_usage(self) -> GenerationUsage | None:
        return getattr(self.base, "last_usage", None)

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        generate = getattr(self.base, "generate_auxiliary", self.base.generate)
        return generate(system_instruction=system_instruction, prompt=prompt)


def create_cloud_provider(*, provider_name: str, model: str, api_key: str, timeout_seconds: float = 60.0,
                          max_output_tokens: int | None = None, reasoning_effort: str = "low") -> AIProvider:
    if not api_key:
        raise AIProviderError(f"{provider_name} için API anahtarı tanımlı değil", status_code=503)
    if provider_name == "anthropic":
        return AnthropicProvider(model=model or "claude-haiku-5-5", api_key=api_key, timeout_seconds=timeout_seconds,
                                 max_output_tokens=0 if max_output_tokens is None else max_output_tokens,
                                 reasoning_effort=reasoning_effort)
    if provider_name == "openai":
        return OpenAIProvider(model=model, api_key=api_key, timeout_seconds=timeout_seconds,
                              max_output_tokens=1024 if max_output_tokens is None else max_output_tokens)
    if provider_name == "deepseek":
        return DeepSeekCloudProvider(model=model or DEEPSEEK_DEFAULT_MODEL, api_key=api_key,
                                     timeout_seconds=timeout_seconds, max_output_tokens=0 if max_output_tokens is None else max_output_tokens,
                                     reasoning_effort=reasoning_effort)
    if provider_name == "openrouter":
        return OpenRouterDeepSeekProvider(model=model or OPENROUTER_DEFAULT_MODEL, api_key=api_key,
                                          timeout_seconds=timeout_seconds,
                                          max_output_tokens=0 if max_output_tokens is None else max_output_tokens,
                                          reasoning_effort=reasoning_effort)
    raise AIProviderError(f"Desteklenmeyen bulut sağlayıcısı: {provider_name}")
