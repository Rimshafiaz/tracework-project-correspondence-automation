import asyncio

from httpx import ASGITransport, AsyncClient

from app.api import health as health_module
from app.main import app


async def get_health():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/health")


def test_health_reports_healthy_database(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "database_is_available", lambda: True)

    response = asyncio.run(get_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_database_failure(monkeypatch) -> None:
    monkeypatch.setattr(health_module, "database_is_available", lambda: False)

    response = asyncio.run(get_health())

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unavailable"}
