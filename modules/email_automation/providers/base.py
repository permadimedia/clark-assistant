"""Abstract email provider interface — all providers implement this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailMessage:
    """Minimal email metadata — no body content, no attachments.

    Privacy-first design: only what's needed for classification and notification.
    """
    id: str                                  # Provider-specific message ID
    from_name: str | None = None             # Display name of sender
    from_email: str = ""                     # Sender email address
    subject: str = ""                        # Subject line
    snippet: str | None = None               # ~100 char preview (no full body)
    received_at: datetime | None = None      # Date/time received
    is_read: bool = False                    # Has been read
    labels: list[str] = field(default_factory=list)  # Existing labels/folders
    is_draft: bool = False                   # Is a draft message
    has_attachments: bool = False            # Has attachments (boolean only — no content)

    @property
    def domain(self) -> str:
        """Extract domain from sender email."""
        if "@" in self.from_email:
            return self.from_email.split("@", 1)[1].lower()
        return ""

    @property
    def is_bulk(self) -> bool:
        """Check if likely a bulk/newsletter sender."""
        return any(self.from_email.startswith(f"{p}+") for p in
                   ("noreply", "no-reply", "notification", "mail", "newsletter"))


class EmailProvider(ABC):
    """Abstract base class for email provider integrations.

    Each provider (Gmail API, IMAP, Outlook Graph, etc.) implements
    these methods. The engine only talks through this interface,
    keeping classification and notification logic completely provider-agnostic.
    """

    def __init__(self):
        self._status = "disconnected"

    @property
    def status(self) -> str:
        return self._status

    # ── Lifecycle ───────────────────────────────────────────

    @abstractmethod
    async def connect(self, credentials: dict) -> bool:
        """Authenticate and connect to the email provider.

        Args:
            credentials: Provider-specific credentials dict
                (OAuth client config, IMAP host/pass, etc.)

        Returns:
            True if connection established successfully.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connections and release resources."""
        ...

    # ── Read operations ─────────────────────────────────────

    @abstractmethod
    async def list_inbox(self, limit: int = 50) -> list[EmailMessage]:
        """Fetch recent inbox messages — metadata only.

        Args:
            limit: Maximum number of messages to fetch.

        Returns:
            List of EmailMessage objects with metadata only.
            No body content, no attachments.
        """
        ...

    @abstractmethod
    async def list_drafts(self, limit: int = 20) -> list[EmailMessage]:
        """Fetch draft messages — for cleanup suggestions.

        Args:
            limit: Maximum number of drafts to fetch.

        Returns:
            List of draft EmailMessage objects (metadata only).
        """
        ...

    # ── Write operations (optional, gated by read_only flag) ─

    @abstractmethod
    async def apply_labels(self, message_id: str, labels: list[str]) -> bool:
        """Apply labels/categories to a message.

        Args:
            message_id: Provider-specific message ID.
            labels: Label names to apply.

        Returns:
            True if labels were applied successfully.
        """
        ...

    @abstractmethod
    async def archive(self, message_id: str) -> bool:
        """Remove from inbox (archive).

        Args:
            message_id: Provider-specific message ID.

        Returns:
            True if message was archived.
        """
        ...

    @abstractmethod
    async def trash(self, message_id: str) -> bool:
        """Move message to trash.

        Args:
            message_id: Provider-specific message ID.

        Returns:
            True if message was trashed.
        """
        ...

    @abstractmethod
    async def mark_read(self, message_id: str) -> bool:
        """Mark message as read.

        Args:
            message_id: Provider-specific message ID.

        Returns:
            True if message was marked as read.
        """
        ...

    # ── Storage info ────────────────────────────────────────

    @abstractmethod
    async def get_storage_info(self) -> dict:
        """Get mailbox storage statistics.

        Returns:
            dict with keys: used_bytes, total_bytes (or equivalent).
        """
        ...
