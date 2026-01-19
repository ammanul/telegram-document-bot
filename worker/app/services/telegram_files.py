"""Utilities for downloading original Telegram files by their file_id."""

import httpx

from worker.app.config import TELEGRAM_TOKEN

API_BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
FILE_BASE_URL = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"


async def download_telegram_file(file_id: str) -> bytes:
    """Fetch the raw bytes for a Telegram file using its ``file_id``."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured; cannot download files from Telegram.")
    if not file_id:
        raise ValueError("file_id is required to download a Telegram file.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        metadata_response = await client.get(f"{API_BASE_URL}/getFile", params={"file_id": file_id})
        metadata_response.raise_for_status()
        payload = metadata_response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Failed to fetch Telegram file metadata: {payload}")

        file_path = (payload.get("result") or {}).get("file_path")
        if not file_path:
            raise RuntimeError("Telegram getFile response did not include a file_path.")

        file_url = f"{FILE_BASE_URL}/{file_path}"
        file_response = await client.get(file_url)
        file_response.raise_for_status()
        return file_response.content
