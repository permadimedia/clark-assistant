"""Scheduler management API endpoints."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
from pydantic import BaseModel

from core.database import get_db
from core.scheduler import SchedulerManager
from core.scheduler.handlers import HANDLER_MAP

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


# ── Models ──────────────────────────────────────────────────

class JobCreate(BaseModel):
    name: str
    description: str = ""
    job_type: str
    schedule_type: str
    schedule_config: dict
    payload: dict
    enabled: bool = True
    max_retries: int = 0
    retry_delay_s: int = 60


class JobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    job_type: str | None = None
    schedule_config: dict | None = None
    payload: dict | None = None
    enabled: bool | None = None
    max_retries: int | None = None
    retry_delay_s: int | None = None


class JobResponse(BaseModel):
    id: int
    name: str
    description: str
    job_type: str
    schedule_type: str
    schedule_config: dict
    payload: dict
    enabled: bool
    max_retries: int
    retry_delay_s: int
    last_run_at: str | None = None
    next_run_at: str | None = None
    run_count: int = 0
    created_at: str
    updated_at: str


class JobRunResponse(BaseModel):
    id: int
    job_id: int
    status: str
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    result: str | None = None
    attempt: int = 1


class JobStatsResponse(BaseModel):
    total_jobs: int
    active_jobs: int
    runs_last_24h: int
    success_last_24h: int
    failed_last_24h: int


class HandlerInfo(BaseModel):
    name: str
    description: str


# ── Helpers ────────────────────────────────────────────────

def _get_mgr(request: Request) -> SchedulerManager:
    mgr = getattr(request.app.state, "scheduler_mgr", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    return mgr


async def _job_to_response(job) -> JobResponse:
    return JobResponse(
        id=job.id,
        name=job.name,
        description=job.description,
        job_type=job.job_type,
        schedule_type=job.schedule_type,
        schedule_config=job.schedule_config,
        payload=job.payload,
        enabled=job.enabled,
        max_retries=job.max_retries,
        retry_delay_s=job.retry_delay_s,
        last_run_at=job.last_run_at.strftime("%Y-%m-%dT%H:%M:%SZ") if job.last_run_at else None,
        next_run_at=job.next_run_at.strftime("%Y-%m-%dT%H:%M:%SZ") if job.next_run_at else None,
        run_count=job.run_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


_handler_descriptions = {
    "send_message": "Send an arbitrary Telegram message",
    "send_agenda": "Send daily agenda summary via Telegram",
    "reminder_alert": "Fire a single reminder notification",
}


# ── CRUD ──────────────────────────────────────────────────

@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(body: JobCreate, request: Request):
    """Create a new scheduled job."""
    mgr = _get_mgr(request)
    job_id = await mgr.store.create_job(
        name=body.name, job_type=body.job_type,
        schedule_type=body.schedule_type, schedule_config=body.schedule_config,
        payload=body.payload, description=body.description or "",
        enabled=body.enabled, max_retries=body.max_retries, retry_delay_s=body.retry_delay_s,
    )
    job = await mgr.store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to create job")
    return await _job_to_response(job)


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(request: Request, enabled_only: bool = False):
    """List all scheduled jobs."""
    mgr = _get_mgr(request)
    jobs = await mgr.store.list_jobs(enabled_only=enabled_only)
    return [await _job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, request: Request):
    """Get a single job by ID."""
    mgr = _get_mgr(request)
    job = await mgr.store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _job_to_response(job)


@router.put("/jobs/{job_id}", response_model=JobResponse)
async def update_job(job_id: int, body: JobUpdate, request: Request):
    """Update a job's configuration."""
    mgr = _get_mgr(request)
    existing = await mgr.store.get_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Job not found")
    kwargs = {}
    for field in ("name", "description", "job_type", "schedule_config", "payload", "enabled", "max_retries", "retry_delay_s"):
        val = getattr(body, field, None)
        if val is not None:
            kwargs[field] = val
    ok = await mgr.store.update_job(job_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update job")
    job = await mgr.store.get_job(job_id)
    return await _job_to_response(job)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, request: Request):
    """Delete a job permanently."""
    mgr = _get_mgr(request)
    ok = await mgr.store.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    logger.info("Job #%d deleted", job_id)
    return {"status": "deleted", "id": job_id}


# ── Control ───────────────────────────────────────────────

@router.post("/jobs/{job_id}/trigger")
async def trigger_job(job_id: int, request: Request):
    """Manually trigger a job immediately."""
    mgr = _get_mgr(request)
    try:
        result = await mgr.trigger_job(job_id)
        return {"status": "triggered", "id": job_id, "result": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: int, request: Request):
    """Pause a job."""
    mgr = _get_mgr(request)
    ok = await mgr.store.set_enabled(job_id, False)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "paused", "id": job_id}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: int, request: Request):
    """Resume a job."""
    mgr = _get_mgr(request)
    ok = await mgr.store.set_enabled(job_id, True)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    job = await mgr.store.get_job(job_id)
    if job and job.next_run_at is None:
        from core.scheduler.job_store import JobStore
        next_run = JobStore._compute_next_run(job.schedule_type, job.schedule_config)
        await mgr.store.mark_next_run(job.id, next_run)
    return {"status": "resumed", "id": job_id}


# ── History & Stats ───────────────────────────────────────

@router.get("/jobs/{job_id}/runs", response_model=list[JobRunResponse])
async def get_job_runs(job_id: int, request: Request, limit: int = 20):
    """Get execution history for a job."""
    mgr = _get_mgr(request)
    job = await mgr.store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    runs = await mgr.store.get_run_history(job_id, limit=limit)
    return [
        JobRunResponse(id=r.id, job_id=r.job_id, status=r.status,
                       started_at=r.started_at, finished_at=r.finished_at,
                       error=r.error, result=r.result, attempt=r.attempt)
        for r in runs
    ]


@router.get("/stats", response_model=JobStatsResponse)
async def get_scheduler_stats(request: Request):
    """Get aggregate scheduler statistics."""
    mgr = _get_mgr(request)
    stats = await mgr.store.get_stats()
    return JobStatsResponse(**stats)


@router.get("/handlers", response_model=list[HandlerInfo])
async def list_handlers():
    """List available job handler types."""
    return [
        HandlerInfo(name=name, description=_handler_descriptions.get(name, ""))
        for name in sorted(HANDLER_MAP.keys())
    ]
