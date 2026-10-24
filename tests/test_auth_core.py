"""Unit tests for password hashing, policy validation, and cryptographic tokens."""
from __future__ import annotations

import unittest

from app.backend.auth.security import (
    dummy_verify_password,
    generate_session_token,
    hash_password,
    hash_token,
    normalize_email,
    validate_email_format,
    validate_password_policy,
    verify_password,
)


class TestAuthCoreSecurity(unittest.TestCase):
    def test_argon2id_hashing_and_verification(self):
        password = "SecurePassword123!@#"
        pwd_hash = hash_password(password)

        self.assertTrue(pwd_hash.startswith("$argon2id$"))
        self.assertTrue(verify_password(password, pwd_hash))
        self.assertFalse(verify_password("WrongPassword123!@#", pwd_hash))
        self.assertFalse(verify_password("", pwd_hash))
        self.assertFalse(verify_password(password, ""))

    def test_different_hashes_for_same_password(self):
        password = "SecurePassword123!@#"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        self.assertNotEqual(hash1, hash2, "Unique salt must be generated for each hash.")

    def test_password_policy_enforcement(self):
        # Too short (< 10)
        valid, msg = validate_password_policy("Short1!")
        self.assertFalse(valid)
        self.assertIn("at least 10", msg)

        # No uppercase
        valid, msg = validate_password_policy("lowercase123!@#")
        self.assertFalse(valid)
        self.assertIn("uppercase", msg)

        # No lowercase
        valid, msg = validate_password_policy("UPPERCASE123!@#")
        self.assertFalse(valid)
        self.assertIn("lowercase", msg)

        # No digits
        valid, msg = validate_password_policy("NoDigitsHere!@#")
        self.assertFalse(valid)
        self.assertIn("digit", msg)

        # No special characters
        valid, msg = validate_password_policy("NoSpecialChars123")
        self.assertFalse(valid)
        self.assertIn("special", msg)

        # Valid strong password
        valid, msg = validate_password_policy("Valid10Chars!@#")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_dummy_verify_password_executes_without_error(self):
        # Must execute cleanly to mitigate timing attacks
        dummy_verify_password()

    def test_session_token_generation_and_hashing(self):
        token1 = generate_session_token()
        token2 = generate_session_token()

        self.assertNotEqual(token1, token2)
        self.assertTrue(len(token1) >= 40)

        hash1 = hash_token(token1)
        hash2 = hash_token(token1)
        self.assertEqual(hash1, hash2, "Hash must be deterministic SHA-256 hex string.")
        self.assertEqual(len(hash1), 64)

    def test_email_normalization_and_validation(self):
        self.assertEqual(normalize_email("  Investigator@Agency.GO.TH "), "investigator@agency.go.th")
        self.assertTrue(validate_email_format("investigator@agency.go.th"))
        self.assertFalse(validate_email_format("invalid-email-string"))
        self.assertFalse(validate_email_format(""))


if __name__ == "__main__":
    unittest.main()
