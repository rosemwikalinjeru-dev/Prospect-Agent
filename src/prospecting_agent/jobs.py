"""Thread-safe in-memory store for background search jobs, backing the webapp's async
`/api/confirm_run` + `/api/run_status/<job_id>` pair.

Safe as a plain in-process dict specifically because the deployed app runs with a single
worker process (Render's own deploy log shows `WEB_CONCURRENCY=1`) — if that ever changes,
this would need a real shared store (e.g. Redis) instead, since each worker would have
its own copy of `_jobs`.
"""

import threading
import uuid

_jobs: dict[str, dict] = {}
_lock = threading.Lock()

STAGE_LABELS = {
    "finding": "Finding businesses",
    "deduping": "Removing duplicates",
    "verifying": "Verifying contact details",
    "scoring": "Calculating lead scores",
    "saving": "Saving results",
}


def create_job() -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"status": "running", "stage": None, "written": None, "error": None}
    return job_id


def update_job(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
