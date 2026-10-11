import json
import math
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

from .config import PROJECT_ROOT


class LLMError(Exception):
    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LLMSettings:
    model: str
    base_url: str = field(repr=False)
    api_key: str = field(default="", repr=False)
    provider: str = "custom"
    timeout: float = 90.0
    json_mode: bool = False

    def check(self):
        if not self.model or not self.base_url:
            raise LLMError("Set LLM_BASE_URL and LLM_MODEL in backend/.env and restart the app.", "configuration")
        try:
            url = urlsplit(self.base_url)
            valid = (url.scheme in ("http", "https") and url.hostname and url.port != 0
                     and not url.username and not url.password and not url.query and not url.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise LLMError("LLM_BASE_URL must be an HTTP(S) API base URL without credentials, query or fragment.", "configuration")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise LLMError("LLM_TIMEOUT_SECONDS must be a positive number.", "configuration")


def load_settings(provider: str | None = None, model: str | None = None) -> LLMSettings:
    load_dotenv(PROJECT_ROOT / "backend" / ".env", override=False)
    try:
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout = float("nan")
    return LLMSettings(
        provider=(provider or os.getenv("LLM_PROVIDER", "custom")).strip() or "custom",
        model=(model if model is not None else os.getenv("LLM_MODEL", "")).strip(),
        base_url=os.getenv("LLM_BASE_URL", "").strip().rstrip("/"),
        api_key=os.getenv("LLM_API_KEY", "").strip(), timeout=timeout,
        json_mode=os.getenv("LLM_JSON_MODE", "false").strip().lower() == "true",
    )


def public_status() -> dict:
    settings = load_settings()
    result = {"provider": settings.provider, "model": settings.model, "configured": True,
              "message": "Ready for prompt interpretation."}
    try:
        settings.check()
    except LLMError as error:
        result.update(configured=False, message=str(error))
    return result


@dataclass(frozen=True)
class LLMResponse:
    text: str
    seconds: float
    input_tokens: int | None
    output_tokens: int | None


def generate_json(system_prompt: str, prompt: str,
                  settings: LLMSettings | None = None, *, max_tokens: int = 1800) -> LLMResponse:
    settings = settings or load_settings()
    settings.check()
    started = time.perf_counter()
    url = f"{settings.base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
    payload = {
        "model": settings.model,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": prompt}],
        "temperature": 0, "max_tokens": max_tokens,
    }
    if settings.json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        # One request, with no hidden SDK retries or cross-provider failover.
        with httpx.Client(timeout=httpx.Timeout(settings.timeout, connect=10.0),
                          follow_redirects=False) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as error:
        raise LLMError("The model took too long to respond. Try again or increase LLM_TIMEOUT_SECONDS.", "timeout") from error
    except httpx.RequestError as error:
        raise LLMError("The model provider could not be reached.", "network") from error
    if response.status_code == 429:
        raise LLMError("The provider quota or rate limit was reached. Wait and retry; no paid fallback was used.", "quota")
    if response.status_code in (401, 403):
        raise LLMError("The provider rejected access. Check the backend key and account permissions.", "access")
    if response.status_code != 200:
        raise LLMError(f"The provider rejected the request (HTTP {response.status_code}).", "provider_error")
    try:
        data = response.json()
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if finish == "length":
            raise LLMError("The response exceeded the output limit. No CAD model was constructed.", "truncated")
        if not isinstance(text, str) or not text.strip():
            raise LLMError("The model returned no usable JSON.", "empty_response")
        json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMError("The model returned an invalid JSON response. No CAD model was constructed.", "invalid_json") from error
    return LLMResponse(text, time.perf_counter() - started, input_tokens, output_tokens)
