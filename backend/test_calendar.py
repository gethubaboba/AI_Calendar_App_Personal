"""Integration checks against a migrated database. Each test rolls back its transaction."""
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from db import engine, get_session
from main import app


class CalendarTest(unittest.TestCase):
    def setUp(self):
        connection = engine.connect()
        self.addCleanup(connection.close)
        transaction = connection.begin()
        self.addCleanup(transaction.rollback)
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        self.addCleanup(session.close)
        app.dependency_overrides[get_session] = lambda: session
        self.addCleanup(app.dependency_overrides.pop, get_session)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def call(self, method, path, status, **kwargs):
        response = self.client.request(method, "/api/" + path, **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if status != 204 else None

    def register(self):
        credentials = dict(email=f"{uuid4().hex}@example.com", password="test-password")
        token = self.call("POST", "auth/register", 201, json=dict(name="QA", **credentials))
        self.client.headers["Authorization"] = "Bearer " + token["access_token"]
        return credentials

    def test_calendar(self):
        self.register()
        foreign = self.call("POST", "templates", 201, json={"title": "Private"})["id"]
        credentials = self.register()
        own = self.call("POST", "templates", 201, json={"title": "Mine"})["id"]
        base = dict(title="Meeting", date="2026-11-10")
        for change in [dict(type="other"), dict(start_time="09:00"), dict(end_time="10:00"),
                       dict(start_time="10:00", end_time="10:00"), dict(start_time="11:00", end_time="10:00")]:
            self.call("POST", "events", 422, json=dict(base, **change))
        for template in [foreign, -1]:
            self.call("POST", "events", 404, json=dict(base, template_id=template))
        event = self.call("POST", "events", 201, json=dict(base, start_time="09:00", end_time="10:00", template_id=own))
        path = f"events/{event['id']}"
        self.call("PUT", path, 422, json=dict(start_time="11:00"))
        self.call("PUT", path, 422, json=dict(start_time=None))
        self.call("PUT", path, 422, json=dict(type=None))
        self.call("PUT", path, 200, json=dict(start_time="08:00"))
        self.call("PUT", path, 200, json=dict(start_time=None, end_time=None))
        self.assertEqual([], self.call("GET", "notifications?today=2026-11-09", 200))
        reminder, = self.call("GET", "notifications?today=2026-11-10", 200)
        self.assertTrue(self.call("PATCH", f"notifications/{reminder['id']}/read", 200)["is_read"])
        note = self.call("POST", "notes", 201, json=dict(text="Draft", note_date=base["date"]))
        self.call("PUT", f"notes/{note['id']}", 200, json=dict(text="Edited"))
        self.assertEqual(1, self.call("GET", "analytics", 200)["total_notes"])
        self.client.headers.clear()
        token = self.call("POST", "auth/login", 200, json=credentials)
        self.client.headers["Authorization"] = "Bearer " + token["access_token"]
        self.assertEqual(event["id"], self.call("GET", "events", 200)[0]["id"])
        self.assertEqual("Edited", self.call("GET", "notes", 200)[0]["text"])
        self.call("DELETE", path, 204)
        self.assertEqual([], self.call("GET", "notifications?today=2026-11-10", 200))
        self.call("DELETE", f"notes/{note['id']}", 204)
