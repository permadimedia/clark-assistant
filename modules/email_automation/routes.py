"""Email automation API endpoints — status, manual scan, and cleanup trigger."""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email_automation"])


# ── Models ──────────────────────────────────────────────────

class EmailStatusResponse(BaseModel):
    provider: str
    status: str
    read_only: bool
    last_scan_at: str | None = None
    last_scan_summary: dict | None = None


class ScanResponse(BaseModel):
    status: str
    provider: str
    messages_processed: int
    priority_count: int
    archived_count: int
    summary: str | None = None


class CleanupResponse(BaseModel):
    status: str
    drafts_deleted: int
    archived_count: int
    read_only: bool


# ── Helpers ────────────────────────────────────────────────

def _get_engine(request: Request):
    """Resolve email engine from app state or module manager."""
    module = getattr(request.app.state, "email_automation_module", None)
    if module is None:
        # Fallback: scan through modules
        from core.app import get_module_manager
        mgr = get_module_manager(request.app)
        module = mgr.get("email_automation") if mgr else None
    if module is None:
        raise HTTPException(status_code=503, detail="EmailAutomation module not loaded")
    engine = getattr(module, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Email engine not initialized")
    return engine


# ── Endpoints ──────────────────────────────────────────────

@router.get("/status", response_model=EmailStatusResponse)
async def email_status(request: Request):
    """Get email automation status — provider, last scan, connection state."""
    engine = _get_engine(request)
    provider_name = engine.provider_type
    provider_status = engine.provider.status if engine.provider else "disconnected"
    return EmailStatusResponse(
        provider=provider_name,
        status=provider_status,
        read_only=engine.read_only,
        last_scan_at=engine.last_scan_at,
        last_scan_summary=engine.last_summary,
    )


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan(request: Request):
    """Trigger an inbox scan immediately. Returns classification results."""
    engine = _get_engine(request)
    if engine.provider is None:
        raise HTTPException(status_code=503, detail="Provider not connected")

    try:
        result = await engine.scan()
        return ScanResponse(
            status="completed",
            provider=engine.provider_type,
            messages_processed=result.get("total", 0),
            priority_count=result.get("priority_count", 0),
            archived_count=result.get("archived_count", 0),
            summary=result.get("summary", ""),
        )
    except Exception as e:
        logger.exception("Manual scan failed")
        raise HTTPException(status_code=500, detail=f"Scan failed: {e}")


@router.post("/cleanup", response_model=CleanupResponse)
async def trigger_cleanup(request: Request):
    """Execute cleanup: delete old drafts, archive read emails.

    Only available when read_only=false in config.
    """
    engine = _get_engine(request)
    if engine.read_only:
        raise HTTPException(status_code=403, detail="Read-only mode — set read_only=false in clark.json to enable cleanup")

    if engine.provider is None:
        raise HTTPException(status_code=503, detail="Provider not connected")

    try:
        result = await engine.cleanup(
            archive_days=engine.archive_read_after_days,
            draft_days=engine.trash_draft_after_days,
        )
        return CleanupResponse(
            status="completed",
            drafts_deleted=result.get("drafts_deleted", 0),
            archived_count=result.get("archived_count", 0),
            read_only=False,
        )
    except Exception as e:
        logger.exception("Cleanup failed")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")
