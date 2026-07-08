---
title: MetaRec Restaurant Recommender
emoji: 🍽️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# MetaRec - Intelligent Restaurant Recommender 🍽️

An intelligent restaurant recommendation system with natural language understanding and interactive confirmation flow.

## ✨ Features

- 🧠 **Natural Language Understanding** - Just describe what you want in plain English
- 💬 **Interactive Confirmation** - AI confirms understanding before recommendations
- 🤔 **Thinking Process Visualization** - See how the AI thinks and decides
- 🔍 **Multi-dimensional Filtering** - Restaurant type, flavor, budget, location, dining purpose
- 🌶️ **Flavor Preference Matching** - Spicy, savory, sweet, sour, mild preferences
- 👤 **User Preference Learning** - Remembers and adapts to your preferences
- 🎯 **Smart Intent Recognition** - Understands confirmations, rejections, and new queries

## 🚀 Quick Start

### Using on Hugging Face Spaces

Simply visit the deployed Space and start asking for restaurant recommendations!

Example queries:
- "I want spicy Sichuan food for dinner"
- "Looking for a romantic restaurant for date night, budget around 100-200 SGD"
- "Best Italian restaurants near Marina Bay"

### Local Development

#### Docker Compose (recommended)
```bash
docker compose up --build
```

This starts:
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- PostgreSQL: `localhost:5432`

The default Compose setup runs in development mode with Vite and Uvicorn reload enabled. LangGraph checkpoints are stored in PostgreSQL through `DATABASE_URL`.

If local port `5432` is already in use, set `POSTGRES_HOST_PORT` before starting Compose, for example `POSTGRES_HOST_PORT=15432 docker compose up --build`.

#### Backend (FastAPI)
```bash
cd MetaRec-backend
pip install -r requirements.txt
set DATABASE_URL=postgresql://metarec:metarec@localhost:5432/metarec?sslmode=disable
python main.py
```

Server runs at `http://localhost:8000` (or port 7860 for HF Spaces)

#### Frontend (React + Vite)
```bash
cd MetaRec-ui
npm install
npm run dev
```

App runs at `http://localhost:5173`

### Docker Deployment

```bash
docker build -t metarec .
docker run -p 7860:7860 metarec
```

## 📁 Project Structure

```
Meta-Recommendation/
├── MetaRec-backend/          # Python FastAPI backend
│   ├── main.py               # FastAPI server with static file serving
│   ├── service.py            # Core recommendation service
│   └── requirements.txt      # Python dependencies
├── MetaRec-ui/               # React frontend
│   ├── src/
│   │   ├── ui/               # React components
│   │   └── utils/            # API utilities
│   └── package.json          # Node dependencies
└── Dockerfile                # Multi-stage build for HF Spaces
```

## 🛠️ Technology Stack

### Backend
- **FastAPI** - Modern Python web framework
- **Pydantic** - Data validation
- **Uvicorn** - ASGI server

### Frontend
- **React** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool

## 🌐 API Endpoints

- `GET /api` - API information
- `GET /health` - Health check
- `POST /api/recommend` - Smart recommendation with intent analysis
- `POST /api/confirm` - Confirm preferences and start task
- `GET /api/status/{task_id}` - Get task status
- `POST /api/update-preferences` - Update user preferences
- `GET /api/user-preferences/{user_id}` - Get user preferences

Full API documentation available at `/docs` (Swagger UI)

## 📝 Example Usage

### Simple Query
```
User: "I want some good restaurants"
AI: Shows thinking process → Displays recommendations
```

### Complex Query with Confirmation
```
User: "I want spicy Sichuan food for friends gathering, budget 50-80 SGD per person"
AI: "Just to confirm, you're looking for Sichuan cuisine, spicy flavor..."
User: "Yes, that's correct"
AI: Shows thinking process → Displays recommendations
```

## 🎯 Deployment on Hugging Face Spaces

Deploys as a single **Docker Space**: the root `Dockerfile` builds the React
frontend to static files, copies them into the backend, and FastAPI serves both the
SPA and the `/api/*` routes on port **7860** (same-origin — no CORS/cookie issues).

