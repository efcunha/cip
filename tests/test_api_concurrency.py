"""Testes do middleware de concorrência: backpressure (429) e timeout (504)."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from cip.api.app import observability_middleware
from cip.config import get_settings


def _make_app(max_concurrent: int, sleep_s: float) -> FastAPI:
    app = FastAPI()
    app.state.semaphore = asyncio.Semaphore(max_concurrent)
    app.middleware("http")(observability_middleware)

    @app.get("/slow")
    async def slow():  # noqa: ANN202
        await asyncio.sleep(sleep_s)
        return {"ok": True}

    @app.get("/health")
    async def health():  # noqa: ANN202 - rota não estrangulada
        return {"status": "ok"}

    return app


async def _get(app: FastAPI, path: str, n: int = 1) -> list[int]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        results = await asyncio.gather(*[c.get(path) for _ in range(n)])
        return sorted(r.status_code for r in results)


def test_backpressure_devolve_429_quando_saturado():
    # Semáforo de 1: com 2 requisições concorrentes lentas, uma passa (200) e a
    # outra é recusada rápido (429).
    app = _make_app(max_concurrent=1, sleep_s=0.4)
    codes = asyncio.run(_get(app, "/slow", n=2))
    assert 200 in codes
    assert 429 in codes


def test_health_nao_e_estrangulado():
    app = _make_app(max_concurrent=1, sleep_s=0.0)
    codes = asyncio.run(_get(app, "/health", n=5))
    assert codes == [200, 200, 200, 200, 200]


def test_timeout_devolve_504(monkeypatch):
    monkeypatch.setenv("REQUEST_TIMEOUT_S", "0.05")
    get_settings.cache_clear()
    try:
        app = _make_app(max_concurrent=10, sleep_s=0.3)  # rota mais lenta que o timeout
        codes = asyncio.run(_get(app, "/slow", n=1))
        assert codes == [504]
    finally:
        get_settings.cache_clear()  # não vazar o env para outros testes
