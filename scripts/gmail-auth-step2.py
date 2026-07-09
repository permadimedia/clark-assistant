#!/usr/bin/env python3
"""Step 2: Exchange OAuth code for token. Usage: python gmail-auth-step2.py <CODE>"""
import json, os, sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python gmail-auth-step2.py <AUTH_CODE>")
    sys.exit(1)

code = sys.argv[1].strip()
token_path = Path(os.path.expanduser("~/.config/email/"))
state_file = token_path / "oauth_flow_state.json"

if not state_file.exists():
    print("❌ No OAuth state found. Run gmail-auth-step1.py first.")
    sys.exit(1)

with open(state_file) as f:
    state = json.load(f)

from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_config(
    state["client_config"],
    scopes=["https://www.googleapis.com/auth/gmail.metadata"],
)
flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
flow.code_verifier = state["code_verifier"]

flow.fetch_token(code=code)
creds = flow.credentials

# Save token
with open(token_path / "token.json", "w") as f:
    f.write(creds.to_json())

print(f"✅ Token saved to {token_path / 'token.json'}")
print(f"✅ Email: {creds.valid}")
print(f"✅ Expired: {creds.expired}")

# Cleanup state file
state_file.unlink(missing_ok=True)
