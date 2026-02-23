"""
Security utilities for pFile.

  - Fernet-based session file encryption (whole-file, AES-128-CBC + HMAC).
  - PII redaction for text sent to LLM APIs.

Key management
--------------
The Fernet key is stored in the OS credential store via `keyring`:
  - macOS  → Keychain (protected by login password / Touch ID)
  - Windows → Windows Credential Manager
  - Linux  → SecretService (GNOME Keyring, KWallet) or, as fallback, a
             plaintext file in ~/.local/share/python_keyring/ (warn user).

The key is generated once and never written to disk by pFile itself.
"""

from __future__ import annotations

import re

import keyring
import keyring.errors
from cryptography.fernet import Fernet

_SERVICE = "pfile"
_USERNAME = "session-encryption-key"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def _load_or_create_key() -> bytes:
    """Return the Fernet key from the OS keychain, creating it if absent."""
    stored = keyring.get_password(_SERVICE, _USERNAME)
    if stored:
        return stored.encode()

    key = Fernet.generate_key()
    try:
        keyring.set_password(_SERVICE, _USERNAME, key.decode())
    except keyring.errors.NoKeyringError:
        # No secure backend available (headless server, CI).  Fall back to
        # an env-var so callers can inject a key without writing to disk.
        import os
        env_key = os.environ.get("PFILE_ENCRYPTION_KEY")
        if env_key:
            return env_key.encode()
        raise RuntimeError(
            "No system keyring found and PFILE_ENCRYPTION_KEY env var is not set.\n"
            "On headless systems, export PFILE_ENCRYPTION_KEY=<base64-fernet-key>."
        ) from None
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


# ---------------------------------------------------------------------------
# Session encryption
# ---------------------------------------------------------------------------

def encrypt_session(plaintext: str) -> bytes:
    """Encrypt a session JSON string and return cipher bytes."""
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_session(ciphertext: bytes) -> str:
    """Decrypt cipher bytes back to a session JSON string."""
    return _fernet().decrypt(ciphertext).decode("utf-8")


def is_encrypted(data: bytes) -> bool:
    """Return True if the data looks like a Fernet token (base64, starts with 'gA')."""
    try:
        return data[:2] == b"gA"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PII redaction for LLM input
# ---------------------------------------------------------------------------

# Patterns that identify common PII in tax documents
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # SSN:  123-45-6789
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "XXX-XX-XXXX"),
    # EIN:  12-3456789
    (re.compile(r"\b\d{2}-\d{7}\b"), "XX-XXXXXXX"),
    # Account numbers: 8–17 consecutive digits (often brokerage/bank account)
    (re.compile(r"\b\d{8,17}\b"), "XXXXXXXXXXXXXXX"),
    # Routing numbers: exactly 9 digits at start of line or after whitespace
    (re.compile(r"(?<!\d)\d{9}(?!\d)"), "XXXXXXXXX"),
]


def redact_pii(text: str) -> str:
    """
    Replace SSNs, EINs, and long account-number strings with placeholders.

    Applied before sending document text to any external LLM API.
    The replacement values are clearly marked so the LLM knows data was
    redacted and can return null/low-confidence for affected fields.
    """
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
