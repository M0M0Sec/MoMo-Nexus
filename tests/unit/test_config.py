"""
Tests for configuration system.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from nexus.config import (
    ChannelsConfig,
    NexusConfig,
    RoutingConfig,
    load_config,
)
from nexus.domain.enums import ChannelType, Priority


class TestNexusConfig:
    """Tests for NexusConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = NexusConfig()

        assert config.device_id == "nexus-001"
        assert config.name == "Nexus Hub"
        assert config.channels.lora.enabled is True
        assert config.channels.cellular.enabled is False

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = NexusConfig(
            device_id="nexus-custom",
            name="Custom Hub",
        )
        assert config.device_id == "nexus-custom"
        assert config.name == "Custom Hub"

    def test_get_enabled_channels(self) -> None:
        """Test getting enabled channels."""
        config = NexusConfig()
        enabled = config.get_enabled_channels()

        assert ChannelType.LORA in enabled
        assert ChannelType.WIFI in enabled
        assert ChannelType.CELLULAR not in enabled

    def test_get_channels_for_priority(self) -> None:
        """Test getting channel order for priority."""
        config = NexusConfig()

        # Critical should prefer cellular first
        critical_channels = config.routing.priority_channels.get("critical", [])
        assert "cellular" in critical_channels

        # Low should prefer lora
        low_channels = config.routing.priority_channels.get("low", [])
        assert low_channels[0] == "lora"

    def test_yaml_save_load(self) -> None:
        """Test saving and loading YAML config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.yml"

            # Create and save
            config = NexusConfig(
                device_id="nexus-yaml-test",
                name="YAML Test",
            )
            config.to_yaml(config_path)

            assert config_path.exists()

            # Load and verify
            loaded = NexusConfig.from_yaml(config_path)
            assert loaded.device_id == "nexus-yaml-test"
            assert loaded.name == "YAML Test"

    def test_yaml_structure(self) -> None:
        """Test YAML output structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yml"

            config = NexusConfig()
            config.to_yaml(config_path)

            with open(config_path) as f:
                data = yaml.safe_load(f)

            assert "device_id" in data
            assert "channels" in data
            assert "routing" in data
            assert "fleet" in data


class TestChannelsConfig:
    """Tests for ChannelsConfig."""

    def test_default_channels(self) -> None:
        """Test default channel configuration."""
        config = ChannelsConfig()

        assert config.lora.enabled is True
        assert config.lora.region == "EU_868"
        assert config.cellular.enabled is False
        assert config.wifi.enabled is True
        assert config.ble.enabled is False

    def test_lora_config(self) -> None:
        """Test LoRa specific config."""
        config = ChannelsConfig()

        assert config.lora.serial_port == "/dev/ttyUSB0"
        assert config.lora.baud_rate == 115200
        assert config.lora.tx_power == 20


class TestRoutingConfig:
    """Tests for RoutingConfig."""

    def test_default_routing(self) -> None:
        """Test default routing configuration."""
        config = RoutingConfig()

        assert config.max_retries == 5
        assert config.ack_timeout == 30
        assert config.queue_max_size == 1000

    def test_priority_channel_mapping(self) -> None:
        """Test priority to channel mapping."""
        config = RoutingConfig()

        # Verify all priorities have channel lists
        assert "critical" in config.priority_channels
        assert "high" in config.priority_channels
        assert "normal" in config.priority_channels
        assert "low" in config.priority_channels
        assert "bulk" in config.priority_channels

        # Verify channel lists are not empty
        for channels in config.priority_channels.values():
            assert len(channels) > 0


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_default(self) -> None:
        """Test loading default config."""
        config = load_config()
        assert config is not None
        assert config.device_id is not None

    def test_load_from_path(self) -> None:
        """Test loading config from specific path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom.yml"

            # Create config file
            custom_config = NexusConfig(device_id="custom-nexus")
            custom_config.to_yaml(config_path)

            # Load from path
            loaded = load_config(config_path)
            assert loaded.device_id == "custom-nexus"

    def test_load_nonexistent(self) -> None:
        """Test loading from nonexistent path returns defaults."""
        config = load_config("/nonexistent/path/config.yml")
        assert config is not None
        assert config.device_id == "nexus-001"

