"""
Command Dispatcher.

Sends commands to devices and handles responses.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from nexus.config import NexusConfig, get_config
from nexus.core.events import EventBus, get_event_bus
from nexus.domain.enums import MessageType, Priority
from nexus.domain.models import Command, CommandResult, Message

if TYPE_CHECKING:
    from nexus.core.router import Router
    from nexus.fleet.registry import DeviceRegistry

logger = logging.getLogger(__name__)


class CommandStatus(str, Enum):
    """Command execution status."""

    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class PendingCommand:
    """Tracks a pending command."""

    command: Command
    status: CommandStatus = CommandStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    result: CommandResult | None = None
    future: asyncio.Future | None = None


class CommandDispatcher:
    """
    Dispatches commands to devices.

    Responsibilities:
    - Send commands to devices
    - Track command status
    - Handle command results
    - Timeout handling
    """

    def __init__(
        self,
        router: Router,
        registry: DeviceRegistry,
        config: NexusConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._router = router
        self._registry = registry
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()

        # Pending commands: command_id -> PendingCommand
        self._pending: dict[str, PendingCommand] = {}
        self._lock = asyncio.Lock()

        # Default timeout from config
        self._default_timeout = self._config.fleet.command_timeout

        # Command history (for stats)
        self._history: list[PendingCommand] = []
        self._max_history = 1000

    # =========================================================================
    # Command Sending
    # =========================================================================

    async def dispatch(
        self,
        device_id: str,
        cmd: str,
        params: dict[str, Any] | None = None,
        priority: Priority = Priority.HIGH,
        timeout: float | None = None,
        wait: bool = True,
    ) -> CommandResult:
        """
        Dispatch a command to a device.

        Args:
            device_id: Target device
            cmd: Command name
            params: Command parameters
            priority: Message priority
            timeout: Timeout in seconds
            wait: Whether to wait for result

        Returns:
            CommandResult with success/failure
        """
        # Check device exists
        device = await self._registry.get(device_id)
        if not device:
            return CommandResult(
                command_id="",
                device_id=device_id,
                success=False,
                error="Device not found",
            )

        # Create command
        command = Command(
            device_id=device_id,
            cmd=cmd,
            params=params or {},
            priority=priority,
            timeout=timeout or self._default_timeout,
        )

        # Create pending entry
        pending = PendingCommand(
            command=command,
            status=CommandStatus.PENDING,
        )

        if wait:
            pending.future = asyncio.Future()

        async with self._lock:
            self._pending[command.id] = pending

        # Create message
        message = Message(
            id=command.id,
            src="nexus",
            dst=device_id,
            type=MessageType.COMMAND,
            pri=priority,
            ack_required=True,
            data={
                "cmd": cmd,
                "id": command.id,
                "params": params or {},
                "timeout": command.timeout,
            },
        )

        # Send message
        try:
            result = await self._router.route(message)

            if result.success:
                pending.status = CommandStatus.SENT
                pending.sent_at = datetime.now()
                logger.info(f"Command sent: {cmd} -> {device_id}")
            else:
                pending.status = CommandStatus.FAILED
                pending.result = CommandResult(
                    command_id=command.id,
                    device_id=device_id,
                    success=False,
                    error="Failed to send command",
                )

                if pending.future and not pending.future.done():
                    pending.future.set_result(pending.result)

                # Send failed → no response will ever arrive; move out of _pending
                # so it does not leak (previously only the wait-branch cleaned up).
                await self._complete_command(command.id)
                return pending.result

        except Exception as e:
            logger.error(f"Command dispatch failed: {e}")
            pending.status = CommandStatus.FAILED
            pending.result = CommandResult(
                command_id=command.id,
                device_id=device_id,
                success=False,
                error=str(e),
            )
            await self._complete_command(command.id)  # don't leak on error
            return pending.result

        # Wait for result if requested
        if wait and pending.future:
            try:
                result = await asyncio.wait_for(
                    pending.future,
                    timeout=command.timeout,
                )
                return result

            except TimeoutError:
                pending.status = CommandStatus.TIMEOUT
                pending.result = CommandResult(
                    command_id=command.id,
                    device_id=device_id,
                    success=False,
                    error="Command timeout",
                )
                return pending.result

            finally:
                # Move to history
                await self._complete_command(command.id)

        # Not waiting
        return CommandResult(
            command_id=command.id,
            device_id=device_id,
            success=True,
            pending=True,
        )

    async def dispatch_broadcast(
        self,
        cmd: str,
        params: dict[str, Any] | None = None,
        device_type: str | None = None,
    ) -> dict[str, CommandResult]:
        """
        Dispatch command to multiple devices.

        Args:
            cmd: Command name
            params: Command parameters
            device_type: Filter by device type

        Returns:
            Dict of device_id -> CommandResult
        """
        from nexus.domain.enums import DeviceType

        if device_type:
            devices = await self._registry.get_by_type(DeviceType(device_type))
        else:
            devices = await self._registry.get_online()

        results = {}
        tasks = []

        for device in devices:
            task = asyncio.create_task(
                self.dispatch(device.id, cmd, params, wait=True)
            )
            tasks.append((device.id, task))

        for device_id, task in tasks:
            try:
                results[device_id] = await task
            except Exception as e:
                results[device_id] = CommandResult(
                    command_id="",
                    device_id=device_id,
                    success=False,
                    error=str(e),
                )

        return results

    # =========================================================================
    # Result Handling
    # =========================================================================

    async def handle_result(self, message: Message) -> None:
        """
        Handle command result from device.

        Args:
            message: RESULT message
        """
        data = message.data
        cmd_id = data.get("cmd_id") or data.get("id")

        if not cmd_id:
            logger.warning("Result message missing command ID")
            return

        async with self._lock:
            pending = self._pending.get(cmd_id)

        if not pending:
            logger.warning(f"Result for unknown command: {cmd_id}")
            return

        # Create result
        result = CommandResult(
            command_id=cmd_id,
            device_id=message.src,
            success=data.get("status") == "success" or data.get("success", False),
            error=data.get("error"),
            data=data.get("data", {}),
            duration_ms=data.get("duration"),
        )

        pending.status = CommandStatus.COMPLETED
        pending.completed_at = datetime.now()
        pending.result = result

        # Resolve future if waiting
        if pending.future and not pending.future.done():
            pending.future.set_result(result)

        logger.info(
            f"Command completed: {pending.command.cmd} "
            f"({result.success}, {result.duration_ms}ms)"
        )

        await self._complete_command(cmd_id)

    async def _complete_command(self, command_id: str) -> None:
        """Move command to history."""
        async with self._lock:
            pending = self._pending.pop(command_id, None)
            if pending:
                self._history.append(pending)

                # Trim history
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]

    async def sweep_expired(self, grace_seconds: float = 5.0) -> int:
        """Time out fire-and-forget (wait=False) commands whose response never arrived.

        Without this, a dispatched command that gets no reply lingers in `_pending`
        forever. Call this periodically. Returns the number of commands swept.
        """
        now = datetime.now()
        expired: list[str] = []
        async with self._lock:
            for cmd_id, pending in self._pending.items():
                age = (now - pending.created_at).total_seconds()
                if age > pending.command.timeout + grace_seconds:
                    pending.status = CommandStatus.TIMEOUT
                    if pending.future and not pending.future.done():
                        pending.future.set_result(
                            CommandResult(
                                command_id=cmd_id,
                                device_id=pending.command.device_id,
                                success=False,
                                error="Command timeout (swept)",
                            )
                        )
                    expired.append(cmd_id)

        for cmd_id in expired:
            await self._complete_command(cmd_id)
        return len(expired)

    # =========================================================================
    # Command Queries
    # =========================================================================

    async def get_pending(self, device_id: str | None = None) -> list[PendingCommand]:
        """Get pending commands."""
        async with self._lock:
            commands = list(self._pending.values())

        if device_id:
            commands = [c for c in commands if c.command.device_id == device_id]

        return commands

    async def get_status(self, command_id: str) -> CommandStatus | None:
        """Get command status."""
        async with self._lock:
            pending = self._pending.get(command_id)
            if pending:
                return pending.status

            # Check history
            for cmd in self._history:
                if cmd.command.id == command_id:
                    return cmd.status

        return None

    async def cancel(self, command_id: str) -> bool:
        """Cancel a pending command."""
        async with self._lock:
            pending = self._pending.get(command_id)
            if not pending:
                return False

            pending.status = CommandStatus.CANCELLED
            if pending.future and not pending.future.done():
                pending.future.cancel()

            del self._pending[command_id]
            self._history.append(pending)

        logger.info(f"Command cancelled: {command_id}")
        return True

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """Get command statistics."""
        async with self._lock:
            pending = list(self._pending.values())
            history = list(self._history)

        completed = [c for c in history if c.status == CommandStatus.COMPLETED]
        failed = [c for c in history if c.status in (CommandStatus.FAILED, CommandStatus.TIMEOUT)]

        avg_duration = 0
        if completed:
            durations = [
                c.result.duration_ms
                for c in completed
                if c.result and c.result.duration_ms
            ]
            if durations:
                avg_duration = sum(durations) / len(durations)

        return {
            "pending": len(pending),
            "completed": len(completed),
            "failed": len(failed),
            "total_history": len(history),
            "success_rate": len(completed) / len(history) * 100 if history else 0,
            "avg_duration_ms": avg_duration,
        }

