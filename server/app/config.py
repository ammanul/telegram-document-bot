"""
This module loads the application's configuration from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
"""The token for the Telegram bot."""

TELEGRAM_SECRET_TOKEN = os.getenv("TELEGRAM_SECRET_TOKEN")
"""The secret token for the Telegram webhook."""
 
TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")
"""The URL for the Telegram webhook."""

TELEGRAM_ADMIN_SECRET = os.getenv("TELEGRAM_ADMIN_SECRET")
"""The secret password for setting the first admin."""

TELEGRAM_OWNER_SECRET = os.getenv("TELEGRAM_OWNER_SECRET")
"""The secret password for setting the owner."""

MAX_FILES = int(os.getenv("MAX_FILES", "30"))

# --- Application ---
ID_TYPES = ["new", "old", "updated","T1", "T2", "T3", "T4"]
"""The supported types of national ID cards."""

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL")
"""SQLAlchemy-compatible Postgres connection string (e.g. postgresql+psycopg2://user:pass@host:5432/db)."""


# --- Worker ---
WORKER_URL = os.getenv("WORKER_URL")
"""URL of the worker's job processing endpoint used for dispatching jobs."""