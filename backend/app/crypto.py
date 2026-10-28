import os
import base64
import logging
from typing import Optional, List, Tuple
from cryptography.fernet import Fernet, MultiFernet, InvalidToken

logger = logging.getLogger(__name__)

class TokenEncryptionError(Exception):
    """Raised when encryption or decryption of sensitive tokens fails."""
    pass

class TokenEncryptor:
    """
    Authenticated encryption engine for storing sensitive tokens at rest.
    Uses Fernet (AES-128-CBC + HMAC-SHA256 authenticated symmetric encryption).
    Supports zero-downtime key rotation via MultiFernet.
    """

    def __init__(self, key_or_keys: Optional[str] = None, service_role_key: Optional[str] = None):
        raw_keys = key_or_keys if key_or_keys is not None else os.getenv("PATCHWORKS_ENCRYPTION_KEY", "")
        self._service_role_key = (service_role_key if service_role_key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
        self._engine, self._configured = self._initialize_engine(raw_keys)

    @staticmethod
    def generate_key() -> str:
        """Generate a cryptographically secure 32-byte base64-encoded Fernet key."""
        return Fernet.generate_key().decode("utf-8")

    def _initialize_engine(self, raw_keys: str) -> Tuple[Optional[MultiFernet], bool]:
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if not keys:
            # Check if running in development / test environment
            logger.warning(
                "PATCHWORKS_ENCRYPTION_KEY is not set. Generating ephemeral in-memory encryption key. "
                "Tokens will not survive application restarts until a persistent key is configured."
            )
            ephemeral_key = Fernet.generate_key()
            return MultiFernet([Fernet(ephemeral_key)]), False

        fernet_instances: List[Fernet] = []

        for key in keys:
            # Strict safety check: Never allow using the Supabase service role key as the encryption key
            if self._service_role_key and key == self._service_role_key:
                raise ValueError("Security violation: PATCHWORKS_ENCRYPTION_KEY cannot match SUPABASE_SERVICE_ROLE_KEY.")

            try:
                # Ensure key is valid 32-byte base64-encoded key
                decoded = base64.urlsafe_b64decode(key.encode("utf-8"))
                if len(decoded) != 32:
                    raise ValueError(f"Invalid key length: expected 32 bytes, got {len(decoded)}")
                fernet_instances.append(Fernet(key.encode("utf-8")))
            except Exception as e:
                logger.error(f"Failed to initialize encryption key: {e}")
                raise ValueError(f"Invalid PATCHWORKS_ENCRYPTION_KEY format: {e}") from e

        if not fernet_instances:
            raise ValueError("No valid encryption keys provided.")

        return MultiFernet(fernet_instances), True

    @property
    def is_configured(self) -> bool:
        """Returns True if a persistent key was loaded from environment configuration."""
        return self._configured

    def encrypt(self, plaintext_token: str) -> str:
        """
        Encrypt a sensitive plaintext token.
        Returns a URL-safe base64-encoded ciphertext string.
        """
        if not plaintext_token or not isinstance(plaintext_token, str):
            raise TokenEncryptionError("Cannot encrypt empty or non-string token.")

        if self._engine is None:
            raise TokenEncryptionError("Encryption engine is not initialized.")

        try:
            encrypted_bytes = self._engine.encrypt(plaintext_token.encode("utf-8"))
            return encrypted_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"Token encryption failed: {type(e).__name__}")
            raise TokenEncryptionError("Failed to encrypt token.") from e

    def decrypt(self, encrypted_token: str) -> str:
        """
        Decrypt a ciphertext token back into plaintext.
        Never logs or leaks the decrypted result.
        """
        if not encrypted_token or not isinstance(encrypted_token, str):
            raise TokenEncryptionError("Cannot decrypt empty or non-string token.")

        if self._engine is None:
            raise TokenEncryptionError("Encryption engine is not initialized.")

        try:
            decrypted_bytes = self._engine.decrypt(encrypted_token.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as e:
            logger.error("Token decryption failed: invalid ciphertext or corrupted key.")
            raise TokenEncryptionError("Invalid or corrupted ciphertext token.") from e
        except Exception as e:
            logger.error(f"Unexpected token decryption error: {type(e).__name__}")
            raise TokenEncryptionError("Failed to decrypt token.") from e

    def rotate(self, encrypted_token: str) -> Tuple[str, bool]:
        """
        Re-encrypt an existing token under the primary key if it was encrypted with an older key.
        Returns (re_encrypted_token, was_rotated).
        """
        if not encrypted_token or not isinstance(encrypted_token, str):
            raise TokenEncryptionError("Cannot rotate empty or non-string token.")

        if self._engine is None:
            raise TokenEncryptionError("Encryption engine is not initialized.")

        try:
            rotated_bytes = self._engine.rotate(encrypted_token.encode("utf-8"))
            rotated_str = rotated_bytes.decode("utf-8")
            was_changed = (rotated_str != encrypted_token)
            return rotated_str, was_changed
        except InvalidToken as e:
            logger.error("Token rotation failed: token cannot be decrypted with any available key.")
            raise TokenEncryptionError("Token could not be rotated with configured keys.") from e
        except Exception as e:
            logger.error(f"Token rotation error: {type(e).__name__}")
            raise TokenEncryptionError("Failed to rotate token.") from e

# Default singleton instance using environment configuration
token_encryptor = TokenEncryptor()
