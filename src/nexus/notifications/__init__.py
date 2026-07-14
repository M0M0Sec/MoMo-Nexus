"""
Notification System.

Provides push notifications via Ntfy.sh and other services.
"""

from nexus.notifications.manager import NotificationManager
from nexus.notifications.ntfy import NtfyClient, NtfyConfig

__all__ = [
    "NtfyClient",
    "NtfyConfig",
    "NotificationManager",
]

