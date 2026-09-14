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
  api/routes/                           # API routers (health, auth, flights, hotels, buses)
  services/flight_service.py             # Duffel flight search: build -> call -> map
  services/hotel_service.py               # parse.bot hotel search: resolve -> build -> call -> map
  ai/vector_store.py                       # Gemini embeddings + pgvector store
  ai/tools.py                               # the tools the agent may call
  ai/graph.py                                # the LangGraph agent
data/policies/                                # PDFs to ingest
scripts/ingest_documents.py                    # one-off: PDFs -> chunks -> embeddings -> DB
  services/bus_service.py                  # parse.bot bus search: resolve -> build -> call -> map
  services/_parsebot.py                     # shared parse.bot HTTP client (hotels + buses)
alembic/                                  # migrations (env.py wired to Settings + Base.metadata)
tests/                                     # pytest suite (no network or DB required)
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

> **On Windows, `--reload` is not optional.** The agent's conversation memory uses an
> async Postgres connection, and psycopg refuses to run on Windows' default
> `ProactorEventLoop`. Uvicorn only selects the compatible `SelectorEventLoop` when it
> runs the app in a subprocess — which `--reload` (or `--workers`) does. Plain
> `uvicorn app.main:app` with neither will fail at startup with a `PoolTimeout`.
> Not an issue on Linux or macOS.

- `GET /health` — liveness check
- `GET /health/db` — checks DB connectivity
- `GET /docs` — Swagger UI

### Auth

- `POST /auth/register` — `{name, email, password}` → creates a user with the `user` role, sets the auth cookie, returns the user
- `POST /auth/login` — `{email, password}` → sets the auth cookie, returns the user
- `POST /auth/logout` — clears the auth cookie
- `GET /auth/me` — returns the current user (requires the auth cookie)

The JWT is signed server-side and set as an `httponly` cookie (`COOKIE_NAME` in `.env`) — it's never exposed to client-side JS. Errors are returned as consistent JSON (`{"detail": "..."}`); unhandled server errors are logged but never leak internals to the client.

### Flights

- `POST /flights/search` — `{origin, destination, departure_date, adults?}` → offers sorted cheapest first. Requires the auth cookie, since every search costs money against the Duffel account.

```bash
curl -X POST http://127.0.0.1:8000/flights/search \
  -H 'Content-Type: application/json' \
  -b 'access_token=<your cookie>' \
  -d '{"origin": "DEL", "destination": "GOI", "departure_date": "2026-09-15"}'
```

Origin and destination are 3-letter IATA codes (case-insensitive); past dates and identical
origin/destination are rejected before Duffel is called. `total_amount` serialises as a JSON
**string** because it is a `Decimal` — money must not round-trip through a float.

Set `DUFFEL_API_KEY` in `.env` (use a `duffel_test_` key while developing — live keys book
real flights). Duffel failures surface as `502`, timeouts as `504`; the API key and the raw
upstream response are never logged or returned to the client.

Search lives in `services/flight_service.py` as a plain `search_flights(settings, request)`
function, so it can be called directly from a future LangGraph/LangChain tool rather than
through an HTTP round-trip back into this API. It reads in three steps: build the request
body, call Duffel, map the response.

### Hotels

- `POST /hotels/search` — `{destination, start_date, end_date, rooms?, adults?}` → up to 20 hotels in the source's recommended order. Requires the auth cookie, since every search costs money against the parse.bot account.

```bash
curl -X POST http://127.0.0.1:8000/hotels/search \
  -H 'Content-Type: application/json' \
  -b 'access_token=<your cookie>' \
  -d '{"destination": "Paris", "start_date": "2026-10-15", "end_date": "2026-10-18"}'
```

The client sends a destination **name**, not a region id — resolving the name is the
API's job. Because "Paris" also matches Paris, Texas, the response echoes back the
`destination` and `region_id` it actually used, so a wrong guess is visible rather than
silent. Resolution prefers a `CITY` suggestion over the neighbourhoods, airports and
landmarks that autocomplete also returns, and is cached in-process so repeat searches
for the same place cost one upstream call instead of two.

Check-in cannot be in the past, check-out must be after check-in, and stays are capped
at 30 nights — all rejected as `422` before parse.bot is called. Prices serialise as
JSON **strings** (`"1661"`) because they are `Decimal`s, and are nullable: the scraper
returns display text like `"$1,661 total"`, and a listing whose price will not parse is
still returned with its name, rating and booking link. Currency comes from the booking
URL rather than the `$`, which could be USD, CAD or AUD.

Set `PARSEBOT_API_KEY` in `.env`. Upstream failures surface as `502` and timeouts as
`504`; a destination that cannot be resolved is a `404`. The API key and the raw
upstream response are never logged or returned to the client.

Like flights, search lives in `services/hotel_service.py` as a plain
`search_hotels(settings, request)` function, callable directly from a future
LangGraph/LangChain tool. It reads in four steps: resolve the destination, build the
query, call parse.bot, map the response.

### Buses

