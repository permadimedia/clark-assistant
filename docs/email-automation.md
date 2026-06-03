# Email Automation Module — Setup Guide

## Privacy & Safety First

This module reads **only metadata** from your inbox:
- Sender name & email address
- Subject line
- Date received
- Snippet/preview (~100 characters)

**No body content, no attachments, no sent messages, no contacts.**

The default scope is `gmail.metadata` (read-only). Write operations (labeling,
archiving, trashing) require explicit opt-in via `read_only: false` in config.

---

## Setup (Gmail)

### Step 1: Create a Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Navigate to **APIs & Services → Library**
4. Search for **Gmail API** → Enable

### Step 2: Create OAuth 2.0 Credentials

1. **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth Client ID**
3. Application type: **Desktop app**
4. Name: `clark-email-automation`
5. Click **Create**
6. Click **Download JSON** → save the file

### Step 3: Save Credentials Locally

```bash
mkdir -p ~/.config/email
mv ~/Downloads/client_secret_*.json ~/.config/email/credentials.json
```

### Step 4: Enable the Module

Add to your `clark.json`:

```json
{
  "modules": {
    "email_automation": {
      "enabled": true,
      "provider": "gmail",
      "credentials_path": "~/.config/email/credentials.json",
      "token_path": "~/.config/email/token.json",
      "scan_schedule": "0 7 * * *",
      "scan_limit": 50,
      "chat_id": 76465160,
      "labels_enabled": true,
      "archive_read_after_days": 90,
      "trash_draft_after_days": 30,
      "read_only": true
    }
  }
}
```

### Step 5: First Run

Restart clark:

```bash
python cli.py restart
```

On the first scan, a browser window will open asking for Gmail consent.
Authenticate with your Google account and grant the requested permissions.

After consent, a token will be saved to `~/.config/email/token.json`
for future use (no re-authentication needed).

---

## API Endpoints

Once the module is loaded, clark exposes:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/email/status` | Connection status, last scan info |
| `POST` | `/api/email/scan` | Trigger immediate scan |
| `POST` | `/api/email/cleanup` | Execute cleanup (read_only must be false) |

---

## Security Notes

- **Token files are private**: Never share `~/.config/email/token.json`.
  It's an OAuth token that grants access to your email metadata.
- **Revoke access anytime**: Visit https://myaccount.google.com/permissions
  → Revoke `clark-email-automation`.
- **Credentials are not in git**: Both `credentials.json` and `token.json`
  are stored outside the repository.
- **Start read-only**: The default is `read_only: true`. Only messages are
  fetched, never modified. Change to `false` only when you're ready for
  auto-labeling and archiving.

---

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| `401: Bad Credentials` | Token expired | Delete `~/.config/email/token.json` and re-authenticate |
| `missing credentials` | No credentials file | Complete Step 1-3 above |
| `missing dependencies` | Google libs not installed | `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib` |
| No notifications | chat_id not set | Set `chat_id` in config to your Telegram chat ID |
