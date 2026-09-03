# travel-agent

FastAPI backend with SQLAlchemy + Alembic, backed by PostgreSQL (run locally).

## Stack

- FastAPI (Starlette under the hood) + Uvicorn
- SQLAlchemy 2.0 (`psycopg` v3 driver)
- Alembic for migrations
- Pydantic Settings for config (`.env`)

## Project layout

```
src/app/
  main.py              # FastAPI app + entrypoint
  core/config.py        # env-based settings
  db/base.py             # SQLAlchemy declarative Base
  db/session.py          # engine, SessionLocal, get_db dependency
  models/                # SQLAlchemy models (import them in models/__init__.py)
  api/routes/             # API routers
alembic/                  # migrations (env.py wired to Settings + Base.metadata)
```

## Setup

```bash
cp .env.example .env
# edit .env with your local Postgres credentials
```

Create the database (Postgres must already be running locally):

```bash
createdb travel_agent
```

## Run

```bash
uv run fastapi dev src/app/main.py
```

(`uv run uvicorn app.main:app --reload` also works.)

- `GET /health` — liveness check
- `GET /health/db` — checks DB connectivity
- `GET /docs` — Swagger UI

> On Windows, if `fastapi dev` crashes with a `UnicodeEncodeError` from an emoji in its startup banner, set `PYTHONUTF8=1` in your environment (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Migrations

```bash
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
```

## Dependencies

Managed via `uv` (`pyproject.toml` / `uv.lock`). `requirements.txt` is exported for tooling that needs it:

```bash
uv export --no-hashes --no-dev --no-emit-project -o requirements.txt
```
