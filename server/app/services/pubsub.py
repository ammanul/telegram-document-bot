"""Job dispatch utilities.

This module now sends jobs directly to the worker service over HTTP
instead of using Google Cloud Pub/Sub.
"""

import asyncio
import json
from typing import Any

import httpx

from server.app.config import WORKER_URL


async def publish_job(job_data: dict[str, Any]) -> None:
    """Send a job to the worker service over HTTP.

    The worker exposes an `/api/jobs/process` endpoint that accepts the
    same ``job_data`` payload previously sent through Pub/Sub.
    """
    if not WORKER_URL:
        raise RuntimeError("WORKER_URL must be configured to dispatch jobs.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{WORKER_URL if WORKER_URL.endswith('/') else WORKER_URL + '/'}api/jobs/process", json=job_data)
        response.raise_for_status()

    print(f"Published job {job_data.get('job_id', 'N/A')} to worker at {WORKER_URL}.")