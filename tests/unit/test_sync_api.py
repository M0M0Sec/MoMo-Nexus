"""
Unit tests for Sync API.

Tests the sync endpoints and storage.
"""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.api.sync import (
    CrackResultUpload,
    CredentialUpload,
    DeviceStatusUpdate,
    GhostBeacon,
    HandshakeResponse,
    HandshakeUpload,
    LootUpload,
    MimicTrigger,
    SyncStorage,
)


class TestHandshakeUpload:
    """Tests for HandshakeUpload model."""

    def test_basic_upload(self):
        """Test basic handshake upload."""
        upload = HandshakeUpload(
            device_id="momo-001",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
            channel=6,
        )

        assert upload.device_id == "momo-001"
        assert upload.ssid == "TestWiFi"
        assert upload.bssid == "AA:BB:CC:DD:EE:FF"
        assert upload.channel == 6
        assert upload.capture_type == "4way"

    def test_upload_with_data(self):
        """Test handshake upload with capture data."""
        capture_data = base64.b64encode(b"fake capture data").decode()

        upload = HandshakeUpload(
            device_id="momo-001",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
            channel=11,
            capture_type="pmkid",
            data=capture_data,
        )

        assert upload.capture_type == "pmkid"
        assert upload.data == capture_data

    def test_upload_with_metadata(self):
        """Test handshake upload with all metadata."""
        upload = HandshakeUpload(
            device_id="momo-001",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
            channel=6,
            signal_strength=-65,
            client_mac="11:22:33:44:55:66",
            gps=[41.015, 28.979],
        )

        assert upload.signal_strength == -65
        assert upload.client_mac == "11:22:33:44:55:66"
        assert upload.gps == [41.015, 28.979]


class TestCredentialUpload:
    """Tests for CredentialUpload model."""

    def test_captive_credential(self):
        """Test captive portal credential."""
        upload = CredentialUpload(
            device_id="momo-001",
            ssid="FakeWiFi",
            client_mac="AA:BB:CC:DD:EE:FF",
            capture_type="captive",
            username="user@example.com",
            password="secret123",
        )

        assert upload.capture_type == "captive"
        assert upload.username == "user@example.com"
        assert upload.password == "secret123"

    def test_eap_credential(self):
        """Test EAP/enterprise credential."""
        upload = CredentialUpload(
            device_id="momo-001",
            ssid="CorpWiFi",
            client_mac="AA:BB:CC:DD:EE:FF",
            capture_type="wpa_enterprise",
            username="jdoe",
            password="corppass",
            domain="CORP",
        )

        assert upload.capture_type == "wpa_enterprise"
        assert upload.domain == "CORP"


class TestCrackResultUpload:
    """Tests for CrackResultUpload model."""

    def test_successful_crack(self):
        """Test successful crack result."""
        result = CrackResultUpload(
            device_id="momo-001",
            handshake_id="hs_abc123",
            success=True,
            password="cracked123",
            duration_seconds=3600,
            method="john",
            wordlist="rockyou.txt",
        )

        assert result.success is True
        assert result.password == "cracked123"
        assert result.method == "john"

    def test_failed_crack(self):
        """Test failed crack result."""
        result = CrackResultUpload(
            device_id="momo-001",
            handshake_id="hs_abc123",
            success=False,
            method="john",
        )

        assert result.success is False
        assert result.password is None


class TestLootUpload:
    """Tests for LootUpload model."""

    def test_text_loot(self):
        """Test text loot upload."""
        loot = LootUpload(
            device_id="momo-001",
            loot_type="text",
            name="passwords.txt",
            text="user1:pass1\nuser2:pass2",
            tags=["passwords", "credentials"],
        )

        assert loot.loot_type == "text"
        assert loot.text is not None
        assert "passwords" in loot.tags

    def test_binary_loot(self):
        """Test binary loot upload."""
        binary_data = base64.b64encode(b"\x00\x01\x02\x03").decode()

        loot = LootUpload(
            device_id="momo-001",
            loot_type="binary",
            name="capture.pcap",
            data=binary_data,
            source="tcpdump",
        )

        assert loot.loot_type == "binary"
        assert loot.data == binary_data
        assert loot.source == "tcpdump"


class TestDeviceStatusUpdate:
    """Tests for DeviceStatusUpdate model."""

    def test_full_status(self):
        """Test full status update."""
        status = DeviceStatusUpdate(
            device_id="momo-001",
            battery=85,
            temperature=45,
            uptime=3600,
            disk_free=1024,
            memory_free=512,
            aps_seen=25,
            handshakes_captured=3,
            clients_seen=50,
            gps=[41.015, 28.979],
            mode="passive",
            current_target="TargetWiFi",
        )

        assert status.battery == 85
        assert status.temperature == 45
        assert status.mode == "passive"

    def test_minimal_status(self):
        """Test minimal status update."""
        status = DeviceStatusUpdate(
            device_id="momo-001",
            battery=50,
        )

        assert status.device_id == "momo-001"
        assert status.battery == 50
        assert status.temperature is None


