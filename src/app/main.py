from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, buses, chat, flights, health, hotels
from app.core.config import get_settings
from app.core.exception_handlers import (
    app_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import AppError

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

# allow_credentials=True is required for the auth cookie to be sent/received
# cross-origin (e.g. a React dev server on a different port) -- which is also why
# allow_origins can't be "*" here, browsers reject that combination outright.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
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
