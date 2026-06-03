"""Email automation API endpoints — status, manual scan, search, and cleanup."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email_automation"])


# ── Response Models ────────────────────────────────────────

class EmailStatusResponse(BaseModel):
    provider: str
    status: str
    read_only: bool
    last_scan_at: str | None = None
    last_scan_summary: dict | None = None
    stats: dict | None = None
    recent_scans: list | None = None


class ScanResponse(BaseModel):
    status: str
    provider: str
    total: int
    new: int
    seen: int
    priority_count: int
    classified: dict | None = None
    summary: str | None = None
    last_scan_at: str | None = None


class CleanupResponse(BaseModel):
    status: str
    drafts_deleted: int
    archived_count: int
    read_only: bool


class SearchResponse(BaseModel):
    status: str
    source: str
    count: int
    summary: str | None = None


# ── Helpers ────────────────────────────────────────────────

def _get_engine(request: Request):
    """Resolve email engine from app state or module manager."""
    module = getattr(request.app.state, "email_automation_module", None)
    if module is None:
        mgr = getattr(request.app.state, "module_manager", None)
        module = mgr.get("email_automation") if mgr else None
    if module is None:
        raise HTTPException(status_code=503, detail="EmailAutomation module not loaded")
    engine = getattr(module, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Email engine not initialized")
    return engine


def _format_search_results(results: list[dict], keyword: str) -> str:
    """Format search results into Telegram-friendly text."""
    from modules.email_automation.labels import LABELS
    from collections import defaultdict

    if not results:
        return f"📬 Email — \"{keyword}\"\n\nNo results found."

    # Group sender by domain
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        domain = r.get("from_email", "").split("@")[-1] if "@" in r.get("from_email", "") else "unknown"
        groups[domain].append(r)

    # Determine primary category from results
    priority_count = sum(1 for r in results if r.get("label_key", "").startswith("priority"))
    tag = "🔒 Priority" if priority_count > 0 else "📄 Informational"

    lines = [
        f"📬 Email Query — \"{keyword}\"",
        f"{tag} — {len(results)} found",
        "",
    ]

    for domain, domain_msgs in sorted(groups.items()):
        company = domain.split(".")[-2].capitalize() if len(domain.split(".")) >= 2 else domain
        lines.append(f"🏢 {company} — {len(domain_msgs)} email{'s' if len(domain_msgs) != 1 else ''}")

        for m in domain_msgs[:8]:  # max 8 per domain
            sender = m.get("from_name", "") or m.get("from_email", "")
            subject = m.get("subject", "(no subject)")
            received_at = m.get("received_at", "")

            badge = ""
            if m.get("is_new"):
                badge = " 🆕"
            elif not m.get("is_read"):
                badge = " 📌"

            lines.append(f"• {sender}{badge}")
            lines.append(f"  {subject}")
            if received_at:
                from modules.email_automation.formatter import _format_time_str
                lines.append(f"  📅 {_format_time_str(received_at)}")
            lines.append("")

        if len(domain_msgs) > 8:
            lines.append(f"  … and {len(domain_msgs) - 8} more")

    lines.append("━" * 25)
    lines.append("🦊 <i>clark · local search</i>")

    return "\n".join(lines)


# ── Endpoints ──────────────────────────────────────────────


@router.get("/status", response_model=EmailStatusResponse)
async def email_status(request: Request):
    """Get email automation status — provider, last scan, DB stats, scan history."""
    engine = _get_engine(request)
    info = await engine.get_status()
    return EmailStatusResponse(
        provider=info["provider"],
        status=info["status"],
        read_only=info["read_only"],
        last_scan_at=info["last_scan_at"],
        last_scan_summary=info["last_scan_summary"],
        stats=info.get("stats"),
        recent_scans=info.get("recent_scans"),
    )


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan(request: Request):
    """Trigger an inbox scan immediately. Only NEW items in summary."""
    engine = _get_engine(request)
    try:
        result = await engine.scan()
        return ScanResponse(
            status="completed",
            provider=engine.provider_type,
            total=result.get("total", 0),
            new=result.get("new", 0),
            seen=result.get("seen", 0),
            priority_count=result.get("priority_count", 0),
            classified=result.get("classified"),
            summary=result.get("summary", ""),
            last_scan_at=result.get("last_scan_at"),
        )
    except Exception as e:
        logger.exception("Manual scan failed")
        raise HTTPException(status_code=500, detail=f"Scan failed: {e}")


@router.post("/notified")
async def mark_notified(request: Request):
    """Mark all pending new messages as notified (call after sending notification)."""
    engine = _get_engine(request)
    new_items = await engine.db.get_new_unnotified(provider=engine.provider_type)
    ids = [r["message_id"] for r in new_items]
    await engine.mark_notified(ids)
    return {"status": "ok", "marked": len(ids)}


@router.get("/search")
async def search_email(
    request: Request,
    q: str = Query(..., description="Keyword to search email sender/subject"),
):
    """Search tracked emails by sender or subject (local DB first)."""
    engine = _get_engine(request)
    try:
        result = await engine.search(q)
        summary = _format_search_results(result["messages"], q)
        return SearchResponse(
            status="ok",
            source=result["source"],
            count=result["count"],
            summary=summary,
        )
    except Exception as e:
        logger.exception("Email search failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


@router.post("/cleanup", response_model=CleanupResponse)
async def trigger_cleanup(request: Request):
    """Execute cleanup: delete old drafts, archive read emails.

    Only available when read_only=false in config.
    """
    engine = _get_engine(request)
    if engine.read_only:
        raise HTTPException(status_code=403, detail="Read-only mode — set read_only=false to enable cleanup")

    if engine.provider is None and not await engine.connect():
        raise HTTPException(status_code=503, detail="Provider not connected")

    try:
        result = await engine.cleanup()
        return CleanupResponse(
            status="completed",
            drafts_deleted=result.get("drafts_deleted", 0),
            archived_count=result.get("archived_count", 0),
            read_only=False,
        )
    except Exception as e:
        logger.exception("Cleanup failed")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}")
