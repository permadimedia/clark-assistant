"""Gmail API provider — OAuth2, metadata-only reads, optional labeling.

Uses google-api-python-client with minimal scopes:
  - gmail.metadata (default): read from/subject/date/labels only
  - gmail.modify (optional): apply labels, archive, trash
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from modules.email_automation.providers.base import EmailMessage, EmailProvider

logger = logging.getLogger(__name__)

# ── Gmail API scopes ──────────────────────────────────────

SCOPE_METADATA = "https://www.googleapis.com/auth/gmail.metadata"
SCOPE_MODIFY = "https://www.googleapis.com/auth/gmail.modify"

# Google API client is heavy; lazy-import so the module loads fast
# even if google-auth isn't installed yet.


class GmailProvider(EmailProvider):
    """Gmail API provider — reads metadata only, no body or attachments."""

    def __init__(self, credentials_path: str, token_path: str, read_only: bool = True):
        super().__init__()
        self._creds_path = Path(credentials_path).expanduser()
        self._token_path = Path(token_path).expanduser()
        self._read_only = read_only
        self._service = None
        self._user_id = "me"

    # ── Lifecycle ───────────────────────────────────────────

    async def connect(self, credentials: dict | None = None) -> bool:
        """Authenticate with Gmail API using saved credentials.

        Args:
            credentials: Optional overrides. If None, reads from credentials_path.

        Returns:
            True if connected and authenticated.
        """
        try:
            # Lazy import — only when this provider is actually used
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            scopes = [SCOPE_METADATA]
            if not self._read_only:
                scopes.append(SCOPE_MODIFY)

            creds = None

            # Load saved token if it exists
            if self._token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(
                        str(self._token_path), scopes
                    )
                except Exception as e:
                    logger.warning("Failed to load saved token: %s", e)

            # Refresh or create new token
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Gmail token refreshed")
                except Exception as e:
                    logger.warning("Token refresh failed: %s", e)
                    creds = None

            if not creds or not creds.valid:
                if not self._creds_path.exists():
                    logger.error(
                        "Gmail credentials file not found at %s. "
                        "Create a Google Cloud Project → Enable Gmail API → "
                        "Download OAuth 2.0 credentials JSON.",
                        self._creds_path,
                    )
                    self._status = "error: missing credentials"
                    return False

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._creds_path), scopes
                )

                # Detect headless — use console auth if no display available
                import os as _os
                has_display = bool(
                    _os.environ.get("DISPLAY") or _os.environ.get("WAYLAND_DISPLAY")
                )

                if has_display:
                    creds = flow.run_local_server(port=0)
                    logger.info("Gmail OAuth consent completed (browser)")
                else:
                    import urllib.parse

                    # Use out-of-band redirect URI for console-based flow
                    oob_uri = "urn:ietf:wg:oauth:2.0:oob"
                    flow.redirect_uri = oob_uri

                    auth_url, _ = flow.authorization_url(
                        access_type="offline",
                        include_granted_scopes="true",
                        prompt="consent",
                    )
                    print("\n" + "=" * 60)
                    print("🌐 OPEN THIS URL IN YOUR BROWSER (phone/laptop):")
                    print("=" * 60)
                    print(auth_url)
                    print("=" * 60)
                    print("\nAfter authenticating, Google will show you a code.")
                    print("Copy that code and paste it below.")
                    print("(You may need to click 'Copy' on the Google page)\n")
                    code = input("Paste authorization code: ").strip()
                    flow.fetch_token(code=code)
                    creds = flow.credentials
                    logger.info("Gmail OAuth consent completed (console)")

            # Save token for next session
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json())
            logger.info("Gmail token saved to %s", self._token_path)

            # Build the API service
            self._service = build("gmail", "v1", credentials=creds)
            self._status = "connected"
            logger.info("Gmail provider connected")
            return True

        except ImportError as e:
            logger.error(
                "Missing dependencies: %s. Install with: "
                "pip install google-api-python-client google-auth-httplib2 "
                "google-auth-oauthlib", e
            )
            self._status = "error: missing dependencies"
            return False

        except Exception as e:
            logger.exception("Gmail connection failed")
            self._status = f"error: {e}"
            return False

    async def disconnect(self) -> None:
        """Release the Gmail API service."""
        if self._service:
            self._service = None
        self._status = "disconnected"
        logger.info("Gmail provider disconnected")

    # ── Read operations ─────────────────────────────────────

    async def list_inbox(self, limit: int = 50) -> list[EmailMessage]:
        """Fetch recent inbox messages — metadata only.

        Uses gmail.metadata scope: returns id, threadId, from, subject, date,
        labelIds, snippet (~100 chars). No body, no attachments.
        """
        if not self._service:
            logger.warning("Gmail provider not connected")
            return []

        try:
            results = self._service.users().messages().list(
                userId=self._user_id,
                maxResults=limit,
                labelIds=["INBOX"],
                fields="messages(id)",
            ).execute()

            msg_ids = [m["id"] for m in results.get("messages", [])]
            if not msg_ids:
                logger.info("No inbox messages found")
                return []

            messages = []
            for msg_id in msg_ids:
                msg = self._service.users().messages().get(
                    userId=self._user_id,
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                    fields="id,labelIds,snippet,internalDate,payload/headers",
                ).execute()

                email = self._parse_message(msg)
                if email:
                    messages.append(email)

            logger.info("Fetched %d messages from inbox", len(messages))
            return messages

        except Exception as e:
            logger.exception("Failed to fetch inbox")
            return []

    async def list_drafts(self, limit: int = 20) -> list[EmailMessage]:
        """Fetch draft messages — for cleanup suggestions."""
        if not self._service:
            return []

        try:
            # Use dedicated drafts.list endpoint (metadata scope compatible)
            results = self._service.users().drafts().list(
                userId=self._user_id,
                maxResults=limit,
            ).execute()

            # Drafts endpoint returns draft objects with id + message nested
            draft_items = results.get("drafts", [])
            if not draft_items:
                return []

            messages = []
            for item in draft_items:
                msg_id = item.get("id", "")
                if not msg_id:
                    continue
                # Fetch full draft message with metadata
                msg = self._service.users().drafts().get(
                    userId=self._user_id,
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()

                # The message payload is nested under msg["message"]
                inner = msg.get("message", {})
                if not inner.get("id"):
                    continue
                email = self._parse_message(inner, is_draft=True)
                if email:
                    messages.append(email)

            return messages

        except Exception as e:
            logger.exception("Failed to fetch drafts")
            return []

    # ── Write operations ────────────────────────────────────

    async def apply_labels(self, message_id: str, labels: list[str]) -> bool:
        """Apply Gmail labels to a message."""
        if not self._service:
            return False

        try:
            body = {
                "addLabelIds": labels,
                "removeLabelIds": [],
            }
            self._service.users().messages().modify(
                userId=self._user_id, id=message_id, body=body
            ).execute()
            return True
        except Exception as e:
            logger.warning("Failed to apply labels to %s: %s", message_id, e)
            return False

    async def archive(self, message_id: str) -> bool:
        """Remove from inbox (archive = remove INBOX label)."""
        if not self._service:
            return False

        try:
            body = {
                "removeLabelIds": ["INBOX"],
            }
            self._service.users().messages().modify(
                userId=self._user_id, id=message_id, body=body
            ).execute()
            return True
        except Exception as e:
            logger.warning("Failed to archive %s: %s", message_id, e)
            return False

    async def trash(self, message_id: str) -> bool:
        """Move message to trash."""
        if not self._service:
            return False

        try:
            self._service.users().messages().trash(
                userId=self._user_id, id=message_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("Failed to trash %s: %s", message_id, e)
            return False

    async def mark_read(self, message_id: str) -> bool:
        """Mark message as read (remove UNREAD label)."""
        if not self._service:
            return False

        try:
            body = {
                "removeLabelIds": ["UNREAD"],
            }
            self._service.users().messages().modify(
                userId=self._user_id, id=message_id, body=body
            ).execute()
            return True
        except Exception as e:
            logger.warning("Failed to mark read %s: %s", message_id, e)
            return False

    # ── Storage info ────────────────────────────────────────

    async def get_storage_info(self) -> dict:
        """Get Gmail mailbox stats — messages & threads count.

        Note: storageQuota is not available with gmail.metadata scope.
        Returns message count as a proxy for mailbox size.
        """
        if not self._service:
            return {"used_bytes": 0, "total_bytes": 0}

        try:
            profile = self._service.users().getProfile(
                userId=self._user_id,
                fields="emailAddress,messagesTotal,threadsTotal",
            ).execute()

            msg_count = int(profile.get("messagesTotal", 0))
            # Approximate: ~5 KB per message average
            approx_bytes = msg_count * 5120
            return {
                "used_bytes": approx_bytes,
                "total_bytes": 15 * 1024**3,  # 15 GB default Gmail quota
                "messages_total": msg_count,
                "threads_total": int(profile.get("threadsTotal", 0)),
            }
        except Exception as e:
            logger.warning("Failed to get storage info: %s", e)
            return {"used_bytes": 0, "total_bytes": 0}

    # ── Internal ────────────────────────────────────────────

    def _parse_message(self, msg: dict, is_draft: bool = False) -> EmailMessage | None:
        """Parse Gmail API response into EmailMessage (metadata only)."""
        try:
            msg_id = msg.get("id", "")
            if not msg_id:
                return None

            # Extract headers (from, subject, date)
            headers = {h["name"].lower(): h["value"] for h in
                       msg.get("payload", {}).get("headers", [])}

            from_header = headers.get("from", "")
            subject = headers.get("subject", "(no subject)")
            date_str = headers.get("date", "")

            # Parse sender name + email
            from_name = None
            from_email = from_header
            if "<" in from_header and ">" in from_header:
                parts = from_header.split("<", 1)
                from_name = parts[0].strip().strip('"')
                from_email = parts[1].rstrip(">").strip()
            elif from_header:
                from_name = from_header.strip()

            # Parse date
            received_at = None
            if date_str:
                try:
                    # Try email-style date first
                    from email.utils import parsedate_to_datetime
                    received_at = parsedate_to_datetime(date_str)
                except Exception:
                    try:
                        # Fallback: use internalDate (unix ms)
                        internal_ms = msg.get("internalDate")
                        if internal_ms:
                            received_at = datetime.fromtimestamp(
                                int(internal_ms) / 1000, tz=timezone.utc
                            )
                    except Exception:
                        pass

            label_ids = msg.get("labelIds", [])
            is_read = "UNREAD" not in label_ids
            snippet = msg.get("snippet", "")[:100] or None

            return EmailMessage(
                id=msg_id,
                from_name=from_name,
                from_email=from_email,
                subject=subject,
                snippet=snippet,
                received_at=received_at,
                is_read=is_read,
                labels=label_ids,
                is_draft=is_draft,
            )

        except Exception as e:
            logger.warning("Failed to parse message %s: %s", msg.get("id"), e)
            return None
