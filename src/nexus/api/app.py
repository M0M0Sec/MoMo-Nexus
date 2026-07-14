"""
FastAPI Application.

Main entry point for the Nexus web API.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from nexus._version import __version__
from nexus.config import NexusConfig, get_config

if TYPE_CHECKING:
    from nexus.channels.manager import ChannelManager
    from nexus.core.router import Router
    from nexus.fleet.manager import FleetManager
    from nexus.notifications.manager import NotificationManager

logger = logging.getLogger(__name__)


class NexusAPI:
    """
    Nexus API application wrapper.

    Manages FastAPI app, components, and lifecycle.
    """

    def __init__(
        self,
        config: NexusConfig | None = None,
        router: Router | None = None,
        channel_manager: ChannelManager | None = None,
        fleet_manager: FleetManager | None = None,
        notification_manager: NotificationManager | None = None,
    ) -> None:
        self._config = config or get_config()
        self._router = router
        self._channel_manager = channel_manager
        self._fleet_manager = fleet_manager
        self._notification_manager = notification_manager

        # Generate API key if not configured
        self._api_key = self._config.server.api_key or secrets.token_urlsafe(32)

        # Initialize notification manager if not provided
        if self._notification_manager is None:
            self._notification_manager = self._create_notification_manager()

        # Register notification handler with alert manager
        if self._fleet_manager and self._notification_manager:
            self._fleet_manager.alerts.add_handler(self._notification_manager.handle_alert)

        # Create FastAPI app
        self._app = self._create_app()

    def _create_notification_manager(self) -> NotificationManager:
        """Create and configure notification manager."""
        from nexus.notifications.manager import NotificationManager
        from nexus.notifications.ntfy import NtfyConfig as NtfyClientConfig

        manager = NotificationManager()

        # Configure Ntfy if enabled
        ntfy_cfg = self._config.notifications.ntfy
        if ntfy_cfg.enabled:
            manager.configure_ntfy(NtfyClientConfig(
                enabled=ntfy_cfg.enabled,
                server_url=ntfy_cfg.server_url,
                topic=ntfy_cfg.topic,
                access_token=ntfy_cfg.access_token,
                username=ntfy_cfg.username,
                password=ntfy_cfg.password,
                min_severity=ntfy_cfg.min_severity,
            ))
            logger.info(f"Ntfy notifications enabled: {ntfy_cfg.server_url}/{ntfy_cfg.topic}")

        return manager

    @property
    def app(self) -> FastAPI:
        """Get FastAPI app instance."""
        return self._app

    @property
    def api_key(self) -> str:
        """Get API key."""
        return self._api_key

    def _get_api_description(self) -> str:
        """Generate API description for OpenAPI docs."""
        return """
# MoMo-Nexus API

Central Communication Hub for the MoMo Red Team Ecosystem.

## Overview

Nexus serves as the central hub connecting all MoMo ecosystem devices:

- **MoMo** - Field wardriving device (Pi 5)
- **GhostBridge** - Network implant (NanoPi R2S)
- **Mimic** - USB HID attack platform (Pi Zero 2W)
- **Swarm** - LoRa mesh network (Meshtastic)

## Authentication

All API endpoints require Bearer token authentication:

```
Authorization: Bearer <api_key>
```

## Communication Channels

Nexus supports multiple communication channels with automatic failover:

| Channel | Priority | Use Case |
|---------|----------|----------|
| LoRa | 1 | Offline, long range |
| 4G/LTE | 2 | High bandwidth |
| WiFi | 3 | Local network |
| BLE | 4 | Short range, low power |

## Real-time Updates

WebSocket endpoint available at `/ws` for real-time event streaming.

## Rate Limits

- API: 100 requests/minute per device
- WebSocket: 10 messages/second
- File uploads: 10MB max

---

*MoMo-Nexus - Secure. Stealthy. Synchronized.*
"""

    def _get_openapi_tags(self) -> list[dict]:
        """Define OpenAPI tags for API grouping."""
        return [
            {
                "name": "health",
                "description": "Health check and status endpoints",
            },
            {
                "name": "devices",
                "description": "Device registration and management",
            },
            {
                "name": "sync",
                "description": "Data synchronization from field devices (handshakes, credentials, loot)",
            },
            {
                "name": "cloud",
                "description": "Cloud GPU cracking and Evilginx control",
            },
            {
                "name": "messages",
                "description": "Inter-device messaging and commands",
            },
            {
                "name": "channels",
                "description": "Communication channel status and control",
            },
            {
                "name": "websocket",
                "description": "Real-time WebSocket connections",
            },
            {
                "name": "notifications",
                "description": "Push notification management (Ntfy.sh, etc.)",
            },
        ]

    def _create_app(self) -> FastAPI:
        """Create and configure FastAPI application."""
        app = FastAPI(
            title="MoMo-Nexus API",
            description=self._get_api_description(),
            version=__version__,
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
            openapi_tags=self._get_openapi_tags(),
            license_info={
                "name": "MIT",
                "url": "https://opensource.org/licenses/MIT",
            },
            contact={
                "name": "MoMo Team",
                "url": "https://github.com/momo-team",
            },
        )

        # Store references in app state
        app.state.nexus = self
        app.state.config = self._config
        app.state.router = self._router
        app.state.channel_manager = self._channel_manager
        app.state.fleet_manager = self._fleet_manager
        app.state.notification_manager = self._notification_manager
        app.state.api_key = self._api_key

        # Add CORS middleware
        cors_origins = self._config.server.cors_origins
        wildcard_origins = "*" in cors_origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            # SECURITY: never combine wildcard origins with credentials — that pairing is
            # spec-invalid and unsafe. This API authenticates via the X-API-Key header
            # (not cookies), so CORS "credentials" are not required for wildcard use.
            allow_credentials=not wildcard_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Add exception handler
        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception):
            # SECURITY: log the detail server-side, but do NOT leak internals/tracebacks
            # to the client.
            logger.exception("Unhandled error handling %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"},
            )

        # Import and include routes
        from nexus.api.cloud import cloud_router
        from nexus.api.routes import router as api_router
        from nexus.api.sync import sync_router
        from nexus.api.websocket import router as ws_router

        app.include_router(api_router, prefix="/api")
        app.include_router(sync_router, prefix="/api")
        app.include_router(cloud_router, prefix="/api")
        app.include_router(ws_router)

        # Mount static files for dashboard
        dashboard_path = Path(__file__).parent / "dashboard"
        if dashboard_path.exists():
            app.mount("/", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")

        # Root redirect
        @app.get("/", include_in_schema=False)
        async def root():
            return {"message": "MoMo-Nexus API", "version": __version__, "docs": "/docs"}

        return app

    async def start(self) -> None:
        """Start the API server."""
        import uvicorn

        config = uvicorn.Config(
            app=self._app,
            host=self._config.server.host,
            port=self._config.server.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


def create_app(
    config: NexusConfig | None = None,
    router: Router | None = None,
    channel_manager: ChannelManager | None = None,
    fleet_manager: FleetManager | None = None,
    notification_manager: NotificationManager | None = None,
) -> FastAPI:
    """
    Create FastAPI application.

    Factory function for creating the Nexus API.
    """
    api = NexusAPI(
        config=config,
        router=router,
        channel_manager=channel_manager,
        fleet_manager=fleet_manager,
        notification_manager=notification_manager,
    )
    return api.app

