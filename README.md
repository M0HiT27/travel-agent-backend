# travel-agent

FastAPI backend with SQLAlchemy + Alembic, backed by PostgreSQL (run locally).

## Stack

- FastAPI (Starlette under the hood) + Uvicorn
- SQLAlchemy 2.0 (`psycopg` v3 driver)
- Alembic for migrations
- Pydantic Settings for config (`.env`)
- PyJWT + bcrypt for cookie-based auth

## Project layout

```
src/app/
  main.py                    # FastAPI app, exception handlers, routers
  core/config.py               # env-based settings
  core/security.py              # password hashing, JWT create/decode
  core/exceptions.py             # AppError and subclasses (NotFound/Conflict/Unauthorized/Forbidden)
  core/exception_handlers.py      # maps exceptions -> JSON error responses
  db/base.py                       # SQLAlchemy declarative Base
  db/session.py                     # engine, SessionLocal, get_db dependency
  models/                            # SQLAlchemy models (import them in models/__init__.py)
  schemas/                            # Pydantic request/response models
  api/deps.py                          # get_current_user (reads JWT from cookie)
  api/routes/                           # API routers (health, auth)
alembic/                                 # migrations (env.py wired to Settings + Base.metadata)
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

### Auth

- `POST /auth/register` — `{name, email, password}` → creates a user with the `user` role, sets the auth cookie, returns the user
- `POST /auth/login` — `{email, password}` → sets the auth cookie, returns the user
- `POST /auth/logout` — clears the auth cookie
- `GET /auth/me` — returns the current user (requires the auth cookie)

The JWT is signed server-side and set as an `httponly` cookie (`COOKIE_NAME` in `.env`) — it's never exposed to client-side JS. Errors are returned as consistent JSON (`{"detail": "..."}`); unhandled server errors are logged but never leak internals to the client.

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
