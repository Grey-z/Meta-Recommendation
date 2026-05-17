# Environment variables

- for Azure OpenAI client (used in `agent/`)
    - `OPENAI_API_KEY`:
    - `AZURE_OPENAI_ENDPOINT`
    - `AZURE_OPENAI_API_VERSION`
    - `AZURE_AGENT_PLANNING_MODEL` 
    - `AZURE_AGENT_SUMMARY_MODEL` 
    
- for OpenAI-compatible LLM client (used in `client.py` / `llm_service.py`)
    - `LLM_BASE_URL` (canonical; defaults to `https://api.groq.com/openai/v1`)
    - `LLM_API_KEY` (canonical; falls back to `GROQ_API_KEY`)
    - `LLM_MODEL` (model name)
    - supported aliases for base URL: `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPATIBLE_BASE_URL`, `GROQ_BASE_URL`
    - supported aliases for API key: `OPENAI_COMPAT_API_KEY`, `OPENAI_COMPATIBLE_API_KEY`, `GROQ_API_KEY`
    - example for another OpenAI-style provider:
      ```powershell
      $env:LLM_BASE_URL="https://your-provider.example.com/openai/v1"
      $env:LLM_API_KEY="your_provider_key"
      $env:LLM_MODEL="your_provider_model"
      ```
    - `AGENT_PLANNING_MODEL` fallback when Azure OpenAI client cannot be created
    - `AGENT_SUMMARY_MODEL` fallback when Azure OpenAI client cannot be created
    
- for serpapi api (used in `agent/agent_mcp/`)
    - `SERPAPI_KEY`

- for xiaohongshu (used in `agent/agent_mcp/agent_xiaohongshu.py`)
    - `TIKHUB_API_KEY`
    - `API_302_KEY`
