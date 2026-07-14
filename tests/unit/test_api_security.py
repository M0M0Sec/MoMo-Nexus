"""API security tests (remediation plan Faz 1: CORS, WS auth, exception leak)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from nexus.api.app import create_app
from nexus.config import NexusConfig


def _make_client(cors_origins=None, auth_enabled=True, api_key="testkey123"):
    config = NexusConfig()
    config.server.auth_enabled = auth_enabled
    config.server.api_key = api_key
    if cors_origins is not None:
        config.server.cors_origins = cors_origins
    app = create_app(config)
    return TestClient(app, raise_server_exceptions=False)


class TestCors:
    def test_wildcard_origin_does_not_allow_credentials(self):
        """1.1: `*` origins must NOT be paired with allow_credentials=true."""
        client = _make_client(cors_origins=["*"])
        resp = client.get("/", headers={"Origin": "http://evil.example.com"})
        # Starlette only echoes the credentials header when it is enabled.
        assert resp.headers.get("access-control-allow-credentials") != "true"

    def test_explicit_origin_allows_credentials(self):
        """With explicit origins, credentials may be enabled."""
        client = _make_client(cors_origins=["http://localhost:5173"])
        resp = client.get(
            "/",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"


class TestExceptionHandler:
    def test_500_does_not_leak_internal_detail(self):
        """1.3: the global handler must not return exception text to the client."""
        config = NexusConfig()
        config.server.auth_enabled = False
        app = create_app(config)

        # Drop the catch-all static dashboard mount (if present) so the test route is
        # reachable — the "/" mount otherwise shadows all routes (tracked as finding 1.6).
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "name", "") != "dashboard"
        ]

        @app.get("/_boom")
        async def _boom():
            raise RuntimeError("super secret internal detail")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/_boom")
        assert resp.status_code == 500
        assert "super secret internal detail" not in resp.text
        assert "detail" not in resp.json()


class TestWebSocketAuth:
    def test_ws_rejects_missing_and_wrong_key(self):
        """1.2: WS auth rejects missing/invalid keys (now via constant-time compare)."""
        client = _make_client(auth_enabled=True, api_key="rightkey")

        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pass  # no key → server closes

        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "/ws?api_key=wrongkey"
        ):
            pass

    def test_ws_accepts_correct_key(self):
        client = _make_client(auth_enabled=True, api_key="rightkey")
        with client.websocket_connect("/ws?api_key=rightkey") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
