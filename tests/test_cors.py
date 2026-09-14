"""Tests for browser access from a frontend on another origin.

CORS failures are silent on the server — the request succeeds, and only the browser
refuses to hand the response to your JavaScript. So it is worth asserting.
"""

from app.core.config import Settings

FRONTEND = "http://localhost:5173"


def build_settings(**overrides) -> Settings:
    defaults = {
        "jwt_secret_key": "test-secret",
        "parsebot_hotel_scraper_id": "test-hotel-scraper",
        "parsebot_redbus_scraper_id": "test-redbus-scraper",
    }
    return Settings(**{**defaults, **overrides})


class TestOriginParsing:
    def test_comma_separated_origins_are_split(self):
        settings = build_settings(cors_origins="http://a.com,http://b.com")

        assert settings.cors_origin_list == ["http://a.com", "http://b.com"]

    def test_surrounding_spaces_are_ignored(self):
        settings = build_settings(cors_origins=" http://a.com , http://b.com ")

        assert settings.cors_origin_list == ["http://a.com", "http://b.com"]

    def test_empty_entries_are_dropped(self):
        settings = build_settings(cors_origins="http://a.com,,")

        assert settings.cors_origin_list == ["http://a.com"]

    def test_the_usual_dev_servers_are_allowed_by_default(self):
        allowed = build_settings().cors_origin_list

        assert FRONTEND in allowed
        assert "http://localhost:3000" in allowed


class TestBrowserRequests:
    def test_preflight_is_accepted_from_an_allowed_origin(self, client):
        """The OPTIONS request a browser sends before a cross-origin POST."""
        response = client.options(
            "/chat/ask",
            headers={
                "Origin": FRONTEND,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == FRONTEND

    def test_cookies_are_permitted(self, client):
        """Without this header the browser drops the auth cookie and every call 401s."""
        response = client.options(
            "/chat/ask",
            headers={
                "Origin": FRONTEND,
                "Access-Control-Request-Method": "POST",
            },
        )

        assert response.headers["access-control-allow-credentials"] == "true"

    def test_a_real_response_carries_the_origin_header(self, client):
        response = client.get("/health", headers={"Origin": FRONTEND})

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == FRONTEND

    def test_an_unlisted_origin_is_not_granted_access(self, client):
        """The response still arrives, but without the header the browser blocks it."""
        response = client.get("/health", headers={"Origin": "http://evil.example.com"})

        assert "access-control-allow-origin" not in response.headers

    def test_the_allowed_origin_is_never_a_wildcard(self, client):
        """A wildcard would be rejected by browsers once credentials are involved."""
        response = client.get("/health", headers={"Origin": FRONTEND})

        assert response.headers["access-control-allow-origin"] != "*"
