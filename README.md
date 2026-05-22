---
title: MetaRec Restaurant Recommender
emoji: 🍽️
colorFrom: blue
colorTo: green
sdk: docker
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

This project is configured for easy deployment on Hugging Face Spaces using Docker SDK.

### Deployment Steps

1. Create a new Space on Hugging Face
2. Select **Docker** as the SDK
3. Push this repository to the Space
4. HF Spaces will automatically build and deploy

The Dockerfile handles:
- Building the React frontend
- Setting up the Python backend
- Serving static files
- Running on port 7860 (HF Spaces requirement)

## 🔧 Configuration

### Environment Variables

- `PORT` - Server port (default: 7860 for HF Spaces, 8000 for local)
- `DATABASE_URL` - PostgreSQL connection string for LangGraph runtime checkpoints
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

1. Frontend unit tests
2. Frontend rendering tests
3. Backend unit tests
4. Backend chain tests - `standard` (mock LLM returns valid output at first attempt)
5. Backend chain tests - `retrial` (mock LLM fails once, then succeeds)
6. Backend chain tests - `fallback` (mock LLM keeps failing, bounded by high retry cap)

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
python -m pytest -q -m chain_standard
python -m pytest -q -m chain_retrial
python -m pytest -q -m chain_fallback
```

Pytest runtime temp files are redirected to:
`MetaRec-backend/__pytest_runtime__/`

Run all backend categories together:

```bash
python -m pytest -q -m "backend_unit or chain_standard or chain_retrial or chain_fallback"
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
- `frontend_unit`
- `frontend_render`
- `backend_unit`
- `backend_chain_standard`
- `backend_chain_retrial`
- `backend_chain_fallback`

Each test job emits a JUnit XML report artifact (`*-junit`), and a final `Test Report` job publishes a merged PR test summary from all XML files.

## 📄 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📧 Contact

For questions or feedback, please open an issue on the repository.
