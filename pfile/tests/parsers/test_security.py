"""Tests for security utilities: PII redaction and session encryption."""

from __future__ import annotations

from pfile.security import decrypt_session, encrypt_session, is_encrypted, redact_pii

# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------

class TestRedactPii:
    def test_ssn_redacted(self):
        assert "123-45-6789" not in redact_pii("SSN: 123-45-6789")

    def test_ssn_replaced_with_placeholder(self):
        result = redact_pii("SSN: 123-45-6789")
        assert "XXX-XX-XXXX" in result

    def test_ein_redacted(self):
        result = redact_pii("EIN: 12-3456789")
        assert "12-3456789" not in result
        assert "XX-XXXXXXX" in result

    def test_long_account_number_redacted(self):
        result = redact_pii("Account: 123456789012")
        assert "123456789012" not in result

    def test_short_number_not_redacted(self):
        # 4-digit numbers should not be touched
        result = redact_pii("year 2024")
        assert "2024" in result

    def test_multiple_ssns_all_redacted(self):
        text = "Primary: 111-22-3333  Spouse: 444-55-6666"
        result = redact_pii(text)
        assert "111-22-3333" not in result
        assert "444-55-6666" not in result

    def test_non_pii_text_preserved(self):
        text = "Total wages: $50,000.00  Filing status: single"
        result = redact_pii(text)
        assert "Total wages" in result
        assert "single" in result


# ---------------------------------------------------------------------------
# Session encryption round-trip
# ---------------------------------------------------------------------------

class TestSessionEncryption:
    def test_round_trip(self):
        original = '{"id": "abc", "tax_year": 2024}'
        cipher = encrypt_session(original)
        assert decrypt_session(cipher) == original

    def test_encrypted_bytes_not_plaintext(self):
        cipher = encrypt_session('{"secret": "data"}')
        assert b'"secret"' not in cipher

    def test_is_encrypted_true_for_fernet(self):
        cipher = encrypt_session("test")
        assert is_encrypted(cipher)

    def test_is_encrypted_false_for_json(self):
        assert not is_encrypted(b'{"tax_year": 2024}')

    def test_different_sessions_produce_different_ciphertext(self):
        a = encrypt_session('{"id": "aaa"}')
        b = encrypt_session('{"id": "bbb"}')
        assert a != b
