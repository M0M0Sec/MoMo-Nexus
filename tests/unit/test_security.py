"""
Tests for security layer.
"""

import secrets
import time

import pytest

from nexus.security.crypto import (
    KEY_SIZE,
    NONCE_SIZE,
    CryptoProvider,
    EncryptedPayload,
    derive_key,
    generate_key,
    generate_nonce,
)
from nexus.security.envelope import (
    EnvelopeBuilder,
    SecureEnvelope,
    SecurityLevel,
    unwrap_message,
    wrap_message,
)
from nexus.security.hmac import (
    AuthenticatedMessage,
    HMACProvider,
    sign_message,
    verify_hmac,
    verify_message,
)
from nexus.security.replay import ReplayGuard


class TestCrypto:
    """Tests for cryptographic primitives."""

    def test_generate_key(self) -> None:
        """Test key generation."""
        key = generate_key()
        assert len(key) == KEY_SIZE

        # Keys should be unique
        key2 = generate_key()
        assert key != key2

    def test_generate_nonce(self) -> None:
        """Test nonce generation."""
        nonce = generate_nonce()
        assert len(nonce) == NONCE_SIZE

    def test_derive_key(self) -> None:
        """Test key derivation."""
        master = generate_key()

        # Same context should give same key
        key1 = derive_key(master, "test")
        key2 = derive_key(master, "test")
        assert key1 == key2

        # Different context should give different key
        key3 = derive_key(master, "other")
        assert key1 != key3

    def test_encrypt_decrypt(self) -> None:
        """Test encryption and decryption."""
        key = generate_key()
        crypto = CryptoProvider(key)

        plaintext = b"Hello, MoMo-Nexus!"

        encrypted = crypto.encrypt(plaintext)
        assert encrypted.ciphertext != plaintext
        assert len(encrypted.nonce) == NONCE_SIZE

        decrypted = crypto.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_with_associated_data(self) -> None:
        """Test AEAD with associated data."""
        key = generate_key()
        crypto = CryptoProvider(key)

        plaintext = b"Secret data"
        ad = b"message-id-123"

        encrypted = crypto.encrypt(plaintext, ad)
        decrypted = crypto.decrypt(encrypted, ad)

        assert decrypted == plaintext

    def test_encrypt_message_string(self) -> None:
        """Test string message encryption."""
        key = generate_key()
        crypto = CryptoProvider(key)

        message = "Test message with UTF-8: 日本語"

        encrypted = crypto.encrypt_message(message)
        decrypted = crypto.decrypt_message(encrypted)

        assert decrypted == message

    def test_encrypted_payload_serialization(self) -> None:
        """Test payload serialization."""
        key = generate_key()
        crypto = CryptoProvider(key)

        plaintext = b"Test data"
        encrypted = crypto.encrypt(plaintext)

        # To bytes and back
        data = encrypted.to_bytes()
        restored = EncryptedPayload.from_bytes(data)
        decrypted = crypto.decrypt(restored)
        assert decrypted == plaintext

        # To base64 and back
        b64 = encrypted.to_base64()
        restored = EncryptedPayload.from_base64(b64)
        decrypted = crypto.decrypt(restored)
        assert decrypted == plaintext


class TestHMAC:
    """Tests for HMAC authentication."""

    def test_sign_verify(self) -> None:
        """Test basic signing and verification."""
        key = generate_key()
        hmac = HMACProvider(key)

        payload = b"Important message"

        message = hmac.sign(payload)
        assert hmac.verify(message) is True

    def test_invalid_signature(self) -> None:
        """Test that invalid signatures are rejected."""
        key = generate_key()
        hmac = HMACProvider(key)

        message = hmac.sign(b"Original")

        # Tamper with signature
        tampered = AuthenticatedMessage(
            payload=message.payload,
            signature=b"X" * 32,
            timestamp=message.timestamp,
            nonce=message.nonce,
        )

        assert hmac.verify(tampered) is False

    def test_tampered_payload(self) -> None:
        """Test that tampered payloads are rejected."""
        key = generate_key()
        hmac = HMACProvider(key)

        message = hmac.sign(b"Original")

        # Tamper with payload
        tampered = AuthenticatedMessage(
            payload=b"Tampered",
            signature=message.signature,
            timestamp=message.timestamp,
            nonce=message.nonce,
        )

        assert hmac.verify(tampered) is False

    def test_timestamp_validation(self) -> None:
        """Test timestamp freshness validation."""
        key = generate_key()
        hmac = HMACProvider(key, max_age=60)

        # Old message
        old_time = int(time.time()) - 120  # 2 minutes ago
        message = hmac.sign(b"Old message", old_time)

        assert hmac.verify(message, check_timestamp=True) is False
        assert hmac.verify(message, check_timestamp=False) is True

    def test_sign_dict(self) -> None:
        """Test dictionary signing."""
        key = generate_key()
        hmac = HMACProvider(key)

        data = {"cmd": "status", "device": "momo-001"}
        signed = hmac.sign_dict(data)

        assert "_sig" in signed
        assert "_ts" in signed
        assert "_nonce" in signed

        valid, original = hmac.verify_dict(signed)
        assert valid is True
        assert original["cmd"] == "status"

    def test_quick_functions(self) -> None:
        """Test quick sign/verify functions."""
        key = generate_key()

        data = {"type": "alert", "severity": "high"}
        signed = sign_message(key, data)

        valid, original = verify_message(key, signed)
        assert valid is True


