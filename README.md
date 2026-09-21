# travel-agent

FastAPI backend with SQLAlchemy + Alembic, backed by PostgreSQL (run locally).

## Stack

- FastAPI (Starlette under the hood) + Uvicorn
- SQLAlchemy 2.0 (`psycopg` v3 driver)
- Alembic for migrations
- Pydantic Settings for config (`.env`)
- PyJWT + bcrypt for cookie-based auth
- LangGraph + LangChain for the chatbot, model-agnostic (Gemini or Groq today)
- pgvector for RAG (policy Q&A)

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
  services/bus_service.py                  # parse.bot bus search: resolve -> build -> call -> map
  services/_parsebot.py                     # shared parse.bot HTTP client (hotels + buses)
  services/chat_service.py                   # loads history, runs the agent, persists the turn, streams SSE
  llm/factory.py                               # get_chat_model(settings) -> BaseChatModel (gemini | groq)
  llm/embeddings.py                             # get_embeddings(settings) -- Gemini only, Groq has none
  vectorstores/pgvector_store.py                 # add_chunks / search over document_chunks, scoped by domain
  ingestion/pdf_loader.py                          # CLI: chunk + embed + store a policy PDF for one domain
  tools/bus_search_tool.py                          # LangChain tool wrapping bus_service.search_buses
  tools/bus_policy_tool.py                           # LangChain tool: pgvector search pinned to domain="bus"
  graphs/travel_chat.py                               # builds the LangGraph agent from the current tool list
  repositories/conversation_repository.py               # conversation CRUD, scoped to the owning user
  repositories/message_repository.py                     # message history for a conversation
alembic/                                  # migrations (env.py wired to Settings + Base.metadata)
tests/                                     # pytest suite (no network, API key or live DB required)
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

The chat feature's RAG needs the [pgvector](https://github.com/pgvector/pgvector)
extension installed on that Postgres server (`CREATE EXTENSION` is run for you by
the migration below, but the extension binary itself has to already be available --
e.g. `apt install postgresql-16-pgvector`, `brew install pgvector`, or use a Postgres
image that bundles it).

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

### Chat

- `POST /chat/` — `{conversation_id?, message}` → streams the assistant's reply as Server-Sent Events (`event: token`/`tool_start`/`tool_end`/`done`/`error`). Omit `conversation_id` to start a new conversation; the first event is always `event: conversation` with its id. Requires the auth cookie.

```bash
curl -N -X POST http://127.0.0.1:8000/chat/ \
  -H 'Content-Type: application/json' \
  -b 'access_token=<your cookie>' \
  -d '{"message": "buses from Mumbai to Pune tomorrow"}'
```

The agent is a LangGraph tool-calling loop (`graphs/travel_chat.py`) bound to two
tools right now: `search_buses` (wraps `bus_service.search_buses` directly -- no
HTTP round-trip back into this API) and `search_bus_policy` (RAG over the ingested
bus policy PDF, via pgvector). **Model-agnostic by design**: everything downstream of
`llm/factory.get_chat_model()` only ever sees LangChain's `BaseChatModel` interface,
never `ChatGoogleGenerativeAI`/`ChatGroq` directly -- switching is `LLM_PROVIDER=gemini`
or `LLM_PROVIDER=groq` in `.env`, nothing else changes. Embeddings are always Gemini
regardless of that setting, since Groq has no embeddings endpoint.

**Adding your own domain** (e.g. hotel or flight policy/search) means: write your own
`tools/<domain>_search_tool.py` / `tools/<domain>_policy_tool.py` following the bus
ones, ingest your own PDF tagged with your own `--domain`, and append your two tools
to the list in `graphs/travel_chat.py`. Everything else -- the route, `chat_service`,
conversation/message persistence, the LLM factory -- is shared and untouched.

**RAG setup** (one-time, per environment):
```bash
# pgvector extension must be installed on your Postgres before running migrations
uv run alembic upgrade head
uv run python -m app.ingestion.pdf_loader --domain bus --file policy_docs/bus_policy.pdf
```
`policy_docs/bus_policy.pdf` is a placeholder fictional policy (cancellations,
refunds, luggage, boarding, etc.) for exercising the pipeline end to end -- swap it
for a real one whenever you have it, under the same `--domain bus`.

> On Windows, if `fastapi dev` crashes with a `UnicodeEncodeError` from an emoji in its startup banner, set `PYTHONUTF8=1` in your environment (PowerShell: `$env:PYTHONUTF8 = "1"`).

## Tests

```bash
uv run pytest
```

No network, API key, or live Postgres is needed. Route tests stub out the service
layer (`search_flights`, `search_hotels`, `search_buses`, `stream_chat`); mapping
functions are tested against recorded/real response payloads; chat's repositories
and `resolve_conversation` run against an in-memory SQLite database (the
Postgres-only `document_chunks` table is excluded there and covered separately by
stubbing the vector store in `test_bus_policy_tool.py`).

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
