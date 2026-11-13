"""Cogniflow API entry point.  Run from the backend/ folder:  uvicorn app.main:app --reload"""
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.routers import (
    activities, assistant, auth, dashboard, documents, expenses, notes, notifications, reminders, search, suggestions, tasks,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cogniflow")

settings = get_settings()
app = FastAPI(title="Cogniflow API", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # tokens travel in the Authorization header, not cookies
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Field-level messages WITHOUT echoing submitted values (FastAPI's default response would echo passwords)."""
    errors = [
        {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "Invalid input.", "errors": errors})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Log details on the server; never send stack traces or internals to the client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/health/db", tags=["system"])
def health_db(db: Session = Depends(get_db)):
    """Runs SELECT 1 on the configured database and reports which database type is in use (no credentials shown)."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "detail": "Database connection failed."})
    return {"status": "ok", "database": db.get_bind().dialect.name}


app.include_router(auth.router)
app.include_router(activities.router)
app.include_router(tasks.router)
app.include_router(notes.router)
app.include_router(expenses.router)
app.include_router(documents.router)
app.include_router(suggestions.router)
app.include_router(reminders.router)
app.include_router(notifications.router)
app.include_router(search.router)
app.include_router(dashboard.router)
app.include_router(assistant.router)
app.include_router(assistant.status_router)
