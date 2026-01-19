from server.app.console import setup_logging
from server.app.services.db_models import init_db

# Setup logging
setup_logging()
init_db() 

from contextlib import asynccontextmanager
from fastapi import FastAPI

from server.app.config import TELEGRAM_WEBHOOK_URL, TELEGRAM_SECRET_TOKEN
from server.app.bot.instance import application
from server.app.webhooks.telegram import router as telegram_router



# --- FastAPI App ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Asynchronous context manager for the FastAPI application's lifespan.
    Handles startup and shutdown events.
    """
    # On startup
    await application.initialize()
    if TELEGRAM_WEBHOOK_URL:
        await application.bot.set_webhook(
            url=TELEGRAM_WEBHOOK_URL,
            secret_token=TELEGRAM_SECRET_TOKEN,
            drop_pending_updates=True,
        )
    await application.start()
    yield
    # On shutdown
    await application.stop()
    await application.shutdown()

app = FastAPI(title="Document Processing Bot Server", lifespan=lifespan)
app.include_router(telegram_router, prefix="/api/telegram", tags=["Telegram"])

@app.get("/")
def read_root():
    """
    Root endpoint for the server.
    Returns a status message indicating that the server is running.
    """
    return {"status": "Server is running"}