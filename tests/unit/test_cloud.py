"""
Unit tests for Cloud integration.

Tests the Hashcat and Evilginx cloud clients.
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from nexus.cloud.evilginx import (
    EvilginxClient,
    EvilginxConfig,
    Lure,
    Phishlet,
    PhishletStatus,
    Session,
)
from nexus.cloud.hashcat import (
    CloudConfig,
    CrackJob,
    CrackResult,
    HashcatCloudClient,
    HashType,
    JobStatus,
)
from nexus.cloud.manager import CloudManager, CloudManagerConfig


class TestCrackJob:
    """Tests for CrackJob model."""

    def test_create_job(self):
        """Test job creation."""
        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="test_hash_data",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
        )

        assert job.hash_type == HashType.WPA_PMKID
        assert job.ssid == "TestWiFi"
        assert job.status == JobStatus.PENDING

    def test_job_to_dict(self):
        """Test job serialization."""
        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
        )

        d = job.to_dict()

        assert d["hash_type"] == 22000
        assert d["ssid"] == "TestWiFi"
        assert d["status"] == "pending"


class TestCrackResult:
    """Tests for CrackResult model."""

    def test_successful_result(self):
        """Test successful crack result."""
        result = CrackResult(
            job_id="abc123",
            success=True,
            password="cracked123",
            duration_seconds=3600,
            hashes_tried=1000000,
        )

        assert result.success is True
        assert result.password == "cracked123"

    def test_failed_result(self):
        """Test failed crack result."""
        result = CrackResult(
            job_id="abc123",
            success=False,
            error="Password not in wordlist",
        )

        assert result.success is False
        assert result.error is not None


class TestHashcatCloudClient:
    """Tests for HashcatCloudClient."""

    @pytest.fixture
    def client(self):
        """Create client with mock mode."""
        config = CloudConfig(enabled=True)
        return HashcatCloudClient(config)

    @pytest.mark.asyncio
    async def test_connect_mock(self, client):
        """Test connection (mock mode)."""
        connected = await client.connect()

        assert connected is True
        assert client.is_connected is True
        assert client.is_mock is True

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_submit_job(self, client):
        """Test job submission."""
        await client.connect()

        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="WPA*02*abc123*...",
            ssid="TestWiFi",
            bssid="AA:BB:CC:DD:EE:FF",
        )

        result = await client.submit_job(job)

        assert result.status in (JobStatus.QUEUED, JobStatus.RUNNING)

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_get_job_status(self, client):
        """Test getting job status."""
        await client.connect()

        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="WPA*02*abc123*...",
            ssid="TestWiFi",
        )

        submitted = await client.submit_job(job)

        # Wait a bit for mock to progress
        await asyncio.sleep(1)

        status = await client.get_job_status(submitted.id)

        assert status is not None
        assert status.progress >= 0

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_wait_for_result(self, client):
        """Test waiting for result."""
        await client.connect()

        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="WPA*02*abc123*...",
            ssid="TestWiFi",
        )

        await client.submit_job(job)

        result = await client.wait_for_result(job.id, poll_interval=0.5, timeout=10)

        assert result is not None
        assert isinstance(result, CrackResult)

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_list_jobs(self, client):
        """Test listing jobs."""
        await client.connect()

        # Submit a job
        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="test",
            ssid="Test1",
        )
        await client.submit_job(job)

        jobs = await client.list_jobs()

        assert len(jobs) >= 1

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_cancel_job(self, client):
        """Test cancelling a job."""
        await client.connect()

        job = CrackJob(
            hash_type=HashType.WPA_PMKID,
            hash_data="test",
            ssid="Test1",
        )
        submitted = await client.submit_job(job)

        cancelled = await client.cancel_job(submitted.id)

        assert cancelled is True

        status = await client.get_job_status(submitted.id)
        assert status.status == JobStatus.CANCELLED

        await client.disconnect()


class TestPhishlet:
    """Tests for Phishlet model."""

    def test_create_phishlet(self):
        """Test phishlet creation."""
        phishlet = Phishlet(
            name="outlook",
            status=PhishletStatus.ENABLED,
            hostname="outlook.example.com",
        )

        assert phishlet.name == "outlook"
        assert phishlet.status == PhishletStatus.ENABLED

    def test_phishlet_to_dict(self):
        """Test phishlet serialization."""
        phishlet = Phishlet(
            name="gmail",
            visits=100,
            captures=5,
        )

        d = phishlet.to_dict()

        assert d["name"] == "gmail"
        assert d["visits"] == 100
        assert d["captures"] == 5


class TestLure:
    """Tests for Lure model."""

    def test_create_lure(self):
        """Test lure creation."""
        lure = Lure(
            phishlet="outlook",
            path="/login",
            campaign="test_campaign",
        )

        assert lure.phishlet == "outlook"
        assert lure.campaign == "test_campaign"


class TestSession:
    """Tests for Session model."""

    def test_create_session(self):
        """Test session creation."""
        session = Session(
            phishlet="outlook",
            username="user@example.com",
            password="secret123",
            cookies=[{"name": "session", "value": "abc123"}],
        )

        assert session.username == "user@example.com"
        assert len(session.cookies) == 1

    def test_get_cookie_string(self):
        """Test cookie string generation."""
        session = Session(
            phishlet="outlook",
            cookies=[
                {"name": "session", "value": "abc123"},
                {"name": "auth", "value": "xyz789"},
            ],
        )

        cookie_str = session.get_cookie_string()

        assert "session=abc123" in cookie_str
        assert "auth=xyz789" in cookie_str


class TestEvilginxClient:
    """Tests for EvilginxClient."""

    @pytest.fixture
    def client(self):
        """Create client with mock mode."""
        config = EvilginxConfig(
            enabled=True,
            domain="example.com",
        )
        return EvilginxClient(config)

    @pytest.mark.asyncio
    async def test_connect_mock(self, client):
        """Test connection (mock mode)."""
        connected = await client.connect()

        assert connected is True
        assert client.is_connected is True
        assert client.is_mock is True

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_list_phishlets(self, client):
        """Test listing phishlets."""
        await client.connect()

        phishlets = await client.list_phishlets()

        assert len(phishlets) > 0
        assert any(p.name == "outlook" for p in phishlets)

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_enable_phishlet(self, client):
        """Test enabling a phishlet."""
        await client.connect()

        phishlet = await client.enable_phishlet("outlook")

        assert phishlet is not None
        assert phishlet.status == PhishletStatus.ENABLED
        assert phishlet.hostname == "outlook.example.com"

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_disable_phishlet(self, client):
        """Test disabling a phishlet."""
        await client.connect()

        await client.enable_phishlet("outlook")
        success = await client.disable_phishlet("outlook")

        assert success is True

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_create_lure(self, client):
        """Test creating a lure."""
        await client.connect()

        # Enable phishlet first
        await client.enable_phishlet("outlook")

        lure = await client.create_lure("outlook", campaign="test")

        assert lure is not None
        assert lure.phishlet == "outlook"
        assert lure.url.startswith("https://")

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_list_lures(self, client):
        """Test listing lures."""
        await client.connect()

        await client.enable_phishlet("outlook")
        await client.create_lure("outlook")

        lures = await client.list_lures()

        assert len(lures) >= 1

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_delete_lure(self, client):
        """Test deleting a lure."""
        await client.connect()

        await client.enable_phishlet("outlook")
        lure = await client.create_lure("outlook")

        success = await client.delete_lure(lure.id)

        assert success is True

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_simulate_capture(self, client):
        """Test simulating a capture."""
        await client.connect()

        session = await client._simulate_capture(
            phishlet="outlook",
            username="victim@example.com",
            password="secret123",
        )

        assert session.username == "victim@example.com"
        assert len(session.cookies) > 0

        # Should appear in sessions
        sessions = await client.get_sessions()
        assert len(sessions) >= 1

        await client.disconnect()


class TestCloudManager:
    """Tests for CloudManager."""

    @pytest.fixture
    def manager(self):
        """Create manager with mock configs."""
        config = CloudManagerConfig(
            hashcat=CloudConfig(enabled=True),
            evilginx=EvilginxConfig(enabled=True, domain="example.com"),
        )
        return CloudManager(config)

    @pytest.mark.asyncio
    async def test_start_stop(self, manager):
        """Test manager lifecycle."""
        started = await manager.start()

        assert started is True
        assert manager.is_running is True

        await manager.stop()

        assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_hashcat_available(self, manager):
        """Test Hashcat availability."""
        await manager.start()

        assert manager.hashcat_available is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_evilginx_available(self, manager):
        """Test Evilginx availability."""
        await manager.start()

        assert manager.evilginx_available is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_stats(self, manager):
        """Test getting stats."""
        await manager.start()

        stats = await manager.get_stats()

        assert "hashcat" in stats
        assert "evilginx" in stats
        assert stats["hashcat"]["available"] is True
        assert stats["evilginx"]["available"] is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_create_phishing_lure(self, manager):
        """Test creating phishing lure via manager."""
        await manager.start()

        # Enable phishlet first
        await manager.enable_phishlet("outlook")

        lure = await manager.create_phishing_lure("outlook", campaign="test")

        assert lure is not None
        assert lure.url.startswith("https://")

        await manager.stop()

    @pytest.mark.asyncio
    async def test_context_manager(self, manager):
        """Test async context manager."""
        async with manager:
            assert manager.is_running is True

        assert manager.is_running is False


class TestHashType:
    """Tests for HashType enum."""

    def test_wpa_types(self):
        """Test WPA hash types."""
        assert HashType.WPA_PMKID.value == 22000
        assert HashType.WPA_EAPOL.value == 22001
        assert HashType.WPA2.value == 2500

    def test_other_types(self):
        """Test other hash types."""
        assert HashType.NTLM.value == 1000
        assert HashType.MD5.value == 0
        assert HashType.SHA256.value == 1400


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_statuses(self):
        """Test all status values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"
        assert JobStatus.CANCELLED.value == "cancelled"


class TestPhishletStatus:
    """Tests for PhishletStatus enum."""

    def test_statuses(self):
        """Test all status values."""
        assert PhishletStatus.DISABLED.value == "disabled"
        assert PhishletStatus.ENABLED.value == "enabled"
        assert PhishletStatus.PAUSED.value == "paused"

