"""Shared test setup. Loads the repo-root .env so connection tests can reach Supabase
(the same .env that backend/main.py reads at startup)."""
from pathlib import Path

from dotenv import load_dotenv

_ENV = Path(__file__).resolve().parents[2] / ".env"
if _ENV.exists():
    load_dotenv(_ENV)