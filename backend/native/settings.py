import os
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from backend.app.llm_client import LLMSettings, load_settings, public_status
from .contracts import Contract, WorkspaceError
from .documents import write_json


class ModelConfiguration(Contract):
    model: str = Field(min_length=1, max_length=300)
    base_url: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(default="", max_length=8000)
    timeout: float = Field(default=90, gt=0, le=600)
    json_mode: bool = False

    @field_validator("api_key")
    @classmethod
    def key_is_header_text(cls, value):
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("The API key must contain printable ASCII characters.")
        return value.strip()


def config_path():
    return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "PromptToCAD" / "model.json"


def load():
    path = config_path()
    if path.exists():
        try:
            apply(ModelConfiguration.model_validate_json(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            import warnings
            warnings.warn("Saved model settings could not be read. Configure the connection in Settings.", RuntimeWarning)


def apply(config):
    for name, value in {"LLM_MODEL": config.model, "LLM_BASE_URL": config.base_url,
                        "LLM_API_KEY": config.api_key, "LLM_TIMEOUT_SECONDS": str(config.timeout),
                        "LLM_JSON_MODE": str(config.json_mode).lower()}.items():
        os.environ[name] = value


def public():
    settings = load_settings()
    return {"model": settings.model, "base_url": settings.base_url, "timeout": settings.timeout,
            "json_mode": settings.json_mode, "has_api_key": bool(settings.api_key),
            "configured": public_status()["configured"]}


def save(params):
    try:
        config = ModelConfiguration.model_validate(params)
    except ValidationError as error:
        raise WorkspaceError("Enter a valid model, API URL, key and request timeout.", "invalid_settings") from error
    current = load_settings()
    if not config.api_key and config.base_url.rstrip("/") == current.base_url.rstrip("/"):
        config.api_key = current.api_key
    LLMSettings(model=config.model, base_url=config.base_url, api_key=config.api_key,
                timeout=config.timeout, json_mode=config.json_mode).check()
    write_json(config_path(), config.model_dump())
    apply(config)
    return public()
