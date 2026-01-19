import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()


@router.post("/process", status_code=status.HTTP_202_ACCEPTED)
async def process_job_webhook(request: Request, job_data: dict[str, Any]):
    """Accept a job payload directly and enqueue it for processing.

    This endpoint replaces the previous Google Pub/Sub push handler and
    now expects the raw job JSON from the server.
    """
    job_id = job_data.get("job_id", "N/A")
    print(f"[webhook] Received job {job_id}")

    try:
        queue = getattr(request.app.state, "job_queue", None)
        if queue is None:
            raise RuntimeError("Job queue not initialized")

        # Schedule an async put so we return immediately
        asyncio.create_task(queue.put(job_data))
        print(f"[webhook] Job {job_id} scheduled for processing")
    except Exception as e:
        print(f"[webhook] Failed to enqueue job {job_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue job: {e}",
        )

    return {"status": "Job accepted for processing"}
