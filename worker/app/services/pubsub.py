"""Retry helper for failed jobs.

Google Cloud Pub/Sub has been removed; this helper now simply logs and
does not attempt automatic retries.
"""

import logging
from typing import Any


logger = logging.getLogger(__name__)


async def publish_job_for_retry(job_data: dict[str, Any]) -> None:
    """Log that a job would be retried.

    Automatic re-queuing via Pub/Sub has been removed. This function is
    kept to avoid changing the job processor control flow but now only
    records that a retry was requested.
    """
    job_id = job_data.get("job_id", "N/A")
    retry_count = job_data.get("retry_count", 0) + 1
    logger.warning(
        "Retry requested for job %s (attempt %s), but automatic retries are disabled.",
        job_id,
        retry_count,
    )
    job_data["retry_count"] = retry_count
