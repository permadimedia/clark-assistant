"""clark — Ask clark. AI agent backend API for menial tasks.

Usage:
    uvicorn app:app --host 127.0.0.1 --port 8124
"""

from core.app import create_app

app = create_app()
