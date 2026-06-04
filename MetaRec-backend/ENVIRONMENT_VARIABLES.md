# Environment variables

- for LangGraph runtime checkpointing
    - `DATABASE_URL`: PostgreSQL connection string, for example `postgresql://metarec:metarec@localhost:5432/metarec?sslmode=disable`
    - `METAREC_CHECKPOINTER_BACKEND`: defaults to `postgres`; use `memory` only for tests
    - `LANGGRAPH_STRICT_MSGPACK`: set to `true` in Compose and CI

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
    - optional network knobs:
      - `LLM_TIMEOUT_SECONDS` (default `30`)
      - `LLM_SDK_MAX_RETRIES` (default `2`, OpenAI SDK network retries)
      - `LLM_TRUST_ENV` (default `true`; set `false` to ignore proxy-related environment variables)
      - `LLM_TEXT_MAX_TOKENS` (default `1024`, used for non-JSON confirmation/guidance messages)
    - example for another OpenAI-style provider:
      ```powershell
      $env:LLM_BASE_URL="https://your-provider.example.com/openai/v1"
      $env:LLM_API_KEY="your_provider_key"
      $env:LLM_MODEL="your_provider_model"
      $env:LLM_TRUST_ENV="false"
      ```
    - `AGENT_PLANNING_MODEL` fallback when Azure OpenAI client cannot be created
    - `AGENT_SUMMARY_MODEL` fallback when Azure OpenAI client cannot be created
    
- for serpapi api (used in `agent/agent_mcp/`)
    - `SERPAPI_KEY`

- for xiaohongshu (used in `agent/agent_mcp/agent_xiaohongshu.py`)
    - `TIKHUB_API_KEY`
    - `API_302_KEY`

- for authentication / roles (used in `main.py`, `business_repositories.py`)
    - `METAREC_SESSION_COOKIE_NAME` (default `metarec_session`) — app session cookie
    - `METAREC_SESSION_COOKIE_SECURE` (default `false`) — set `true` behind HTTPS
    - `METAREC_SESSION_MAX_AGE_SECONDS` (default 30 days)
    - `METAREC_ADMIN_EMAILS` — comma-separated emails promoted to the `admin` role on
      startup (idempotent; the user must have registered first). Example:
      `METAREC_ADMIN_EMAILS="alice@example.com,bob@example.com"`

- for the debug arena (used in `internal/debug/router.py`)
    - `DEBUG_UI_ENABLED` (default `false`) — master kill-switch for the `/internal/debug` API
    - Access now requires an authenticated user with the **`admin`** role (the former
      `DEBUG_ADMIN_TOKEN` / `DEBUG_ADMIN_TOKEN_HASH` / `DEBUG_SESSION_*` shared-token auth has
      been removed). Bootstrap an admin in one of these ways:
        1. Fresh account (create + promote, idempotent):
           `python scripts/seed_admin_user.py admin@metarec.local Admin12345!`
           (or set `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`; defaults to those values).
           In Docker: `docker compose exec backend python scripts/seed_admin_user.py`.
        2. Promote an already-registered user: `METAREC_ADMIN_EMAILS` allowlist
           (auto-promote on startup), or `python scripts/seed_admin.py admin@example.com`.
        3. direct DB: `UPDATE users SET role='admin' WHERE email='admin@example.com';`
    - `DEBUG_LLM_EXPLAIN_ENABLED` (default `true`)
    - rate-limit knobs: `DEBUG_LLM_GEN_RATE_LIMIT_COUNT` / `_WINDOW_SECONDS`,
      `DEBUG_LLM_EXPLAIN_RATE_LIMIT_COUNT` / `_WINDOW_SECONDS`, `DEBUG_EXEC_TIMEOUT_SECONDS`
