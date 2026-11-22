"""Security checks against an explicitly selected, migrated disposable PostgreSQL."""
import os
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pyotp
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from auth import _create_token, create_access_token, create_refresh_token
from db import DATABASE_URL, SessionLocal, engine
from main import app
from models import MFAChallenge, User
from services import mfa


@unittest.skipUnless(os.getenv("MFA_TEST_DATABASE_URL"), "Set MFA_TEST_DATABASE_URL to a disposable database")
class MFATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ["MFA_TEST_DATABASE_URL"] != DATABASE_URL or engine.dialect.name != "postgresql":
            raise RuntimeError("MFA_TEST_DATABASE_URL must match DATABASE_URL and use PostgreSQL")

    def setUp(self):
        self.now = datetime(2030, 1, 1, 12, 0)
        self.clock = patch("services.mfa.utcnow", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.key = Fernet.generate_key().decode()
        self.environment = patch.dict(os.environ, MFA_ENCRYPTION_KEY=self.key)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.credentials = {"email": f"mfa-{uuid4().hex}@example.com", "password": "test-password"}
        response = self.client.post("/api/auth/register", json={**self.credentials, "name": "MFA test"})
        self.assertEqual(response.status_code, 201)
        self.old_tokens = response.json()
        self.use_tokens(self.old_tokens)
        self.uid = self.client.get("/api/auth/me").json()["id"]
        self.addCleanup(self.remove_user)

    def remove_user(self):
        with SessionLocal() as db:
            db.query(User).filter_by(id=self.uid).delete()
            db.commit()

    def use_tokens(self, tokens):
        self.client.headers["Authorization"] = "Bearer " + tokens["access_token"]

    def post(self, path, data, expected=200):
        response = self.client.post("/api/auth/" + path, json=data)
        self.assertEqual(response.status_code, expected, f"{path} returned {response.status_code}")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        return response.json()

    def code(self, secret):
        return pyotp.TOTP(secret).at(self.now.replace(tzinfo=timezone.utc))

    def setup_secret(self):
        return self.post("mfa/setup", {"password": self.credentials["password"]})["secret"]

    def enroll(self):
        secret = self.setup_secret()
        tokens = self.post("mfa/enable", {"code": self.code(secret)})
        self.use_tokens(tokens)
        return secret, tokens

    def challenge(self):
        response = self.post("login", self.credentials)
        self.assertTrue(response["mfa_required"])
        self.assertNotIn("access_token", response)
        return response["challenge_token"]

    def verify(self, challenge, code, expected=200):
        return self.post("mfa/verify", {"challenge_token": challenge, "code": code}, expected)

    def test_optional_login_and_legacy_tokens(self):
        self.post("login", self.credentials)
        self.post("refresh", {"refresh_token": self.old_tokens["refresh_token"]})
        old_access = _create_token({"sub": str(self.uid), "type": "access"}, timedelta(minutes=2))
        old_refresh = _create_token({"sub": str(self.uid), "type": "refresh"}, timedelta(minutes=2))
        self.use_tokens({"access_token": old_access})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.post("refresh", {"refresh_token": old_refresh})
        status = self.client.get("/api/auth/mfa/status").json()
        self.assertEqual(status, {"enabled": False, "recovery_codes_remaining": 0})

    def test_setup_reauth_encryption_expiry_and_pending_state(self):
        self.post("mfa/setup", {"password": "incorrect"}, 401)
        secret = self.setup_secret()
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            self.assertFalse(user.mfa_enabled)
            self.assertIsNone(user.mfa_secret)
            self.assertNotIn(secret, user.mfa_pending_secret)
            self.assertTrue(Fernet(self.key).decrypt(user.mfa_pending_secret.encode()).decode() == secret)
        self.assertIn("access_token", self.post("login", self.credentials))
        self.verify("unknown-challenge", self.code(secret), 401)
        self.now += timedelta(minutes=11)
        self.post("mfa/enable", {"code": self.code(secret)}, 409)
        self.assertFalse(self.client.get("/api/auth/mfa/status").json()["enabled"])

    def test_setup_replacement_rejects_previous_secret(self):
        previous = self.setup_secret()
        current = self.setup_secret()
        if self.code(previous) == self.code(current):
            self.now += timedelta(seconds=30)
        self.post("mfa/enable", {"code": self.code(previous)}, 401)
        self.post("mfa/enable", {"code": self.code(current)})

    def test_enable_revokes_prior_tokens_and_requires_factor_proof(self):
        _, enabled = self.enroll()
        self.assertEqual(len(enabled["recovery_codes"]), 10)
        self.use_tokens(self.old_tokens)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.post("refresh", {"refresh_token": self.old_tokens["refresh_token"]}, 401)
        for factory, path in [(create_access_token, "access"), (create_refresh_token, "refresh")]:
            token = factory(self.uid, auth_version=1, mfa=False)
            if path == "access":
                self.use_tokens({"access_token": token})
                self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
            else:
                self.post("refresh", {"refresh_token": token}, 401)
        self.use_tokens(enabled)
        refreshed = self.post("refresh", {"refresh_token": enabled["refresh_token"]})
        self.use_tokens(refreshed)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        with SessionLocal() as db:
            stored = db.get(User, self.uid).mfa_recovery_hashes
            self.assertEqual(len(stored), 10)
            self.assertTrue(all(len(value) == 64 for value in stored))
            self.assertTrue(all(mfa.digest(code.replace("-", "")) in stored for code in enabled["recovery_codes"]))

    def test_challenge_is_not_api_token_and_cannot_be_replayed(self):
        secret, _ = self.enroll()
        challenge = self.challenge()
        self.use_tokens({"access_token": challenge})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.post("refresh", {"refresh_token": challenge}, 401)
        self.verify(challenge, self.code(secret), 401)  # Enrollment consumed this step.
        self.now += timedelta(seconds=30)
        tokens = self.verify(challenge, self.code(secret))
        self.use_tokens(tokens)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.verify(challenge, self.code(secret), 401)
        self.verify(self.challenge(), self.code(secret), 401)

    def test_challenge_expiry_and_new_login_invalidation(self):
        secret, _ = self.enroll()
        old = self.challenge()
        new = self.challenge()
        self.verify(old, self.code(secret), 401)
        self.now += timedelta(seconds=mfa.CHALLENGE_SECONDS + 1)
        self.verify(new, self.code(secret), 401)

    def test_recovery_is_single_use_and_disable_revokes_sessions(self):
        secret, enrolled = self.enroll()
        first, second = enrolled["recovery_codes"][:2]
        self.verify(self.challenge(), first)
        self.verify(self.challenge(), first, 401)
        self.assertEqual(self.client.get("/api/auth/mfa/status").json()["recovery_codes_remaining"], 9)
        self.post("mfa/disable", {"password": "incorrect", "code": second}, 401)
        self.post("mfa/disable", {"password": self.credentials["password"], "code": self.code(secret)}, 401)
        disabled = self.post("mfa/disable", {"password": self.credentials["password"], "code": second})
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.post("refresh", {"refresh_token": enrolled["refresh_token"]}, 401)
        self.use_tokens(disabled)
        self.assertEqual(self.client.get("/api/auth/mfa/status").json(),
                         {"enabled": False, "recovery_codes_remaining": 0})
        self.assertIn("access_token", self.post("login", self.credentials))
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            self.assertIsNone(user.mfa_secret)
            self.assertEqual(user.auth_version, 2)

    def test_missing_key_fails_closed_and_recovery_works(self):
        with patch.dict(os.environ, MFA_ENCRYPTION_KEY=""):
            self.post("mfa/setup", {"password": self.credentials["password"]}, 503)
        secret, enrolled = self.enroll()
        challenge = self.challenge()
        self.now += timedelta(seconds=30)
        with patch.dict(os.environ, MFA_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.verify(challenge, self.code(secret), 503)
            self.verify(challenge, enrolled["recovery_codes"][0])

    def test_persistent_mfa_limit_survives_new_challenges(self):
        secret, _ = self.enroll()
        for attempt in range(5):
            challenge = self.challenge()
            self.verify(challenge, "wrong", 429 if attempt == 4 else 401)
        self.post("login", self.credentials, 429)
        self.now += timedelta(seconds=301)
        self.verify(self.challenge(), self.code(secret))

    def test_password_and_setup_limits_persist(self):
        for attempt in range(5):
            self.post("mfa/setup", {"password": "incorrect"}, 429 if attempt == 4 else 401)
        self.post("login", self.credentials, 429)
        self.now += timedelta(seconds=301)
        secret = self.setup_secret()
        for attempt in range(5):
            self.post("mfa/enable", {"code": "wrong"}, 429 if attempt == 4 else 401)
        self.post("mfa/setup", {"password": self.credentials["password"]}, 429)
        self.now += timedelta(seconds=301)
        self.post("mfa/enable", {"code": self.code(secret)})

    def concurrent_verify(self, challenges, code):
        barrier = threading.Barrier(2)
        def request(challenge):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.post("/api/auth/mfa/verify", json={
                    "challenge_token": challenge, "code": code}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(request, challenges))

    def test_concurrent_challenge_consumption(self):
        secret, _ = self.enroll()
        self.now += timedelta(seconds=30)
        challenge = self.challenge()
        self.assertEqual(self.concurrent_verify([challenge, challenge], self.code(secret)), [200, 401])

    def test_concurrent_recovery_across_distinct_challenges(self):
        _, enrolled = self.enroll()
        first = self.challenge()
        second = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(MFAChallenge(token_hash=mfa.digest(second), user_id=self.uid, auth_version=1,
                                expires_at=self.now + timedelta(minutes=5)))
            db.commit()
        self.assertEqual(self.concurrent_verify([first, second], enrolled["recovery_codes"][0]), [200, 401])

    def test_concurrent_totp_across_distinct_challenges(self):
        secret, _ = self.enroll()
        self.now += timedelta(seconds=30)
        first = self.challenge()
        second = secrets.token_urlsafe(32)
        with SessionLocal() as db:
            db.add(MFAChallenge(token_hash=mfa.digest(second), user_id=self.uid, auth_version=1,
                                expires_at=self.now + timedelta(minutes=5)))
            db.commit()
        self.assertEqual(self.concurrent_verify([first, second], self.code(secret)), [200, 401])

    def test_concurrent_enable_uses_original_session_only_once(self):
        secret = self.setup_secret()
        barrier = threading.Barrier(2)
        def enable_once(_):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                response = client.post("/api/auth/mfa/enable",
                                       headers={"Authorization": "Bearer " + self.old_tokens["access_token"]},
                                       json={"code": self.code(secret)})
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(enable_once, range(2))), [200, 401])

    def test_auth_errors_are_not_cacheable(self):
        response = self.client.post("/api/auth/mfa/verify", json={"code": "123456"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")


if __name__ == "__main__":
    unittest.main()