class TestReplayGuard:
    """Tests for replay protection."""

    @pytest.fixture
    def guard(self) -> ReplayGuard:
        """Create replay guard."""
        return ReplayGuard(window_seconds=60, max_nonces=100)

    @pytest.mark.asyncio
    async def test_first_nonce_valid(self, guard: ReplayGuard) -> None:
        """Test that first nonce is accepted."""
        nonce = secrets.token_hex(16)
        timestamp = int(time.time())

        result = await guard.check_nonce(nonce, timestamp)
        assert result is True

    @pytest.mark.asyncio
    async def test_replay_rejected(self, guard: ReplayGuard) -> None:
        """Test that replayed nonces are rejected."""
        nonce = secrets.token_hex(16)
        timestamp = int(time.time())

        # First use
        assert await guard.check_nonce(nonce, timestamp) is True

        # Replay attempt
        assert await guard.check_nonce(nonce, timestamp) is False

    @pytest.mark.asyncio
    async def test_old_timestamp_rejected(self, guard: ReplayGuard) -> None:
        """Test that old timestamps are rejected."""
        nonce = secrets.token_hex(16)
        old_time = int(time.time()) - 120  # 2 minutes ago

        result = await guard.check_nonce(nonce, old_time)
        assert result is False

    @pytest.mark.asyncio
    async def test_device_isolation(self, guard: ReplayGuard) -> None:
        """Test that nonces are isolated per device."""
        nonce = secrets.token_hex(16)
        timestamp = int(time.time())

        # Same nonce for different devices should both be valid
        assert await guard.check_nonce(nonce, timestamp, "device-1") is True
        assert await guard.check_nonce(nonce, timestamp, "device-2") is True

        # But replay for same device is rejected
        assert await guard.check_nonce(nonce, timestamp, "device-1") is False

    @pytest.mark.asyncio
    async def test_sequence_validation(self, guard: ReplayGuard) -> None:
        """Test sequence number validation."""
        # Increasing sequences are valid
        assert await guard.check_sequence("dev-1", 1) is True
        assert await guard.check_sequence("dev-1", 2) is True
        assert await guard.check_sequence("dev-1", 5) is True

        # Replay/decrease is rejected
        assert await guard.check_sequence("dev-1", 3) is False
        assert await guard.check_sequence("dev-1", 5) is False

    @pytest.mark.asyncio
    async def test_lru_eviction(self) -> None:
        """Test LRU eviction when over limit."""
        guard = ReplayGuard(window_seconds=60, max_nonces=10)
        timestamp = int(time.time())

        # Add 15 nonces (over limit of 10)
        for i in range(15):
            nonce = f"nonce-{i}"
            await guard.check_nonce(nonce, timestamp)

        stats = await guard.get_stats()
        assert stats["total_nonces"] <= 10


class TestSecureEnvelope:
    """Tests for secure envelope."""

    def test_envelope_serialization(self) -> None:
        """Test envelope serialization."""
        envelope = SecureEnvelope(
            lvl=SecurityLevel.SIGNED,
            payload='{"test": true}',
            sig="abc123",
        )

        # To dict and back
        data = envelope.to_dict()
        restored = SecureEnvelope.from_dict(data)
        assert restored.payload == envelope.payload
        assert restored.lvl == envelope.lvl

        # To JSON and back
        json_str = envelope.to_json()
        restored = SecureEnvelope.from_json(json_str)
        assert restored.payload == envelope.payload

    def test_wrap_signed(self) -> None:
        """Test wrapping with signature."""
        hmac_key = generate_key()
        builder = EnvelopeBuilder(hmac_key)

        payload = {"cmd": "status", "device_id": "momo-001"}
        envelope = builder.wrap(payload, SecurityLevel.SIGNED)

        assert envelope.lvl == SecurityLevel.SIGNED
        assert envelope.sig != ""
        assert builder.verify(envelope) is True

    def test_wrap_encrypted(self) -> None:
        """Test wrapping with encryption."""
        hmac_key = generate_key()
        enc_key = generate_key()
        builder = EnvelopeBuilder(hmac_key, enc_key)

        payload = {"secret": "data", "pin": "1234"}
        envelope = builder.wrap(payload, SecurityLevel.ENCRYPTED)

        assert envelope.lvl == SecurityLevel.ENCRYPTED
        # Payload should be base64 encoded encrypted data
        assert "secret" not in envelope.payload

        # Should be verifiable and decryptable
        unwrapped = builder.unwrap(envelope)
        assert unwrapped["secret"] == "data"
        assert unwrapped["pin"] == "1234"

    def test_tampered_envelope_rejected(self) -> None:
        """Test that tampered envelopes are rejected."""
        hmac_key = generate_key()
        builder = EnvelopeBuilder(hmac_key)

        payload = {"important": "data"}
        envelope = builder.wrap(payload, SecurityLevel.SIGNED)

        # Tamper with payload
        envelope.payload = '{"important": "hacked"}'

        assert builder.verify(envelope) is False

        with pytest.raises(ValueError):
            builder.unwrap(envelope)

    def test_quick_wrap_unwrap(self) -> None:
        """Test quick wrap/unwrap functions."""
        hmac_key = generate_key()
        enc_key = generate_key()

        payload = {"type": "alert", "severity": "high"}

        envelope = wrap_message(payload, hmac_key, enc_key, SecurityLevel.ENCRYPTED)
        unwrapped = unwrap_message(envelope, hmac_key, enc_key)

        assert unwrapped["type"] == "alert"
        assert unwrapped["severity"] == "high"

