"""Password reset security checks using explicitly selected disposable PostgreSQL."""
import json
import os
import smtplib
import ssl
import subprocess
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import anyio
import pyotp
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from auth import verify_password
from db import DATABASE_URL, SessionLocal, engine
from main import app
from models import MFAChallenge, PasswordResetMailSlot, PasswordResetRate, PasswordResetToken, User
from services import password_reset as reset
from services import reset_mail

MAIL_ENV = {
    "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "465", "SMTP_USERNAME": "sender@example.com",
    "SMTP_PASSWORD": "test-mail-password", "SMTP_FROM": "sender@example.com", "SMTP_TLS_MODE": "ssl",
    "PASSWORD_RESET_URL": "https://gethubaboba.github.io/AI_Calendar_App_Personal/reset-password/",
}
NEW_PASSWORD = "New-reset-password-42!"


@unittest.skipUnless(os.getenv("RESET_TEST_DATABASE_URL"), "Set RESET_TEST_DATABASE_URL to a disposable database")
class PasswordResetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ["RESET_TEST_DATABASE_URL"] != DATABASE_URL or engine.dialect.name != "postgresql":
            raise RuntimeError("RESET_TEST_DATABASE_URL must match DATABASE_URL and use PostgreSQL")

    def setUp(self):
        self.now = datetime(2030, 1, 1, 12, 0)
        for target in ("services.password_reset.utcnow", "services.mfa.utcnow"):
            mock = patch(target, side_effect=lambda: self.now)
            mock.start()
            self.addCleanup(mock.stop)
        environment = patch.dict(os.environ, {**MAIL_ENV, "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode()})
        environment.start()
        self.addCleanup(environment.stop)
        mail_patch = patch("services.password_reset.send_reset_mail", return_value=True)
        self.mail = mail_patch.start()
        self.addCleanup(mail_patch.stop)
        with SessionLocal() as db:
            db.query(PasswordResetRate).filter(
                PasswordResetRate.key.notin_(("global-minute", "global-hour"))).delete()
            db.query(PasswordResetRate).update({"count": 0, "window_start": self.now, "last_request_at": self.now})
            db.query(PasswordResetMailSlot).update({"owner": None, "lease_until": self.now})
            db.commit()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.credentials = {"email": f"reset-{uuid4().hex}@example.com", "password": "original-password"}
        response = self.client.post("/api/auth/register", json={**self.credentials, "name": "Reset test"})
        self.assertEqual(response.status_code, 201)
        self.tokens = response.json()
        self.client.headers["Authorization"] = "Bearer " + self.tokens["access_token"]
        self.uid = self.client.get("/api/auth/me").json()["id"]
        self.addCleanup(self.remove_user)

    def remove_user(self):
        with SessionLocal() as db:
            db.query(User).filter_by(id=self.uid).delete()
            db.commit()

    def forgot(self, email=None, status=200):
        response = self.client.post("/api/auth/password/forgot",
                                    json={"email": email or self.credentials["email"]})
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        return response

    def token(self):
        self.forgot()
        self.assertTrue(self.mail.called)
        return self.mail.call_args.args[2]

    def submit(self, token, password=NEW_PASSWORD, status=200):
        response = self.client.post("/api/auth/password/reset", json={"token": token, "new_password": password})
        self.assertEqual(response.status_code, status, f"reset returned {response.status_code}")
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        return response

    def test_uniform_reply_normalization_and_digest_only_storage(self):
        known = self.forgot()
        token = self.mail.call_args.args[2]
        unknown = self.forgot("unknown@example.com")
        cooldown = self.forgot(self.credentials["email"].upper())
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual(known.json(), cooldown.json())
        self.assertEqual(known.json(), {"message": reset.REQUEST_MESSAGE})
        self.assertEqual(self.mail.call_count, 1)
        self.assertNotIn(token, known.text)
        self.assertEqual(len(token), 43)
        with SessionLocal() as db:
            row = db.query(PasswordResetToken).filter_by(user_id=self.uid).one()
            self.assertTrue(row.token_hash == reset.digest(token))
            self.assertEqual(row.expires_at, self.now + timedelta(minutes=15))
            self.assertEqual(db.get(PasswordResetRate, reset.digest("unknown@example.com")).count, 1)
            self.assertEqual(db.get(PasswordResetRate, reset.digest(self.credentials["email"])).count, 1)
            user = db.get(User, self.uid)
            self.assertEqual(user.auth_version, 0)
            self.assertTrue(verify_password(self.credentials["password"], user.password_hash))

    def test_missing_or_insecure_mail_config_is_uniform_503(self):
        for environment in ({"SMTP_PASSWORD": ""}, {"SMTP_TLS_MODE": "none"},
                            {"PASSWORD_RESET_URL": "http://insecure.example/reset"},
                            {"PASSWORD_RESET_URL": "https://example.com/reset?token=bad"}):
            with self.subTest(config=list(environment)), patch.dict(os.environ, environment):
                self.assertEqual(self.forgot(status=503).json(), self.forgot("unknown@example.com", 503).json())
        self.mail.assert_not_called()

    def test_expired_and_random_tokens_do_not_change_password(self):
        token = self.token()
        self.now += timedelta(seconds=901)
        self.submit(token, status=400)
        self.submit("z" * 43, status=400)
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            self.assertEqual(user.auth_version, 0)
            self.assertTrue(verify_password(self.credentials["password"], user.password_hash))

    def test_success_revokes_sessions_and_token_without_auto_login(self):
        token = self.token()
        response = self.submit(token)
        self.assertEqual(response.json(), {"message": reset.RESET_MESSAGE})
        self.submit(token, status=400)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/refresh",
                                        json={"refresh_token": self.tokens["refresh_token"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json=self.credentials).status_code, 401)
        login = self.client.post("/api/auth/login", json={**self.credentials, "password": NEW_PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.assertIn("access_token", login.json())

    def test_reissue_invalidates_old_link(self):
        first = self.token()
        self.now += timedelta(seconds=61)
        second = self.token()
        self.assertFalse(first == second)
        self.submit(first, status=400)
        self.submit(second)

    def test_enabled_mfa_and_recovery_survive(self):
        secret = self.client.post("/api/auth/mfa/setup", json={"password": self.credentials["password"]}).json()["secret"]
        enabled = self.client.post("/api/auth/mfa/enable", json={"code": pyotp.TOTP(secret).at(self.now)}).json()
        self.client.headers["Authorization"] = "Bearer " + enabled["access_token"]
        challenge = self.client.post("/api/auth/login", json=self.credentials).json()["challenge_token"]
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            previous = (user.mfa_secret, user.mfa_last_step, list(user.mfa_recovery_hashes))
            user.mfa_failures = 2
            db.commit()
        self.submit(self.token())
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            self.assertTrue(user.mfa_enabled)
            self.assertTrue((user.mfa_secret, user.mfa_last_step, user.mfa_recovery_hashes) == previous)
            self.assertEqual(user.mfa_failures, 2)
            self.assertEqual(db.query(MFAChallenge).filter_by(user_id=self.uid).count(), 0)
        self.assertEqual(self.client.post("/api/auth/mfa/verify", json={
            "challenge_token": challenge, "code": enabled["recovery_codes"][0]}).status_code, 401)
        login = self.client.post("/api/auth/login", json={**self.credentials, "password": NEW_PASSWORD}).json()
        self.assertTrue(login["mfa_required"])
        self.assertNotIn("access_token", login)
        verified = self.client.post("/api/auth/mfa/verify", json={
            "challenge_token": login["challenge_token"], "code": enabled["recovery_codes"][0]})
        self.assertEqual(verified.status_code, 200)

    def test_pending_mfa_setup_is_cleared(self):
        self.client.post("/api/auth/mfa/setup", json={"password": self.credentials["password"]})
        self.submit(self.token())
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            self.assertIsNone(user.mfa_pending_secret)
            self.assertIsNone(user.mfa_pending_expires_at)
            self.assertFalse(user.mfa_enabled)

    def test_new_auth_version_invalidates_reset_link(self):
        token = self.token()
        with SessionLocal() as db:
            user = db.get(User, self.uid)
            user.auth_version += 1
            db.commit()
        self.submit(token, status=400)

    def test_smtp_failure_is_private_and_cleans_token(self):
        self.mail.side_effect = RuntimeError("private SMTP response with recipient and credentials")
        with self.assertLogs("services.password_reset", level="WARNING") as output:
            failed = self.forgot()
        self.assertEqual(failed.json(), self.forgot("unknown@example.com").json())
        self.assertNotIn("private SMTP", " ".join(output.output))
        with SessionLocal() as db:
            self.assertEqual(db.query(PasswordResetToken).filter_by(user_id=self.uid).count(), 0)
            self.assertEqual(db.query(PasswordResetMailSlot).filter(PasswordResetMailSlot.owner.isnot(None)).count(), 0)
        self.assertEqual(self.client.post("/api/auth/login", json=self.credentials).status_code, 200)

    def test_password_policy_and_validation_do_not_echo_secrets(self):
        token = self.token()
        for weak in ("short", "a" * 15, "1234567890123", "Password1234", "漢字文" * 9, "x" * 73, "safe-prefix\x00secret"):
            with self.subTest(length=len(weak)):
                response = self.submit(token, weak, 422)
                self.assertNotIn(token, response.text)
                self.assertNotIn(weak, response.text)
        oversized = "private-token-" * 20
        self.assertNotIn(oversized, self.submit(oversized, status=422).text)
        self.submit(token, "Abcd123!" * 9)  # Exactly 72 UTF-8 bytes.

    def test_old_delivery_failure_cannot_delete_new_reset_token(self):
        newer = []
        def failure_after_reissue(*args):
            self.now += timedelta(seconds=61)
            self.mail.side_effect = None
            newer.append(self.token())
            return False
        self.mail.side_effect = failure_after_reissue
        with self.assertLogs("services.password_reset", level="WARNING"):
            self.forgot()
        self.submit(newer[0])

    def test_invalid_unicode_password_is_rejected_privately(self):
        token = self.token()
        response = self.submit(token, "invalid-password-\ud800", 422)
        self.assertNotIn(token, response.text)
        self.submit(token)

    def test_per_email_and_global_limits_persist_for_unknown_addresses(self):
        email = "unknown-limit@example.com"
        for _ in range(5):
            self.forgot(email)
            self.now += timedelta(seconds=61)
        self.forgot(email)
        with SessionLocal() as db:
            self.assertEqual(db.get(PasswordResetRate, reset.digest(email)).count, 5)
            rate = db.get(PasswordResetRate, "global-hour")
            rate.count = reset.GLOBAL_HOURLY_LIMIT
            db.commit()
        limited = self.forgot("another-unknown@example.com")
        self.assertEqual(limited.json(), {"message": reset.REQUEST_MESSAGE})
        with SessionLocal() as db:
            self.assertIsNone(db.get(PasswordResetRate, reset.digest("another-unknown@example.com")))
        self.now += timedelta(hours=1)
        self.forgot("another-unknown@example.com")
        with SessionLocal() as db:
            self.assertEqual(db.get(PasswordResetRate, reset.digest("another-unknown@example.com")).count, 1)

    def test_global_minute_limit_and_bounded_slots(self):
        deliveries = []
        for index in range(4):
            with SessionLocal() as db:
                deliveries.append(reset.reserve_delivery(db, f"slot-{index}@example.com"))
        self.assertTrue(all(deliveries))
        with SessionLocal() as db:
            self.assertIsNone(reset.reserve_delivery(db, "no-slot@example.com"))
        self.now += timedelta(seconds=61)
        with SessionLocal() as db:
            replacement = reset.reserve_delivery(db, "replacement@example.com")
        self.assertIsNotNone(replacement)
        reset.deliver_reset("slot-0@example.com", reset_mail.configuration(), *deliveries[0])
        with SessionLocal() as db:
            self.assertTrue(db.get(PasswordResetMailSlot, replacement[0]).owner == replacement[1])
            db.get(PasswordResetRate, "global-minute").count = reset.GLOBAL_MINUTE_LIMIT
            db.commit()
        self.forgot("minute-limited@example.com")
        with SessionLocal() as db:
            self.assertIsNone(db.get(PasswordResetRate, reset.digest("minute-limited@example.com")))

    def test_concurrent_reset_is_single_use(self):
        token = self.token()
        barrier = threading.Barrier(2)
        def submit_once(_):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.post("/api/auth/password/reset",
                                   json={"token": token, "new_password": NEW_PASSWORD}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(submit_once, range(2))), [200, 400])
        with SessionLocal() as db:
            self.assertEqual(db.get(User, self.uid).auth_version, 1)

    def test_background_lookup_starts_after_response_body(self):
        sent = []
        def delivery(*args):
            self.assertTrue(any(event["type"] == "http.response.body" and not event.get("more_body") for event in sent))
        async def invoke():
            body_read = False
            async def receive():
                nonlocal body_read
                if not body_read:
                    body_read = True
                    return {"type": "http.request", "body": json.dumps({"email": self.credentials["email"]}).encode()}
                await anyio.sleep_forever()
            async def send(event):
                sent.append(event)
            await app({"type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
                       "path": "/api/auth/password/forgot", "raw_path": b"/api/auth/password/forgot",
                       "query_string": b"", "headers": [(b"content-type", b"application/json")],
                       "server": ("testserver", 443), "client": ("127.0.0.1", 1234)}, receive, send)
        with patch("services.password_reset.deliver_reset", side_effect=delivery) as mock:
            anyio.run(invoke)
        mock.assert_called_once()


class SMTPTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, MAIL_ENV)
        environment.start()
        self.addCleanup(environment.stop)
        self.config = reset_mail.configuration()
        self.token = "t" * 43

    def test_ssl_certificates_and_fragment_link(self):
        with patch("services.reset_mail.smtplib.SMTP_SSL") as constructor:
            smtp = constructor.return_value
            smtp.send_message.return_value = {}
            reset_mail.send_smtp(self.config, "test@example.com", self.token)
            context = constructor.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(constructor.call_args.kwargs["timeout"], 5)
            message = smtp.send_message.call_args.args[0]
            self.assertIn(MAIL_ENV["PASSWORD_RESET_URL"] + "#token=" + self.token, message.get_content())
            self.assertNotIn("?token=", message.get_content())
            smtp.close.assert_called_once()

    def test_starttls_is_required_before_authentication(self):
        with patch.dict(os.environ, SMTP_TLS_MODE="starttls", SMTP_PORT="587"):
            config = reset_mail.configuration()
        with patch("services.reset_mail.smtplib.SMTP") as constructor:
            smtp = constructor.return_value
            smtp.send_message.return_value = {}
            reset_mail.send_smtp(config, "test@example.com", self.token)
            self.assertEqual([call[0] for call in smtp.method_calls],
                             ["ehlo", "starttls", "ehlo", "login", "send_message", "close"])
            context = smtp.starttls.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            smtp.reset_mock()
            smtp.starttls.side_effect = smtplib.SMTPNotSupportedError("STARTTLS unavailable")
            with self.assertRaises(smtplib.SMTPNotSupportedError):
                reset_mail.send_smtp(config, "test@example.com", self.token)
            smtp.login.assert_not_called()
            smtp.send_message.assert_not_called()

    def test_subprocess_has_hard_deadline_and_private_stdin(self):
        with patch("services.reset_mail.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(reset_mail.send_reset_mail(self.config, "test@example.com", self.token))
            self.assertNotIn(self.token, str(run.call_args.args))
            self.assertEqual(run.call_args.kwargs["timeout"], 20)
            self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
            run.side_effect = subprocess.TimeoutExpired(["python"], 20)
            self.assertFalse(reset_mail.send_reset_mail(self.config, "test@example.com", self.token))


if __name__ == "__main__":
    unittest.main()
