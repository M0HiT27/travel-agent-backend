from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.routes import auth, flights, health
from app.core.config import get_settings
from app.core.exception_handlers import (
    app_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import AppError

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(flights.router)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
