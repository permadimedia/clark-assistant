"""Telegram notification sender — sends messages directly via Bot API."""

import logging

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_BOT_API = "https://api.telegram.org/bot{}"
_HTTP: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Lazy-init shared httpx client."""
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.AsyncClient(timeout=10.0)
    return _HTTP


async def close() -> None:
    """Cleanup on shutdown."""
    global _HTTP
    if _HTTP:
        await _HTTP.aclose()
        _HTTP = None


async def send_message(
    text: str,
    chat_id: int | None = None,
    parse_mode: str | None = "HTML",
) -> bool:
    """Send a Telegram message to the configured chat.

    Returns True on success, False on failure.
    """
    if not settings.telegram_token:
        logger.warning("TELEGRAM_TOKEN not set, cannot send notification")
        return False

    chat = chat_id or settings.telegram_chat_id
    url = f"{_BOT_API.format(settings.telegram_token)}/sendMessage"
    payload: dict = {
        "chat_id": chat,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        client = await _get_client()
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        logger.info("Telegram message sent to %s", chat)
        return True
    except httpx.HTTPStatusError as e:
        logger.error("Telegram API error: %s — %s", e.response.status_code, e.response.text)
        return False
    except httpx.RequestError as e:
        logger.error("Telegram request failed: %s", e)
        return False


async def send_reminder_notification(reminder_id: int, text: str, time_str: str) -> None:
    """Send a nicely formatted reminder notification."""
    message = (
        f"🔔 <b>REMINDER</b>\n\n"
        f"<b>{text}</b>\n\n"
        f"⏰ {time_str}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🦊 <i>clark</i>"
    )
    await send_message(message)
