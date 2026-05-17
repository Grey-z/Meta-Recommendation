import os
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


LLM_API_KEY, LLM_BASE_URL = get_openai_compatible_config()

def create_sync_client():
    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
    )
    return client

def create_sync_azure_client():
    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=AZURE_API_VERSION,
    )
    return client

def create_async_client():
    client = AsyncOpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
    )
    return client

def create_async_azure_client():
    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=AZURE_API_VERSION,
    )
    return client
