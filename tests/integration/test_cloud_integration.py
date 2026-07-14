"""
Integration tests for Cloud API - Hashcat and Evilginx remote operations.

Tests the full flow of Nexus proxying requests to cloud services.

NOTE: These tests are skipped because Cloud API endpoints are not yet implemented.
Cloud API will be implemented in Phase 3 of the project.
"""

import asyncio
import base64
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests in this module - Cloud API not yet implemented
pytestmark = pytest.mark.skip(reason="Cloud API endpoints not yet implemented - Phase 3")

from fastapi.testclient import TestClient

from nexus.api.app import create_app
from nexus.cloud import (
    CloudManager,
    CrackJob,
    CrackResult,
    EvilginxClient,
    HashcatCloudClient,
    HashType,
    JobStatus,
    Lure,
    Phishlet,
    PhishletStatus,
    Session,
)
from nexus.config import NexusConfig


class TestCloudAPIIntegration:
    """Integration tests for Cloud API endpoints."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-cloud-test",
            name="Cloud Test Nexus",
            database={"path": str(tmp_path / "cloud.db")},
            server={"enabled": True, "host": "127.0.0.1", "port": 8080},
            security={"api_key": "cloud-test-key"},
            cloud={
                "hashcat": {
                    "enabled": True,
                    "api_url": "https://gpu.example.com",
                    "api_key": "hashcat-key",
                },
                "evilginx": {
                    "enabled": True,
                    "api_url": "https://phish.example.com",
                    "api_key": "evilginx-key",
                },
            },
        )

    @pytest.fixture
    def mock_cloud_manager(self):
        """Create mock cloud manager."""
        manager = MagicMock(spec=CloudManager)

        # Hashcat mocks
        manager.submit_crack_job = AsyncMock(return_value=CrackJob(
            id="job-001",
            hash_value="test-hash",
            hash_type=HashType.WPA2,
            status=JobStatus.QUEUED,
            created_at=datetime.now(),
        ))
        manager.get_job_status = AsyncMock(return_value=CrackJob(
            id="job-001",
            hash_value="test-hash",
            hash_type=HashType.WPA2,
            status=JobStatus.RUNNING,
            progress=45,
            created_at=datetime.now(),
        ))
        manager.get_job_result = AsyncMock(return_value=CrackResult(
            job_id="job-001",
            success=True,
            password="cracked123",
            hash_type=HashType.WPA2,
            duration_seconds=120,
            completed_at=datetime.now(),
        ))
        manager.cancel_job = AsyncMock(return_value=True)
        manager.list_jobs = AsyncMock(return_value=[
            CrackJob(id="job-001", hash_value="h1", hash_type=HashType.WPA2,
                    status=JobStatus.COMPLETED, created_at=datetime.now()),
            CrackJob(id="job-002", hash_value="h2", hash_type=HashType.NTLM,
                    status=JobStatus.RUNNING, created_at=datetime.now()),
        ])

        # Evilginx mocks
        manager.list_phishlets = AsyncMock(return_value=[
            Phishlet(name="o365", status=PhishletStatus.ENABLED, hostname="login.example.com"),
            Phishlet(name="google", status=PhishletStatus.DISABLED, hostname=None),
        ])
        manager.enable_phishlet = AsyncMock(return_value=True)
        manager.disable_phishlet = AsyncMock(return_value=True)
        manager.create_lure = AsyncMock(return_value=Lure(
            id="lure-001",
            phishlet="o365",
            path="/login",
            redirect_url="https://microsoft.com",
            url="https://login.example.com/login",
        ))
        manager.list_sessions = AsyncMock(return_value=[
            Session(
                id="sess-001",
                phishlet="o365",
                username="victim@corp.com",
                password="Summer2024!",
                tokens={"access_token": "eyJ..."},
                ip="1.2.3.4",
                user_agent="Mozilla/5.0",
                captured_at=datetime.now(),
            ),
        ])

        return manager

    @pytest.fixture
    def client(self, config: NexusConfig, mock_cloud_manager) -> TestClient:
        """Create test client with mocked cloud manager."""
        app = create_app(config)
        app.state.cloud_manager = mock_cloud_manager
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self) -> dict:
        """Get authorization headers."""
        return {"Authorization": "Bearer cloud-test-key"}

    # ========== Hashcat API Tests ==========

    def test_submit_crack_job(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test submitting a cracking job."""
        payload = {
            "hash_value": "d033e22ae348aeb5660fc2140aec35850c4da997",
            "hash_type": "WPA2",
            "wordlist": "rockyou.txt",
            "rules": ["best64"],
            "metadata": {"ssid": "TargetWiFi"},
        }

        response = client.post("/api/cloud/hashcat/jobs", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "job-001"
        assert data["status"] == "QUEUED"
        mock_cloud_manager.submit_crack_job.assert_called_once()

    def test_get_job_status(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test getting job status."""
        response = client.get("/api/cloud/hashcat/jobs/job-001", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "job-001"
        assert data["status"] == "RUNNING"
        assert data["progress"] == 45

    def test_get_job_result(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test getting completed job result."""
        response = client.get("/api/cloud/hashcat/jobs/job-001/result", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["password"] == "cracked123"

    def test_cancel_job(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test cancelling a job."""
        response = client.delete("/api/cloud/hashcat/jobs/job-001", headers=auth_headers)

        assert response.status_code == 200
        mock_cloud_manager.cancel_job.assert_called_once_with("job-001")

    def test_list_jobs(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test listing all jobs."""
        response = client.get("/api/cloud/hashcat/jobs", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "job-001"
        assert data[1]["status"] == "RUNNING"

    # ========== Evilginx API Tests ==========

    def test_list_phishlets(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test listing phishlets."""
        response = client.get("/api/cloud/evilginx/phishlets", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "o365"
        assert data[0]["status"] == "ENABLED"

    def test_enable_phishlet(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test enabling a phishlet."""
        payload = {"hostname": "login.target.com"}

        response = client.post(
            "/api/cloud/evilginx/phishlets/google/enable",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 200
        mock_cloud_manager.enable_phishlet.assert_called_once()

    def test_disable_phishlet(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test disabling a phishlet."""
        response = client.post(
            "/api/cloud/evilginx/phishlets/o365/disable",
            headers=auth_headers,
        )

        assert response.status_code == 200
        mock_cloud_manager.disable_phishlet.assert_called_once()

    def test_create_lure(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test creating a lure."""
        payload = {
            "phishlet": "o365",
            "path": "/secure-login",
            "redirect_url": "https://microsoft.com/success",
        }

        response = client.post("/api/cloud/evilginx/lures", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "lure-001"
        assert data["phishlet"] == "o365"
        assert "url" in data

    def test_list_sessions(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test listing captured sessions."""
        response = client.get("/api/cloud/evilginx/sessions", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["username"] == "victim@corp.com"
        assert "tokens" in data[0]

    def test_get_session(self, client: TestClient, auth_headers: dict, mock_cloud_manager):
        """Test getting a specific session."""
        mock_cloud_manager.get_session = AsyncMock(return_value=Session(
            id="sess-001",
            phishlet="o365",
            username="victim@corp.com",
            password="Summer2024!",
            tokens={"access_token": "eyJ...", "refresh_token": "abc..."},
            ip="1.2.3.4",
            user_agent="Mozilla/5.0",
            captured_at=datetime.now(),
        ))

        response = client.get("/api/cloud/evilginx/sessions/sess-001", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["password"] == "Summer2024!"

    # ========== Authorization Tests ==========

    def test_hashcat_unauthorized(self, client: TestClient):
        """Test Hashcat API without auth."""
        response = client.get("/api/cloud/hashcat/jobs")
        assert response.status_code in [401, 403]

    def test_evilginx_unauthorized(self, client: TestClient):
        """Test Evilginx API without auth."""
        response = client.get("/api/cloud/evilginx/phishlets")
        assert response.status_code in [401, 403]


class TestCloudFlows:
    """Tests for complete cloud operation flows."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> NexusConfig:
        """Create test configuration."""
        return NexusConfig(
            device_id="nexus-flow",
            database={"path": str(tmp_path / "flow.db")},
            server={"enabled": True},
            security={"api_key": "flow-key"},
        )

    @pytest.fixture
    def mock_cloud_manager(self):
        """Create mock cloud manager."""
        manager = MagicMock(spec=CloudManager)

        # Track job states
        job_state = {"status": JobStatus.QUEUED, "progress": 0}

        def submit_job(*args, **kwargs):
            return CrackJob(
                id="flow-job-001",
                hash_value=kwargs.get("hash_value", "test"),
                hash_type=HashType.WPA2,
                status=JobStatus.QUEUED,
                created_at=datetime.now(),
            )

        def get_status(job_id):
            job_state["progress"] += 25
            if job_state["progress"] >= 100:
                job_state["status"] = JobStatus.COMPLETED
            return CrackJob(
                id=job_id,
                hash_value="test",
                hash_type=HashType.WPA2,
                status=job_state["status"],
                progress=min(job_state["progress"], 100),
                created_at=datetime.now(),
            )

        manager.submit_crack_job = AsyncMock(side_effect=submit_job)
        manager.get_job_status = AsyncMock(side_effect=get_status)
        manager.get_job_result = AsyncMock(return_value=CrackResult(
            job_id="flow-job-001",
            success=True,
            password="FlowPassword!",
            hash_type=HashType.WPA2,
            duration_seconds=300,
            completed_at=datetime.now(),
        ))

        return manager

    @pytest.fixture
    def client(self, config: NexusConfig, mock_cloud_manager) -> TestClient:
        """Create test client."""
        app = create_app(config)
        app.state.cloud_manager = mock_cloud_manager
        return TestClient(app)

    def test_full_crack_flow(self, client: TestClient, mock_cloud_manager):
        """Test complete cracking flow: submit → poll → result."""
        headers = {"Authorization": "Bearer flow-key"}

        # Step 1: Submit job
        submit_resp = client.post(
            "/api/cloud/hashcat/jobs",
            json={
                "hash_value": "abcd1234",
                "hash_type": "WPA2",
                "wordlist": "rockyou.txt",
            },
            headers=headers,
        )
        assert submit_resp.status_code == 200
        job_id = submit_resp.json()["id"]

        # Step 2: Poll for status (simulates progress)
        for _ in range(4):
            status_resp = client.get(f"/api/cloud/hashcat/jobs/{job_id}", headers=headers)
            assert status_resp.status_code == 200
            status = status_resp.json()
            if status["status"] == "COMPLETED":
                break

        assert status["status"] == "COMPLETED"

        # Step 3: Get result
        result_resp = client.get(f"/api/cloud/hashcat/jobs/{job_id}/result", headers=headers)
        assert result_resp.status_code == 200
        result = result_resp.json()
        assert result["success"] is True
        assert result["password"] == "FlowPassword!"

    def test_phishing_campaign_flow(self, client: TestClient, mock_cloud_manager):
        """Test complete phishing campaign flow."""
        headers = {"Authorization": "Bearer flow-key"}

        # Setup phishlet mocks
        mock_cloud_manager.list_phishlets = AsyncMock(return_value=[
            Phishlet(name="o365", status=PhishletStatus.DISABLED, hostname=None),
        ])
        mock_cloud_manager.enable_phishlet = AsyncMock(return_value=True)
        mock_cloud_manager.create_lure = AsyncMock(return_value=Lure(
            id="campaign-lure",
            phishlet="o365",
            path="/secure",
            redirect_url="https://office.com",
            url="https://login.phish.com/secure",
        ))
        mock_cloud_manager.list_sessions = AsyncMock(return_value=[
            Session(
                id="victim-session",
                phishlet="o365",
                username="target@company.com",
                password="P@ssw0rd!",
                tokens={"access": "token123"},
                ip="10.0.0.1",
                user_agent="Chrome",
                captured_at=datetime.now(),
            ),
        ])

        # Step 1: List available phishlets
        list_resp = client.get("/api/cloud/evilginx/phishlets", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()[0]["name"] == "o365"

        # Step 2: Enable phishlet
        enable_resp = client.post(
            "/api/cloud/evilginx/phishlets/o365/enable",
            json={"hostname": "login.phish.com"},
            headers=headers,
        )
        assert enable_resp.status_code == 200

        # Step 3: Create lure
        lure_resp = client.post(
            "/api/cloud/evilginx/lures",
            json={
                "phishlet": "o365",
                "path": "/secure",
                "redirect_url": "https://office.com",
            },
            headers=headers,
        )
        assert lure_resp.status_code == 200
        lure_url = lure_resp.json()["url"]
        assert "phish.com" in lure_url

        # Step 4: Check captured sessions (after victim clicks)
        sessions_resp = client.get("/api/cloud/evilginx/sessions", headers=headers)
        assert sessions_resp.status_code == 200
        sessions = sessions_resp.json()
        assert len(sessions) == 1
        assert sessions[0]["username"] == "target@company.com"
        assert sessions[0]["password"] == "P@ssw0rd!"


class TestCloudManagerUnit:
    """Unit tests for CloudManager class."""

    @pytest.mark.asyncio
    async def test_cloud_manager_initialization(self):
        """Test CloudManager initializes with clients."""
        with patch.object(HashcatCloudClient, '__init__', return_value=None), \
             patch.object(EvilginxClient, '__init__', return_value=None):

            manager = CloudManager(
                hashcat_url="https://gpu.example.com",
                hashcat_key="key1",
                evilginx_url="https://phish.example.com",
                evilginx_key="key2",
            )

            assert manager is not None

    @pytest.mark.asyncio
    async def test_cloud_manager_submit_job_delegates(self):
        """Test that CloudManager delegates to HashcatClient."""
        mock_hashcat = MagicMock(spec=HashcatCloudClient)
        mock_hashcat.submit_job = AsyncMock(return_value=CrackJob(
            id="test-job",
            hash_value="hash",
            hash_type=HashType.WPA2,
            status=JobStatus.QUEUED,
            created_at=datetime.now(),
        ))

        manager = CloudManager.__new__(CloudManager)
        manager._hashcat = mock_hashcat
        manager._evilginx = MagicMock()

        result = await manager.submit_crack_job(
            hash_value="test-hash",
            hash_type=HashType.WPA2,
        )

        assert result.id == "test-job"
        mock_hashcat.submit_job.assert_called_once()

