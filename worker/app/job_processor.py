import asyncio
import functools
import io
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from PIL import Image

from worker.app.core.docx_generate import images_to_docx_stream
from worker.app.core.pdf_generate import images_to_pdf_stream
from worker.app.core.ppt_generate import images_to_ppt_stream
from worker.app.services.db import get_session
from worker.app.services.db_models import Job, JobFile, User
from worker.app.services.national_id import NationalID
from worker.app.services.pubsub import publish_job_for_retry
from worker.app.services.telegram_files import download_telegram_file
from worker.app.services.telegram_sender import (
    send_document_to_chat,
    send_existing_document_to_chat,
    send_message_to_chat,
)
from worker.app.services.resource_monitor import ResourceMonitor

logger = logging.getLogger(__name__)

# Per-process rembg session
rembg_session = None


def _escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if text is None:
        return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in str(text))


def _update_user_stats(user_id, username, processed_count: int):
    """Increment the processed documents counter for a user in Postgres."""
    if not user_id or processed_count <= 0:
        return

    try:
        from sqlalchemy import select

        with get_session() as session:
            user = (
                session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                .scalars()
                .first()
            )
            if user is None:
                user = User(telegram_id=user_id, username=username or None, role="user")
                session.add(user)
                session.flush()

            user.processed_documents_count = (user.processed_documents_count or 0) + processed_count
            if username and user.username != username:
                user.username = username
            session.commit()
    except Exception as exc:
        logger.error(
            "Failed to update usage stats for user %s by %s documents: %s",
            user_id,
            processed_count,
            exc,
        )


def init_rembg_session():
    """
    Initializes a rembg session in each worker process for CPU mode.
    """
    global rembg_session
    if rembg_session is None:
        from worker.app.config import REMBG_MODEL

        logger.info("Initializing rembg session in worker process (CPU mode)")
        providers = ["CPUExecutionProvider"]
        try:
            from rembg import new_session

            rembg_session = new_session(model_name=REMBG_MODEL, providers=providers)
            logger.info(
                f"rembg session initialized in process: {getattr(rembg_session, 'model_name', 'unknown')}"
            )
        except Exception as e:
            logger.fatal(f"Failed to initialize rembg session in process. Error: {e}")
            rembg_session = None


def _coerce_non_negative_float(value, default) -> float:
    try:
        numeric = float(value)
        return numeric if numeric >= 0.0 else default
    except (TypeError, ValueError):
        return default


def process_single_document(
    pdf_bytes: bytes,
    id_type: str,
    grayscale: bool,
    mirror: bool,
    brightness: float = 1.0,
    saturation: float = 1.0,
    session: Optional[object] = None,
) -> tuple[bytes, str]:
    """
    Processes a single PDF document into PNG bytes.
    """
    global rembg_session
    used_session = session or rembg_session
    if used_session is None:
        raise RuntimeError("rembg session is not available in this worker process.")

    try:
        handler = NationalID(
            document=pdf_bytes,
            id_type=id_type,
            grayscale=grayscale,
            mirror=mirror,
            brightness=_coerce_non_negative_float(brightness, 1.0),
            saturation=_coerce_non_negative_float(saturation, 1.0),
            session=used_session,
        )
        final_image = handler.generate()
        user_name = handler.user.replace(" ", "_") if handler.user else "document"
        with io.BytesIO() as img_buffer:
            final_image.save(img_buffer, format="PNG", optimize=True)
            return img_buffer.getvalue(), user_name
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        traceback.print_exc()
        raise


async def download_and_process_file(
    file_id: str,
    id_type: str,
    grayscale: bool,
    mirror: bool,
    brightness: float,
    saturation: float,
    executor,
    file_semaphore: asyncio.Semaphore,
    resource_monitor: Optional[ResourceMonitor] = None,
    file_name: str | None = None,
):
    """
    Downloads a Telegram file and processes it, respecting concurrency and resource limits.
    """
    try:
        if resource_monitor:
            while not resource_monitor.cpu_ok_event.is_set():
                await asyncio.sleep(0.5)

        pdf_bytes = await download_telegram_file(file_id)
        loop = asyncio.get_event_loop()

        func = functools.partial(
            process_single_document,
            pdf_bytes=pdf_bytes,
            id_type=id_type,
            grayscale=grayscale,
            mirror=mirror,
            brightness=brightness,
            saturation=saturation,
        )

        await file_semaphore.acquire()
        try:
            result = await loop.run_in_executor(executor, func)
        finally:
            file_semaphore.release()

        return result
    except Exception as e:
        label = file_name or file_id
        logger.error(f"Task for {label} failed: {e}")
        traceback.print_exc()
        return None