Because a Space's filesystem is **ephemeral** (wiped on the 48 h sleep/wake and on
every rebuild), the database must live **outside** the container. The app is
Postgres-only, so use a free managed Postgres (e.g. [Neon](https://neon.tech)).

### Deployment Steps

1. **Create a Postgres database** (Neon free tier) and copy its connection string.
   Use the **plain** `postgresql://USER:PASSWORD@HOST/DB?sslmode=require` form
   (not `postgresql+psycopg://`) — both SQLAlchemy and the LangGraph checkpointer
   accept it.
2. **Create a new Space** → SDK **Docker** → push this repository. HF detects the
   root `Dockerfile` and reads `app_port: 7860` from this README.
3. **Space settings → Secrets** (runtime): set `DATABASE_URL`, `OPENAI_API_KEY`,
   `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `LLM_MODEL`, `SERPAPI_KEY`,
   `SERPAPI_URL`, `TIKHUB_API_KEY`, and `METAREC_SESSION_COOKIE_SECURE=true`.
   Optional: `SEED_ADMIN_EMAIL` + `SEED_ADMIN_PASSWORD` (auto-creates an admin on
   startup), `GROQ_API_KEY`, `API_302_KEY`, `METAREC_ADMIN_EMAILS`, `DEBUG_UI_ENABLED`.
4. **Space settings → Variables** (build-time, public): set
   `VITE_GOOGLE_MAPS_API_KEY` (baked into the frontend at build). Leave
   `VITE_API_BASE_URL` **unset** so the frontend calls the backend same-origin.
5. **Build & run**: on start, the container runs `alembic upgrade head` (idempotent)
   then launches the server. **Admin bootstrap (shell-free):** set `SEED_ADMIN_EMAIL`
   and `SEED_ADMIN_PASSWORD` secrets and the app creates that admin account on startup
   (no register-first, no restart). Alternatively, register a user, add its email to
   `METAREC_ADMIN_EMAILS`, and restart the Space once to promote it. Admin UI:
   `/dashboard`.

The Dockerfile handles building the frontend, installing the backend, running
migrations on startup, serving static files, and listening on port 7860.

## 🔧 Configuration

### Environment Variables

- `PORT` - Server port (default: 7860 for HF Spaces, 8000 for local)
- `DATABASE_URL` - PostgreSQL connection string; **required**. Primary data store for users, conversations, feedback, and LangGraph runtime checkpoints
- `METAREC_CHECKPOINTER_BACKEND` - `postgres` by default; set `memory` only for tests
- `LANGGRAPH_STRICT_MSGPACK` - set to `true` for checkpoint serialization hardening
- `VITE_API_BASE_URL` - Frontend API base URL (optional, auto-detected)
- `VITE_GOOGLE_MAPS_API_KEY` - Google Maps API key (required for map functionality)

#### Google Maps API Key Setup

To enable map functionality, you need to configure a Google Maps API key:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the following APIs:
   - **Maps JavaScript API** - For displaying maps
   - **Geocoding API** - For address to coordinates conversion
   - **Places API** - For restaurant details (ratings, photos, opening hours, etc.)
4. Create credentials (API Key)
5. (Optional but recommended) Restrict the API key to specific APIs and HTTP referrers for security
6. Set the API key in your `.env` file:
   ```
   VITE_GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
   ```

### Local vs Production

The application automatically detects the environment:
- **Development**: Frontend uses `http://localhost:8000` for API, dev dependencies for local testing
- **Production**: Frontend uses relative URLs (same domain as backend)

## 📝 Automated Test Pipeline

Multi-part automated testing pipeline (no Playwright E2E yet, that'll be too heavy for now) v2:

0. API contract check (OpenAPI export + frontend type generation drift check)

1. Frontend unit tests (`*.unit.test.ts`)
2. Frontend rendering tests (`*.test.tsx`)
3. Backend unit tests (marker `backend_unit`; includes the scripted-LLM chain
   coverage — first-attempt success, retry-once, and bounded-fallback paths)
4. Backend runtime contract tests (marker `runtime_contract`; these need
   Postgres — they skip locally without `DATABASE_URL` and run in CI against a
   real Postgres 16 service)

Every backend test must carry one of the two suite markers — collection fails
otherwise (see `tests/conftest.py`), and `--strict-markers` rejects unregistered
marker names.

### Frontend

```bash
cd MetaRec-ui
npm run contract:gen
npm run contract:check
npm run test:unit
npm run test:render
```

Run all frontend tests:

```bash
npm test
```

### Backend

Install dev test dependencies:

```bash
cd MetaRec-backend
python -m pip install -r requirements-dev.txt
```

Export OpenAPI contract (single source of truth):

```bash
python scripts/export_openapi.py
```

Run each backend category:

```bash
python -m pytest -q -m backend_unit
python -m pytest -q -m runtime_contract   # needs DATABASE_URL, skips otherwise
```

Pytest runtime temp files are redirected to:
`MetaRec-backend/__pytest_runtime__/`

Run everything together:

```bash
python -m pytest -q
```

### CI/CD Contract Tips
- Enable auto-generation once per local clone:
  - `git config core.hooksPath .githooks`
  - (macOS/Linux) `chmod +x .githooks/pre-commit`
- Any backend API schema/route change must regenerate contract artifacts:
  - `python MetaRec-backend/scripts/export_openapi.py`
  - `cd MetaRec-ui && npm run contract:gen`
- Run `npm run contract:check` before pushing; this validates generated types still compile.
- CI contract checks are semantic-first (OpenAPI validate + type compile), not strict file-text matching.
- For new frontend API calls, add runtime contract validation in `MetaRec-ui/src/utils/api.ts` via `parseWithContract(...)`.

### GitHub Actions CI

CI workflow file: `.github/workflows/tests.yml`

- `contract_check` (semantic validation: export OpenAPI, validate contract, generate frontend types, ensure type compile)
- `frontend_unit` (runs `npm run test:unit`)
- `frontend_render` (runs `npm run test:render`)
- `backend_unit`
- `backend_runtime_contracts` (Postgres 16 service + `DATABASE_URL`)
- `Deploy Hugging Face Space` runs only on `push` to `main` after all tests above pass.

Each test job emits a JUnit XML report artifact (`*-junit`), and a final `Test Report` job publishes a merged PR test summary from all XML files.

To enable automatic HF Space deployment, configure repository-side values:

- `HF_SPACE_ID`: repository variable or secret, in `user-name/space-name` form.
- `HF_TOKEN`: repository secret with write access to that Space.

The deploy job mirrors the repository to the Docker Space via `huggingface/hub-sync`; the Space rebuild then uses the root `Dockerfile`.

## 📄 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📧 Contact

For questions or feedback, please open an issue on the repository.
