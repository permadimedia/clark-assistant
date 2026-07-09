#!/usr/bin/env python3
"""Step 1: Print Gmail OAuth URL. User opens in browser, then sends code back."""
import json, os, sys
from pathlib import Path

creds_path = Path(os.path.expanduser("~/.config/email/credentials.json"))
if not creds_path.exists():
    print("❌ Credentials not found")
    sys.exit(1)

# Load client config
with open(creds_path) as f:
    client_config = json.load(f)

# Build the OAuth URL manually — works without interactive input
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_config(
    client_config,
    scopes=["https://www.googleapis.com/auth/gmail.metadata"],
)
flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
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
print("\nAfter authenticating, Google shows a code.")
print("Copy that code and send it to me here.\n")

# Save flow state for next step
token_path = Path(os.path.expanduser("~/.config/email/"))
token_path.mkdir(parents=True, exist_ok=True)
state_file = token_path / "oauth_flow_state.json"
with open(state_file, "w") as f:
    json.dump({
        "client_config": client_config,
        "code_verifier": flow.code_verifier,
    }, f)
print("💾 OAuth state saved. Send me the code when you have it.")
