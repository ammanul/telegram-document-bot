import httpx
from typing import IO, Optional

from worker.app.config import TELEGRAM_TOKEN

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


async def send_document_to_chat(
    chat_id: int,
    file_stream: IO[bytes],
    filename: str,
    caption: str = "",
    parse_mode: Optional[str] = None,
) -> Optional[str]:
    """Uploads and sends a document file to a specific chat.

    Returns the Telegram ``file_id`` of the sent document when available.
    """
    url = f"{API_URL}/sendDocument"
    files = {"document": (filename, file_stream, "application/octet-stream")}
    data: dict = {"chat_id": chat_id, "caption": caption}
    if parse_mode:
        data["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, files=files, data=data)
        response.raise_for_status()

    print(f"[TELEGRAM] Files sent to chat id {chat_id}")

    try:
        payload = response.json()
        document = (payload.get("result") or {}).get("document") or {}
        return document.get("file_id")
    except Exception:
        return None


async def send_existing_document_to_chat(
    chat_id: int,
    document_file_id: str,
    caption: str = "",
    parse_mode: Optional[str] = None,
) -> None:
    """Sends an already-uploaded Telegram document by its ``file_id``."""
    url = f"{API_URL}/sendDocument"
    data: dict = {"chat_id": chat_id, "document": document_file_id, "caption": caption}
    if parse_mode:
        data["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, data=data)
        response.raise_for_status()

    print(f"[TELEGRAM] Existing file {document_file_id} sent to chat id {chat_id}")

async def send_message_to_chat(chat_id: int, text: str):
    """Sends a simple text message to a specific chat."""
    url = f"{API_URL}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data)
        response.raise_for_status()
    print(f"[TELEGRAM] Sent message to chat id {chat_id}: {text}")