import os
from openai import AsyncAzureOpenAI, AzureOpenAI, AsyncOpenAI, OpenAI
from dotenv import load_dotenv, find_dotenv

# tries to find .env in current path, or traverses parent directories until found
dotenv_path = find_dotenv()

load_dotenv(dotenv_path)

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://agenthiack.openai.azure.com/")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")

def create_sync_client():
    client = OpenAI(
        base_url = LLM_BASE_URL,
        api_key = LLM_API_KEY,
    )
    return client

def create_sync_azure_client():
    client = AzureOpenAI(
        azure_endpoint = AZURE_ENDPOINT,
        api_key = OPENAI_API_KEY,
        api_version = AZURE_API_VERSION,
    )
    return client

def create_async_client():
    client = AsyncOpenAI(
        base_url = LLM_BASE_URL,
        api_key = LLM_API_KEY,
    )
    return client

def create_async_azure_client():
    client = AsyncAzureOpenAI(
        azure_endpoint = AZURE_ENDPOINT,
        api_key = OPENAI_API_KEY,
        api_version = AZURE_API_VERSION,
    )
    return client
