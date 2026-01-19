"""Uvicorn entrypoint that exposes the FastAPI worker app."""
from worker.app.main import app

__all__ = ["app"]
