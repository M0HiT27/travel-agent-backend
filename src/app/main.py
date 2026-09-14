import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.ai.checkpointer import open_checkpointer
from app.ai.graph import build_agent
from app.api.routes import auth, buses, chat, flights, health, hotels
from app.core.config import get_settings
from app.core.exception_handlers import (
    app_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import AppError

if sys.platform == "win32":
    # psycopg's async pool refuses to run on Windows' default ProactorEventLoop, and the
    # agent's conversation memory is an async Postgres connection.
    #
    # This covers entry points that create their own loop after importing the app (a
    # script calling asyncio.run, for example). It does NOT reach uvicorn, which builds
    # its loop before importing us — uvicorn picks SelectorEventLoop itself whenever it
    # runs the app in a subprocess, which is why --reload (or --workers) is required on
    # Windows. Plain `uvicorn app.main:app` with neither will fail to start here.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # The agent's conversation memory needs a database connection open for the life of
    # the app, so it is built here once rather than per request.
    async with open_checkpointer(settings) as checkpointer:
        app.state.agent = build_agent(settings, checkpointer)
        yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

# Lets a browser frontend on another origin call this API. allow_credentials is required
# because auth is a cookie: without it the browser sends the request but strips the
# cookie, and every call comes back 401. That also rules out allow_origins=["*"] —
# browsers reject a wildcard when credentials are involved, so origins are listed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(flights.router)
app.include_router(hotels.router)
app.include_router(buses.router)
app.include_router(chat.router)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