class TestGhostBeacon:
    """Tests for GhostBeacon model."""

    def test_beacon(self):
        """Test GhostBridge beacon."""
        beacon = GhostBeacon(
            device_id="ghost-001",
            tunnel_status="up",
            internal_ip="192.168.1.100",
            external_ip="1.2.3.4",
            gateway_mac="AA:BB:CC:DD:EE:FF",
            bytes_in=1024000,
            bytes_out=512000,
            uptime=7200,
        )

        assert beacon.tunnel_status == "up"
        assert beacon.internal_ip == "192.168.1.100"


class TestMimicTrigger:
    """Tests for MimicTrigger model."""

    def test_trigger(self):
        """Test Mimic trigger event."""
        trigger = MimicTrigger(
            device_id="mimic-001",
            trigger_type="usb_insert",
            payload_name="reverse_shell.js",
            target_os="windows",
            success=True,
            execution_time_ms=1500,
            output="Shell connected",
        )

        assert trigger.trigger_type == "usb_insert"
        assert trigger.success is True


class TestSyncStorage:
    """Tests for SyncStorage class."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create storage with temp path."""
        return SyncStorage(str(tmp_path / "sync_data"))

    @pytest.mark.asyncio
    async def test_save_handshake(self, storage):
        """Test saving handshake."""
        upload = HandshakeUpload(
            device_id="momo-001",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
            channel=6,
        )

        hs_id = await storage.save_handshake(upload)

        assert hs_id.startswith("hs_")
        assert (storage.base_path / "handshakes" / hs_id / "meta.json").exists()

    @pytest.mark.asyncio
    async def test_save_handshake_with_data(self, storage):
        """Test saving handshake with capture data."""
        capture_data = base64.b64encode(b"fake capture data").decode()

        upload = HandshakeUpload(
            device_id="momo-001",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
            channel=6,
            data=capture_data,
        )

        hs_id = await storage.save_handshake(upload)

        # Check capture file exists
        hs_dir = storage.base_path / "handshakes" / hs_id
        assert (hs_dir / "capture.cap").exists()

    @pytest.mark.asyncio
    async def test_save_credential(self, storage):
        """Test saving credential."""
        upload = CredentialUpload(
            device_id="momo-001",
            ssid="FakeWiFi",
            client_mac="AA:BB:CC:DD:EE:FF",
            username="user@example.com",
            password="secret123",
        )

        cred_id = await storage.save_credential(upload)

        assert cred_id.startswith("cred_")
        assert (storage.base_path / "credentials" / f"{cred_id}.json").exists()

    @pytest.mark.asyncio
    async def test_save_loot_text(self, storage):
        """Test saving text loot."""
        upload = LootUpload(
            device_id="momo-001",
            loot_type="text",
            name="test.txt",
            text="Hello World",
        )

        loot_id = await storage.save_loot(upload)

        assert loot_id.startswith("loot_")
        loot_dir = storage.base_path / "loot" / loot_id
        assert (loot_dir / "meta.json").exists()
        assert (loot_dir / "test.txt").exists()

    @pytest.mark.asyncio
    async def test_save_loot_binary(self, storage):
        """Test saving binary loot."""
        binary_data = base64.b64encode(b"\x00\x01\x02\x03").decode()

        upload = LootUpload(
            device_id="momo-001",
            loot_type="binary",
            name="data.bin",
            data=binary_data,
        )

        loot_id = await storage.save_loot(upload)

        loot_dir = storage.base_path / "loot" / loot_id
        assert (loot_dir / "data.bin").exists()

        # Verify binary content
        content = (loot_dir / "data.bin").read_bytes()
        assert content == b"\x00\x01\x02\x03"

    @pytest.mark.asyncio
    async def test_update_status(self, storage):
        """Test updating device status."""
        status = DeviceStatusUpdate(
            device_id="momo-001",
            battery=85,
            temperature=45,
        )

        await storage.update_status(status)

        status_file = storage.base_path / "status" / "momo-001.json"
        assert status_file.exists()

        with open(status_file) as f:
            data = json.load(f)

        assert data["battery"] == 85
        assert data["temperature"] == 45

    def test_generate_id(self, storage):
        """Test ID generation."""
        id1 = storage.generate_id("hs", "test1")
        id2 = storage.generate_id("hs", "test2")

        assert id1.startswith("hs_")
        assert id2.startswith("hs_")
        assert id1 != id2  # Different data = different ID
        assert len(id1) == 15  # hs_ + 12 chars

