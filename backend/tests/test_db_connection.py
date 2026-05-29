"""Connection / client health tests for the backend Supabase layer.

These guard the database *connection and client wiring* against regressions (e.g. the
unawaited `acreate_client` bug) rather than the schema. They intentionally do NOT assert
anything about table columns or row contents.

Tiers:
  - construction/wiring tests run offline (no network, no creds).
  - live tests require VITE_SUPABASE_URL + VITE_SUPABASE_PUBLISHABLE_KEY (loaded from the
    repo-root .env by conftest.py) and are skipped otherwise.
"""
import asyncio
import inspect
import os

import pytest
from supabase import AsyncClient, acreate_client

from backend import database
from backend.main import app, lifespan

LIVE = bool(os.getenv("VITE_SUPABASE_URL") and os.getenv("VITE_SUPABASE_PUBLISHABLE_KEY"))
requires_creds = pytest.mark.skipif(
    not LIVE,
    reason="needs VITE_SUPABASE_URL + VITE_SUPABASE_PUBLISHABLE_KEY (repo-root .env)",
)

# Well-formed but fake — acreate_client constructs the client locally without a network call.
FAKE_URL = "https://example-project.supabase.co"
FAKE_KEY = "fake-key-for-construction-only"


# --- client construction & wiring (offline) ---------------------------------

def test_acreate_client_must_be_awaited():
    """acreate_client is a coroutine function: calling it without `await` yields a
    coroutine, not a client. This is the exact shape of the lifespan bug we fixed."""
    coro = acreate_client(FAKE_URL, FAKE_KEY)
    try:
        assert inspect.iscoroutine(coro)
    finally:
        coro.close()  # avoid "coroutine was never awaited" warning


def test_awaited_acreate_client_returns_async_client():
    async def _make():
        return await acreate_client(FAKE_URL, FAKE_KEY)

    client = asyncio.run(_make())
    assert isinstance(client, AsyncClient)
    assert hasattr(client, "table") and hasattr(client, "rpc")


def test_initialize_db_sets_module_client():
    """initialize_db must wire the passed client into the module-level global that the
    query helpers use."""
    original = database.supabase
    try:
        sentinel = object()
        database.initialize_db(sentinel)
        assert database.supabase is sentinel
    finally:
        database.initialize_db(original)


# --- lifespan & live connection (need creds) ---------------------------------

@requires_creds
def test_app_boots_and_health_ok():
    """The app's lifespan (env load + client creation + initialize_db) runs without error,
    and a non-DB endpoint responds. Drives the lifespan + ASGI app directly (avoids the
    starlette TestClient, which is incompatible with httpx >= 0.28's removed `app=` kwarg)."""
    from httpx import ASGITransport, AsyncClient as HttpxClient

    async def _boot_and_health():
        async with lifespan(app):
            transport = ASGITransport(app=app)
            async with HttpxClient(transport=transport, base_url="http://test") as ac:
                return await ac.get("/api/health")

    resp = asyncio.run(_boot_and_health())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@requires_creds
def test_lifespan_initializes_real_async_client():
    """After startup the shared client must be a live AsyncClient, not an un-awaited
    coroutine — the precise failure mode the lifespan bug produced."""
    async def _boot():
        async with lifespan(app):
            return database.supabase

    client = asyncio.run(_boot())
    assert isinstance(client, AsyncClient)
    assert not inspect.iscoroutine(client)


@requires_creds
def test_live_db_roundtrip():
    """Connectivity smoke test: a query round-trips and returns a list. Uses the core
    `securities` table only as a ping; asserts nothing about its columns or contents."""
    async def _ping():
        client = await acreate_client(
            os.environ["VITE_SUPABASE_URL"],
            os.environ["VITE_SUPABASE_PUBLISHABLE_KEY"],
        )
        return await client.table("securities").select("*").limit(1).execute()

    resp = asyncio.run(_ping())
    assert isinstance(resp.data, list)