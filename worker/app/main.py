import asyncio
import logging
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from worker.app.job_processor import (
    init_rembg_session as init_worker_rembg_session,
    process_job as process_job_fn,
)
from worker.app.webhooks.jobs import router as jobs_router
from worker.app.services.resource_monitor import ResourceMonitor

from worker.app.console import setup_logging
from worker.app.services.db_models import init_db

# Setup logging and database
setup_logging()
init_db()
logger = logging.getLogger(__name__)

_SPAWN_CONTEXT = multiprocessing.get_context("spawn")


def get_max_workers() -> int:
    """Determines the number of worker processes for CPU-only execution.

    We keep the maximum number of worker processes strictly below the
    total number of CPU cores so that at least one core remains free
    for the event loop and other system work.
    """
    cpu_count = os.cpu_count() or 4
    # Use at most (CPU - 1) workers, but never less than 1.
    return max(1, cpu_count - 1)


async def run_job_processor(
    queue: asyncio.Queue,
    file_semaphore: asyncio.Semaphore,
    resource_monitor: Optional[ResourceMonitor],
):
    """Main loop for dequeuing and processing jobs.

    Processes a single job at a time, while allowing concurrent
    processing of that job's files via the per-job process pool and
    the shared file_semaphore.
    """

    logger.info("Job processor started")
    while True:
        job_data = await queue.get()

        if job_data is None:
            logger.info("Shutdown signal received")
            queue.task_done()
            break

        job_id = job_data.get("job_id", "N/A")

        # Single-job processing: handle one job at a time, but allow
        # concurrent processing of that job's files via the process
        # pool and file_semaphore in the job processor.
        max_workers = get_max_workers()
        file_count = len(job_data.get("files", [])) or 1
        workers_for_job = max(1, min(max_workers, file_count))

        executor = ProcessPoolExecutor(
            max_workers=workers_for_job,
            initializer=init_worker_rembg_session,
            mp_context=_SPAWN_CONTEXT,
        )

        try:
            await process_job_fn(
                job_data,
                executor,
                file_semaphore,
                resource_monitor,
            )
        except asyncio.CancelledError:
            logger.warning(f"Job task cancelled for {job_id}")
        except Exception as exc:
            logger.error(f"Job {job_id} failed with unexpected exception: {exc}")
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        # Mark this job as processed in the queue.
        queue.task_done()

    logger.info("Exiting run_job_processor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    """
    logger.info("Worker starting...")

    app.state.job_queue = asyncio.Queue()

    # We process one job at a time, but within a job we allow
    # concurrent file processing up to a CPU-based limit.
    file_concurrency = get_max_workers()

    app.state.file_semaphore = asyncio.Semaphore(file_concurrency)

    resource_monitor = ResourceMonitor()
    await resource_monitor.start()
    app.state.resource_monitor = resource_monitor

    processor_task = asyncio.create_task(
        run_job_processor(
            app.state.job_queue,
            app.state.file_semaphore,
            app.state.resource_monitor,
        )
    )

    yield

    logger.info("Shutdown initiated")
    await app.state.job_queue.put(None)
    await processor_task

    try:
        await resource_monitor.stop()
    except Exception as ex:
        logger.error(f"Failed to stop resource monitor cleanly: {ex}")
    logger.info("Shutdown complete")


app = FastAPI(
    title="Document Processing Worker",
    description="A worker to process document jobs from a Pub/Sub push subscription.",
    lifespan=lifespan,
)
app.include_router(jobs_router, prefix="/api/jobs", tags=["Job Processing"])


@app.get("/")
def read_root():
    return {"status": "Worker is running"}
