import os
import httpx
from openai import AsyncAzureOpenAI, AzureOpenAI, AsyncOpenAI, OpenAI
from dotenv import load_dotenv, find_dotenv

# tries to find .env in current path, or traverses parent directories until found
dotenv_path = find_dotenv()

load_dotenv(dotenv_path)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://agenthiack.openai.azure.com/")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.groq.com/openai/v1"


def _first_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    try:
        return max(min_value, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, *, min_value: float = 0.1) -> float:
    try:
        return max(min_value, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def get_openai_compatible_config() -> tuple[str, str]:
    """Return API key and base URL for OpenAI-compatible providers.

    LLM_* variables are canonical for MetaRec. OPENAI_COMPAT* aliases make it
    clear that this client targets the OpenAI-compatible API surface, not the
    Azure OpenAI client used by the legacy agent modules.
    """
    api_key = _first_env_value(
        "LLM_API_KEY",
        "OPENAI_COMPAT_API_KEY",
        "OPENAI_COMPATIBLE_API_KEY",
        "GROQ_API_KEY",
    )
    base_url = _first_env_value(
        "LLM_BASE_URL",
        "OPENAI_COMPAT_BASE_URL",
        "OPENAI_COMPATIBLE_BASE_URL",
        "GROQ_BASE_URL",
        default=DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    ).rstrip("/")
    return api_key, base_url


def get_openai_compatible_transport_config() -> dict[str, object]:
    return {
        "timeout": _env_float("LLM_TIMEOUT_SECONDS", 30.0),
        "max_retries": _env_int("LLM_SDK_MAX_RETRIES", 2),
        "trust_env": _env_bool("LLM_TRUST_ENV", True),
    }


def describe_openai_compatible_config(model: str | None = None) -> str:
    transport = get_openai_compatible_transport_config()
    return (
        f"base_url={LLM_BASE_URL} "
        f"model={model or os.getenv('LLM_MODEL') or '(unset)'} "
        f"api_key_configured={bool(LLM_API_KEY)} "
        f"timeout={transport['timeout']} "
        f"max_retries={transport['max_retries']} "
        f"trust_env={transport['trust_env']}"
    )


def _client_kwargs(async_client: bool = False) -> dict[str, object]:
    transport = get_openai_compatible_transport_config()
    kwargs: dict[str, object] = {
        "base_url": LLM_BASE_URL,
        "api_key": LLM_API_KEY,
        "max_retries": transport["max_retries"],
    }
    timeout = transport["timeout"]
    if transport["trust_env"]:
        kwargs["timeout"] = timeout
    elif async_client:
        kwargs["http_client"] = httpx.AsyncClient(timeout=timeout, trust_env=False)
    else:
        kwargs["http_client"] = httpx.Client(timeout=timeout, trust_env=False)
    return kwargs


LLM_API_KEY, LLM_BASE_URL = get_openai_compatible_config()

def create_sync_client():
    client = OpenAI(**_client_kwargs(async_client=False))
    return client

def create_sync_azure_client():
    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=AZURE_API_VERSION,
    )
    return client

def create_async_client():
    client = AsyncOpenAI(**_client_kwargs(async_client=True))
    return client

def create_async_azure_client():
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=AZURE_API_VERSION,
    )
    return client
