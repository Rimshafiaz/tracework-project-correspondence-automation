import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app


def _preflight(origin: str):
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.options(
                "/health",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )

    return asyncio.run(request())


def test_configured_local_frontend_origin_is_allowed() -> None:
    response = _preflight("http://localhost:5173")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )


def test_unconfigured_origin_is_not_allowed() -> None:
    response = _preflight("https://untrusted.example")

    assert "access-control-allow-origin" not in response.headers
