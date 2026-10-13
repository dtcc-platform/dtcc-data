"""Check limiter ownership and enforcement through the application lifespan."""

import multiprocessing
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

import server


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "startup", "shutdown"])
async def test_lifespan_closes_manager_even_on_database_failure(monkeypatch, failure):
    baseline = {p.pid for p in multiprocessing.active_children()}
    children = []

    async def init_pool():
        children[:] = [p for p in multiprocessing.active_children() if p.pid not in baseline]
        if failure == "startup":
            raise RuntimeError("database startup failed")

    monkeypatch.setattr(server, "ENABLE_RATE_LIMIT", True)
    monkeypatch.setattr(server.db, "init_pool", init_pool)
    monkeypatch.setattr(server.db, "close_pool", AsyncMock(
        side_effect=RuntimeError("database shutdown failed") if failure == "shutdown" else None
    ))
    app = server.create_app()
    assert {p.pid for p in multiprocessing.active_children()} == baseline

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            assert len(children) == 1 and children[0].is_alive()

    # Reusing an app must create fresh resources after both success and failure.
    for _ in range(2):
        if failure == "none":
            await run_lifespan()
        else:
            with pytest.raises(RuntimeError, match=f"database {failure} failed"):
                await run_lifespan()
        assert len(children) == 1 and not children[0].is_alive()


@pytest.mark.asyncio
async def test_lifespan_preserves_client_and_global_limits(monkeypatch):
    monkeypatch.setattr(server, "ENABLE_RATE_LIMIT", True)
    monkeypatch.setattr(server, "RATE_REQ_LIMIT", 2)
    monkeypatch.setattr(server, "RATE_GLOBAL_LIMIT", 3)
    monkeypatch.setattr(server, "RATE_TIME_WINDOW", 60)
    monkeypatch.setattr(server.db, "init_pool", AsyncMock())
    monkeypatch.setattr(server.db, "close_pool", AsyncMock())
    app = server.create_app()

    @app.get("/rate-check")
    async def rate_check():
        return {"ok": True}

    # A fresh lifespan starts with fresh counters, as a restarted process would.
    for _ in range(2):
        async with app.router.lifespan_context(app):
            for address, expected in [("192.0.2.1", [200, 200, 429]), ("192.0.2.2", [200, 429])]:
                transport = httpx.ASGITransport(app=app, client=(address, 12345))
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    assert [(await client.get("/rate-check")).status_code for _ in expected] == expected


@pytest.mark.asyncio
async def test_disabled_limiter_starts_no_manager(monkeypatch):
    factory = Mock(side_effect=AssertionError("Disabled limiter must not start"))
    monkeypatch.setattr(server, "ENABLE_RATE_LIMIT", False)
    monkeypatch.setattr(server, "create_rate_limit_middleware", factory)
    monkeypatch.setattr(server.db, "init_pool", AsyncMock())
    monkeypatch.setattr(server.db, "close_pool", AsyncMock())
    app = server.create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/healthz")).status_code == 200
    factory.assert_not_called()
