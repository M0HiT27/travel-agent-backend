"""CORS must allow credentialed requests from the configured frontend origins --
the auth cookie is useless to a React dev server without this."""

from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_a_configured_origin_with_credentials():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_an_unconfigured_origin():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_allows_post_with_content_type():
    with TestClient(app) as client:
        response = client.options(
            "/chat/",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