- `POST /buses/search` — `{origin, destination, departure_date}` → buses in the source's own order. Requires the auth cookie, since every search costs money against the parse.bot account.

```bash
curl -X POST http://127.0.0.1:8000/buses/search \
  -H 'Content-Type: application/json' \
  -b 'access_token=<your cookie>' \
  -d '{"origin": "Mumbai", "destination": "Pune", "departure_date": "2026-09-15"}'
```

Same shape as hotels: the client sends city **names**, not the numeric ids the
redbus scraper expects, and resolving them is the API's job. The response echoes
back the resolved name and id for each city, so a wrong guess (there's more than one
"Springfield") is visible rather than silent. `fare` is a `Decimal` and serialises as
a JSON **string**; it is the lowest fare across seat classes when the source lists
more than one. `departure_time`/`arrival_time` are naive local datetimes (redBus does
not send a timezone, so none is invented). Past dates and identical
origin/destination are rejected as `422` before parse.bot is called.

Set `PARSEBOT_REDBUS_SCRAPER_ID` and `PARSEBOT_API_KEY` in `.env` (the same key used
for hotels; buses is a separate scraper on the same account). Upstream failures
surface as `502` and timeouts as `504`; a city that cannot be resolved is a `404`.

Search lives in `services/bus_service.py`, structured exactly like
`hotel_service.py` (`resolve -> build -> call -> map`), and shares its parse.bot HTTP
plumbing via `services/_parsebot.py` rather than duplicating it a second time. Field
names in `_map_bus`/`_pick_city` are verified against a real recorded response, like
flights and hotels (`test_bus_service.py`'s payloads are trimmed copies of it) —
notably, both `get_city_suggestions` and `search_buses` wrap their payload in a `data`
envelope, and `ID`/`routeId`/`operatorId` arrive as integers, not strings.

### Assistant (RAG + agent)

- `POST /chat/ask` — `{question, conversation_id?}` → `{answer, conversation_id}`. Requires the auth cookie.

```bash
# First message: omit conversation_id, and keep the one you get back.
curl -X POST http://127.0.0.1:8000/chat/ask \
  -H 'Content-Type: application/json' -b 'access_token=<your cookie>' \
  -d '{"question": "If I cancel 30 hours before departure, what fee do I pay?"}'
# → {"answer": "20% of the ticket fare...", "conversation_id": "e4c5e7f0-..."}

# Follow-up: send that id back, and context carries over.
curl -X POST http://127.0.0.1:8000/chat/ask \
  -H 'Content-Type: application/json' -b 'access_token=<your cookie>' \
  -d '{"question": "And what about 20 hours?", "conversation_id": "e4c5e7f0-..."}'
# → {"answer": "50% of the ticket fare...", ...}
```

**Conversation memory.** History is stored in Postgres by LangGraph's checkpointer, so it
survives restarts. Omit `conversation_id` to start fresh; send it back to continue.
Separate ids never see each other's messages.

To keep a long chat from getting steadily more expensive, `ai/history.py` trims what is
sent to the model: the last few turns are kept, but bulky tool results (retrieved policy
chunks, flight listings) are carried only for the newest turn — stale chunks cannot help
answer the next question. **Trimming affects what is sent, not what is stored**, so the
full conversation is still in the database for a UI to display.

A LangGraph agent (Gemini) picks its own tool per question — there is no routing
`if/else` in the codebase:

- `search_travel_policies` — semantic search over the ingested PDFs (RAG)
- `search_flight_offers` — calls `search_flights()` directly, no HTTP round-trip

Ask *"flights from Delhi to Goa on 2026-09-28"* and it converts the city names to IATA
codes and searches. Ask about cancellation fees and it quotes the policy. Ask about
something the documents do not cover and it says so rather than inventing an answer.

**Loading documents.** Put PDFs in `data/policies/`, then:

```bash
uv run python scripts/ingest_documents.py
```

This reads each page, splits it into overlapping ~1000-character chunks, embeds them
with Gemini and stores them in pgvector. Re-running **replaces** the collection, so it
is safe to run again after editing a PDF or adding another. `PGVector` creates the
`vector` extension and its own tables on first use — those tables are deliberately not
managed by Alembic.

Embeddings are 1536-dimensional rather than the model's native 3072: pgvector's HNSW and
IVFFlat indexes only support up to 2000 dimensions. **Changing the embedding model or
dimension means re-running the ingest script** — old vectors become meaningless.

Set `GEMINI_API_KEY` in `.env` (free from Google AI Studio). Free-tier quotas are counted
**per model**, so a persistent `429` is often fixed by pointing `GEMINI_CHAT_MODEL` at a
different one. Rate limits surface as `429` with a retry message; other agent failures as
`502`. Note `gemini-2.5-flash` is closed to new API keys.

> On Windows, if `fastapi dev` crashes with a `UnicodeEncodeError` from an emoji in its startup banner, set `PYTHONUTF8=1` in your environment (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Tests

```bash
uv run pytest
```

No network, API key, or database is needed: route tests stub out `search_flights`, and the
Duffel mapping is tested against a recorded response payload.

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
