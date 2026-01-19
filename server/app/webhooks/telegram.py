"""
This module defines the Telegram webhook endpoint for the FastAPI application.
"""
from fastapi import APIRouter, HTTPException, Request
from telegram import Update

from server.app.bot.instance import application
from server.app.config import TELEGRAM_SECRET_TOKEN

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Handles incoming Telegram updates via a webhook.

    This endpoint receives updates from the Telegram Bot API, verifies the
    secret token, and processes the update using the bot application.

    Args:
        request: The incoming FastAPI request.

    Returns:
        A dictionary with a status of "ok" if the update is processed successfully.

    Raises:
        HTTPException: If the secret token is invalid.
    """
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if TELEGRAM_SECRET_TOKEN and secret_token != TELEGRAM_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)

    return {"status": "ok"}