"""Per-request count of model calls, for finding where an answer's time goes.

Counts calls, wall seconds, and characters sent/received; token counts are added only when the provider reports them. Prompt text
and answers are never stored or logged, only sizes. Thread-safe: parts are written and checked in parallel.
"""

from threading import Lock
from time import monotonic

from api.ai.providers import OllamaProvider


class LLMMeter:
    def __init__(self):
        self._lock = Lock()
        self.calls = 0
        self.errors = 0
        self.seconds = 0.0
        self.longest = 0.0
        self.prompt_chars = 0
        self.output_chars = 0
        self.prompt_tokens = 0
        self.output_tokens = 0

    def record(self, *, seconds: float, prompt_chars: int, output_chars: int, usage, failed: bool) -> None:
        with self._lock:
            self.calls += 1
            self.errors += int(failed)
            self.seconds += seconds
            self.longest = max(self.longest, seconds)
            self.prompt_chars += prompt_chars
            self.output_chars += output_chars
            self.prompt_tokens += int(getattr(usage, "prompt_eval_count", 0) or 0)
            self.output_tokens += int(getattr(usage, "eval_count", 0) or 0)

    def summary(self) -> dict:
        with self._lock:
            return dict(calls=self.calls, errors=self.errors, call_seconds=round(self.seconds, 1), longest_call=round(self.longest, 1),
                        prompt_chars=self.prompt_chars, output_chars=self.output_chars,
                        prompt_tokens=self.prompt_tokens, output_tokens=self.output_tokens)


class MeteredProvider:
    """The same provider whose `generate` is counted; everything else is passed through."""

    def __init__(self, inner, meter: LLMMeter):
        self._inner, self._meter = inner, meter

    def generate(self, **kwargs):
        started, output, failed = monotonic(), "", True
        try:
            output = self._inner.generate(**kwargs)
            failed = False
            return output
        finally:
            self._meter.record(seconds=monotonic() - started,
                               prompt_chars=len(kwargs.get("prompt", "")) + len(kwargs.get("system_instruction", "")),
                               output_chars=len(output or ""), usage=getattr(self._inner, "last_usage", None), failed=failed)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def metered(provider, meter: LLMMeter):
    """Local Ollama providers are returned as they are: callers branch on their concrete type."""
    return provider if provider is None or isinstance(provider, OllamaProvider) else MeteredProvider(provider, meter)
