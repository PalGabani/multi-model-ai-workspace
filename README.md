# Modelspace

Modelspace is a multi-tenant AI workspace for chatting with different language models, comparing answers side by side, and tracking usage from one interface.

## Features

- Email/password sign-in and registration; each new account starts with its own workspace.
- Persistent conversations with model selection, streaming, retry, stop, rename, delete, search, and export.
- Side-by-side comparison with concurrent streamed responses.
- OpenAI-compatible provider adapters, task-aware model routing, and workspace model allowlists.
- Response feedback and request, token, estimated cost, and latency reporting.
- PostgreSQL persistence, Redis-backed authentication rate limiting, and Alembic migrations.
- Responsive Next.js interface with TanStack Query and shadcn/ui components.

## Architecture

```text
Browser: Next.js / React / TypeScript
    |
    +-- /api rewrite --> FastAPI
                          +-- authentication and workspace authorization
                          +-- model routing and provider adapters
                          +-- Server-Sent Events (SSE)
                          +-- PostgreSQL via SQLAlchemy and Alembic
                          +-- Redis for authentication rate limits
```

Provider credentials are configured on the backend and are not sent to the browser.

## Quick start with Docker Compose

Requirements: Docker Compose v2. A provider API key is needed to receive successful model responses.

1. Create the local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env`. Set a private `POSTGRES_PASSWORD` and a random `JWT_SECRET` of at least 32 characters. To generate a suitable JWT secret with Node.js:

   ```powershell
   node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"
   ```

   Add your `OPENAI_API_KEY` or configure another OpenAI-compatible provider as described below.

3. Build and start the application:

   ```powershell
   docker compose up --build
   ```

4. Open the application at [http://localhost:3000](http://localhost:3000). The API and interactive API documentation are at [http://localhost:8000/api/health](http://localhost:8000/api/health) and [http://localhost:8000/docs](http://localhost:8000/docs).

Compose starts PostgreSQL and Redis, applies database migrations before the API starts, and then starts the web app. Use `docker compose down` to stop the services. Persistent database data remains in the Compose volumes.

## Local development

Requirements: Node.js 20+, Python 3.11+, PostgreSQL, and Redis.

1. Install frontend dependencies and make a local environment file:

   ```powershell
   npm ci
   Copy-Item .env.example .env
   ```

2. Configure `.env` for the local database and Redis. The example uses PostgreSQL on port `5433` and Redis on port `6380`; change the URLs if your services use different ports. Set a private `JWT_SECRET`.

3. Set up the Python environment:

   ```powershell
   py -3.11 -m venv backend\.venv
   backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

4. Apply migrations:

   ```powershell
   npm run db:upgrade
   ```

5. In separate terminals, start the API and frontend:

   ```powershell
   npm run dev:api
   ```

   ```powershell
   npm run dev
   ```

   Visit [http://localhost:3000](http://localhost:3000).

The provided npm scripts use Windows virtual-environment paths. On other platforms, create/activate a Python virtual environment and run the equivalent `python -m alembic -c backend/alembic.ini upgrade head` and `uvicorn app.main:app --app-dir backend --reload` commands from the repository root.

## Provider setup

- Set `OPENAI_API_KEY` to use the default OpenAI models.
- Configure additional OpenAI-compatible providers in `PROVIDER_CONFIGS_JSON`. This is a JSON object keyed by provider ID, with `api_key` and `base_url` values. Keep credentials in the backend environment; never use `NEXT_PUBLIC_*` variables for secrets.
- Optionally set `MODEL_CATALOG_JSON` to replace the default model catalog. Each model accepts `id`, `provider`, `label`, optional `description`, `input_cost_per_million`, `output_cost_per_million`, `context_window`, and `enabled`.

Example model catalog:

```json
[
  {
    "id": "gpt-4o-mini",
    "provider": "openai",
    "label": "GPT-4o mini",
    "input_cost_per_million": 0.15,
    "output_cost_per_million": 0.6
  }
]
```

The built-in catalog and prices are examples, not guarantees of current provider availability or pricing. Keep catalog entries and cost estimates in sync with your provider. Comparisons make concurrent requests, so provider rate limits and outages may affect individual responses.

## Checks and tests

Run from the project root:

```powershell
npm run lint
npm run build
npm run lint:python
npm run test:unit
```

Integration tests require a migrated PostgreSQL database and a reachable Redis service:

```powershell
npm run db:upgrade
npm run test:integration
```

Docker Compose configuration can be checked after setting the required environment variables:

```powershell
docker compose config --quiet
```

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- `GET` and `PATCH /api/auth/workspace`
- `GET /api/models`, `POST /api/models/route`
- `GET` and `POST /api/conversations`; conversation detail, history, rename, and delete
- `POST /api/conversations/{id}/messages` for streamed generation
- `POST /api/conversations/compare` for streamed model comparison
- `POST /api/messages/{id}/feedback`
- `GET /api/usage/summary`, `GET /api/usage/by-model`
- `GET /api/health`

FastAPI's interactive documentation is available at `/docs`.

## Security and limitations

- Replace development secrets before deployment and use HTTPS in production.
- Access tokens currently live in browser `sessionStorage`; this is a development-oriented approach, not an HttpOnly-cookie session.
- Workspace budgets are checked before requests and measured after completion. They are not reservation-based hard limits; concurrent generations can exceed a configured budget.
- Cost totals are estimates based on configured catalog pricing and token counts.
- A provider API key is required for successful live generation. Without one, the rest of the workspace can be explored, but model requests return a provider configuration error.
- Registration creates a workspace for its owner. Workspace invitations, billing, and end-user provider credential management are not currently implemented.

## Repository layout

```text
src/                    Next.js application and UI
backend/app/             FastAPI routes, database models, and provider adapters
backend/alembic/         Database migration environment and revisions
backend/tests/           Backend unit and integration tests
.github/workflows/       Continuous integration
docker-compose.yml       Local PostgreSQL, Redis, API, and web services
```