async def process_job(
    job_data: dict,
    executor,
    file_semaphore: asyncio.Semaphore,
    resource_monitor: Optional[ResourceMonitor] = None,
):
    """
    Main job processing function.
    """
    chat_id = job_data.get("chat_id")
    job_id_str = job_data.get("job_id")
    files = job_data.get("files", [])
    user_id = job_data.get("user_id")
    username = job_data.get("username")
    user_full_name = job_data.get("user_full_name") or None

    if not files:
        logger.error(f"Invalid job data: Missing 'files'.")
        if chat_id:
            await send_message_to_chat(chat_id, "An error occurred due to invalid job data.")
        return

    start_time = datetime.now()
    # Mark job as started in Postgres
    if job_id_str:
        try:
            from sqlalchemy import select
            import uuid

            job_uuid = uuid.UUID(job_id_str)
            with get_session() as session:
                job = session.get(Job, job_uuid)
                if job:
                    job.status = "processing"
                    job.started_at = datetime.now(timezone.utc)
                    session.commit()
        except Exception as exc:
            logger.error(f"Failed to mark job {job_id_str} as processing: {exc}")
    logger.info(f"Starting job for chat {chat_id} with {len(files)} files...")

    processed_images = []
    output_stream = io.BytesIO()

    try:
        brightness = _coerce_non_negative_float(job_data.get("brightness", 1.0), 1.0)
        saturation = _coerce_non_negative_float(job_data.get("saturation", 1.0), 1.0)

        tasks = [
            download_and_process_file(
                source["file_id"],
                job_data["id_type"],
                job_data["grayscale"],
                job_data["mirror"],
                brightness,
                saturation,
                executor,
                file_semaphore,
                resource_monitor,
                file_name=source.get("file_name"),
            )
            for source in files
        ]

        results = await asyncio.gather(*tasks)

        successful_results = []
        for i, res in enumerate(results):
            if res is not None:
                successful_results.append((res, files[i]["file_id"]))

        if not successful_results:
            raise ValueError("All files in the batch failed to process.")

        processed_images = [Image.open(io.BytesIO(res[0][0])) for res in successful_results]
        output_format = job_data.get("output_format", "pdf").lower()

        if output_format == "pdf":
            output_stream = images_to_pdf_stream(processed_images)
        elif output_format == "docx":
            output_stream = images_to_docx_stream(processed_images)
        elif output_format == "pptx":
            output_stream = images_to_ppt_stream(processed_images)
        else:
            output_stream = images_to_pdf_stream(processed_images)
            output_format = "pdf"

        if output_format == "pptx":
            file_extension = "ppt"
        else:
            file_extension = output_format

        file_owner_name = successful_results[0][0][1]

        filename = (
            f"{file_owner_name}_{job_data['id_type'][:3].upper()}_{'CLS' if job_data['grayscale'] else 'CLR'}_{'MIR' if job_data['mirror'] else 'NOR'}.{file_extension}"
            if len(successful_results) == 1
            else f"BATCH_{len(successful_results)}_{job_data['id_type'][:3].upper()}_{'CLS' if job_data['grayscale'] else 'CLR'}_{'MIR' if job_data['mirror'] else 'NOR'}.{file_extension}"
        )

        output_stream.seek(0)
        user_document_file_id = None
        if chat_id:
            user_document_file_id = await send_document_to_chat(
                chat_id,
                output_stream,
                filename,
                "Your files have been processed successfully!",
            )

        if user_id:
            _update_user_stats(user_id, username, len(successful_results))

        # Update job and job_files in Postgres
        if job_id_str:
            try:
                from sqlalchemy import select, update
                import uuid

                job_uuid = uuid.UUID(job_id_str)
                successful_file_ids = {fid for _, fid in successful_results}

                with get_session() as session:
                    job = session.get(Job, job_uuid)
                    if job:
                        job.status = "completed"
                        job.completed_at = datetime.now(timezone.utc)
                        session.commit()

                    # Mark job_files as processed/failed
                    if successful_file_ids:
                        job_files = (
                            session.query(JobFile)
                            .filter(JobFile.job_id == job_uuid)
                            .all()
                        )
                        for jf in job_files:
                            jf.processed_successfully = jf.telegram_file_id in successful_file_ids
                        session.commit()
            except Exception as exc:
                logger.error(f"Failed to update job/job_files for {job_id_str}: {exc}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Finished job for chat {chat_id} successfully in {duration:.2f} seconds.")

    except ValueError as e:
        if "All files in the batch failed to process" in str(e):
            logger.error(f"Job for chat {chat_id} failed because all files failed to process. This might be due to an issue with the processing worker.")
            if chat_id:
                await send_message_to_chat(
                    chat_id, "Processing failed for all documents. This could be due to a temporary issue with the processing service. Please try again in a few moments."
                )
        else:
            logger.error(f"Error processing job for chat {chat_id}: {e}")
            traceback.print_exc()
            if chat_id:
                await send_message_to_chat(
                    chat_id, "An unexpected error occurred. Your request will be retried automatically."
                )
            try:
                if job_id_str:
                    import uuid
                    with get_session() as session:
                        job = session.get(Job, uuid.UUID(job_id_str))
                        if job:
                            job.status = "failed"
                            job.error_message = str(e)
                            job.completed_at = datetime.now(timezone.utc)
                            session.commit()
                await publish_job_for_retry(job_data)
                logger.info(f"Job for chat {chat_id} re-published for retry.")
            except Exception as ex:
                logger.error(f"Failed to re-publish job for chat {chat_id} for retry: {ex}")

    except Exception as e:
        logger.error(f"Error processing job for chat {chat_id}: {e}")
        traceback.print_exc()
        if chat_id:
            await send_message_to_chat(
                chat_id, "An unexpected error occurred. Your request will be retried automatically."
            )
        try:
            if job_id_str:
                import uuid
                with get_session() as session:
                    job = session.get(Job, uuid.UUID(job_id_str))
                    if job:
                        job.status = "failed"
                        job.error_message = str(e)
                        job.completed_at = datetime.now(timezone.utc)
                        session.commit()
            await publish_job_for_retry(job_data)
            logger.info(f"Job for chat {chat_id} re-published for retry.")
        except Exception as ex:
            logger.error(f"Failed to re-publish job for chat {chat_id} for retry: {ex}")
    finally:
        for img in processed_images:
            try:
                img.close()
            except Exception:
                pass
        output_stream.close()
