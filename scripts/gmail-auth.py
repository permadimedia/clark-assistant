#!/usr/bin/env python3
"""Gmail OAuth setup — run this once to grant consent and save token.

Usage:
    python scripts/gmail-auth.py

If run on a headless system (no display), it will print a URL.
Open that URL in any browser (phone/laptop), authenticate,
copy the authorization code, and paste it back here.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.email_automation.providers.gmail import GmailProvider


async def main():
    creds_path = os.path.expanduser("~/.config/email/credentials.json")
    token_path = os.path.expanduser("~/.config/email/token.json")

    if not os.path.exists(creds_path):
        print(f"❌ Credentials not found at {creds_path}")
        print("")
        print("Create a Google Cloud Project → Enable Gmail API →")
        print("Download OAuth 2.0 credentials JSON and save it to:")
        print(f"  {creds_path}")
        sys.exit(1)

    print(f"📁 Credentials: {creds_path}")
    print(f"📁 Token will be saved to: {token_path}")
    print("")
    print("🚀 Starting Gmail OAuth flow...")
    print("")

    provider = GmailProvider(
        credentials_path=creds_path,
        token_path=token_path,
        read_only=True,
    )

    ok = await provider.connect()
    if ok:
        print("")
        print("✅ OAuth consent completed!")
        print(f"✅ Token saved to {token_path}")
        print("")
        print("📬 Testing inbox access...")
        messages = await provider.list_inbox(limit=5)
        if messages:
            print(f"✅ Successfully fetched {len(messages)} messages from inbox!")
            for m in messages[:3]:
                print(f"   • {m.from_email}: {m.subject[:60]}")
        else:
            print("ℹ️  No inbox messages found (or empty inbox).")

        # Get storage info
        storage = await provider.get_storage_info()
        used_mb = storage.get("used_bytes", 0) / (1024**2)
        total_mb = storage.get("total_bytes", 15 * 1024**3) / (1024**2)
        print(f"💾 Storage: {used_mb:.0f} MB / {total_mb:.0f} MB")
    else:
        print(f"❌ Authentication failed. Check your credentials file.")
        sys.exit(1)

    await provider.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
