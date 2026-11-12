"""Calendar agent checks using SQLite or an isolated PostgreSQL test database."""
import unittest
import os
from io import BytesIO
from types import SimpleNamespace
from openpyxl import Workbook
from datetime import date
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth import create_access_token
from db import Base, get_session
from main import app


class MCPTest(unittest.TestCase):
    def setUp(self):
        test_url = os.getenv("AGENT_TEST_DATABASE_URL")
        if test_url:
            self.engine = create_engine(test_url)
            connection = self.engine.connect()
            transaction = connection.begin()
            self.addCleanup(connection.close)
            self.addCleanup(transaction.rollback)
            self.sessions = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        else:
            self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                                        poolclass=StaticPool)
            Base.metadata.create_all(self.engine)
            self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as db:
            db.add_all([models.User(id=1, email="one@example.com", name="One"),
                        models.User(id=2, email="two@example.com", name="Two")])
            db.flush()
            mine = models.Event(user_id=1, title="Mine", date=date(2026, 11, 12), type="task")
            private = models.Event(user_id=2, title="Private", date=date(2026, 11, 12), type="task")
            db.add_all([mine, private])
            db.commit()
            self.mine, self.private = mine.id, private.id
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_session] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_session, None)
        self.engine.dispose()

    def test_auth_and_isolation(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "list_events",
                              "arguments": {"from_date": "2026-11-01", "to_date": "2026-11-30"}}}
        self.assertEqual(self.client.post("/api/agent/mcp", json=request).status_code, 401)
        headers = {"Authorization": "Bearer " + create_access_token(1)}
        response = self.client.post("/api/agent/mcp", json=request, headers=headers)
        items = response.json()["result"]["structuredContent"]["items"]
        self.assertEqual([item["title"] for item in items], ["Mine"])
        request["params"]["name"] = "delete_event"
        request["params"]["arguments"] = {"event_id": 1, "confirm": True}
        self.assertTrue(self.client.post("/api/agent/mcp", json=request, headers=headers).json()["result"]["isError"])
        with self.sessions() as db:
            self.assertEqual(db.query(models.Event).count(), 2)

    def test_unconfigured_model(self):
        headers = {"Authorization": "Bearer " + create_access_token(1)}
        with patch.dict("os.environ", {"AGENT_MODEL_BASE_URL": "", "AGENT_MODEL_NAME": ""}):
            response = self.client.post("/api/agent/chat", json={"message": "Совет"}, headers=headers)
        self.assertEqual(response.status_code, 503)

    def post(self, path, data, uid=1):
        return self.client.post("/api/agent/" + path, json=data,
                                headers={"Authorization": "Bearer " + create_access_token(uid)})

    def propose(self, **change):
        req = {"jsonrpc": "2.0", "method": "tools/call", "id": 1,
               "params": {"name": "propose_change", "arguments": change}}
        return self.post("mcp", req).json()["result"]

    def test_confirm_is_scoped_single_use_and_checks_snapshot(self):
        self.assertTrue(self.propose(action="delete", kind="event", entry_id=self.private)["isError"])
        proposal = self.propose(action="delete", kind="event", entry_id=self.mine)["structuredContent"]["items"]
        confirmation = {"proposal_id": proposal["id"]}
        self.assertEqual(self.post("confirm", {"confirm": True}).status_code, 422)
        self.assertEqual(self.post("confirm", confirmation, uid=2).status_code, 404)
        with self.sessions() as db:
            item = db.get(models.Event, self.mine)
            self.assertEqual(item.title, "Mine")
            item.title = "Edited elsewhere"
            db.commit()
        self.assertEqual(self.post("confirm", confirmation).status_code, 409)
        new = self.propose(action="delete", kind="event", entry_id=self.mine)["structuredContent"]["items"]
        self.assertEqual(self.post("confirm", {"proposal_id": new["id"]}).status_code, 200)
        self.assertEqual(self.post("confirm", {"proposal_id": new["id"]}).status_code, 404)

    def test_note_create_and_update(self):
        note_id = None
        for action, fields in [("create", {"text": "First"}), ("update", {"text": "Edited"})]:
            result = self.propose(kind="note", action=action, fields=fields,
                                  entry_id=note_id)
            pending = result["structuredContent"]["items"]
            self.assertEqual(self.post("confirm", {"proposal_id": pending["id"]}).json(), {"applied": 1})
            with self.sessions() as db:
                note_id = db.query(models.Note).filter_by(user_id=1).one().id
        with self.sessions() as db:
            self.assertEqual(db.get(models.Note, note_id).text, "Edited")

    def test_advice_cannot_prepare_or_apply_changes(self):
        fake = AsyncMock()
        call = SimpleNamespace(id="test", function=SimpleNamespace(name="propose_change",
            arguments='{"kind":"event","action":"delete","entry_id":1}'))
        msg = SimpleNamespace(tool_calls=[call], model_dump=lambda **kwargs: {"role":"assistant","content":""})
        fake.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        with patch.dict("os.environ", AGENT_MODEL_BASE_URL="http://localhost/v1", AGENT_MODEL_NAME="test"), patch(
                "routers.mcp_calendar.AsyncOpenAI", return_value=fake):
            self.assertEqual(self.post("chat", {"message":"Совет", "mode":"advice"}).status_code, 502)
        with self.sessions() as db:
            self.assertEqual(db.query(models.AgentProposal).count(), 0)
            self.assertEqual(db.query(models.Event).count(), 2)

    def test_event_update_and_invalid_text(self):
        for title in ["x" + " " * 512, "bad\x00text"]:
            self.assertTrue(self.propose(kind="event", action="update", entry_id=self.mine,
                                         fields={"title": title})["isError"])
        preview = self.propose(kind="event", action="update", entry_id=self.mine,
                               fields={"title": "Moved"})["structuredContent"]["items"]
        self.assertEqual(preview["changes"][0]["before"]["title"], "Mine")
        self.assertEqual(self.post("confirm", {"proposal_id": preview["id"]}).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.get(models.Event, self.mine).title, "Moved")

    def test_import_preview_and_apply(self):
        headers = {"Authorization": "Bearer " + create_access_token(1)}
        def upload(raw):
            return self.client.post("/api/agent/import", content=raw, headers=headers)
        self.assertEqual(upload(b"invalid").status_code, 422)
        self.assertEqual(upload(b"x" * 524289).status_code, 413)
        book = Workbook()
        for row in [("title","date","start_time","end_time"), ("Mine","2026-11-12"),
                    ("Lecture","2026-11-14","10:00","11:00"), ("Overlap","2026-11-14","10:30","11:30"),
                    ("=SUM(1,2)","2026-11-15"), ("Invalid","oops")]:
            book.active.append(row)
        stream = BytesIO()
        book.save(stream)
        result = upload(stream.getvalue()).json()
        self.assertEqual([e["row"] for e in result["errors"]], [2,4,5,6])
        with self.sessions() as db:
            self.assertEqual(db.query(models.Event).count(), 2)
        self.assertEqual(self.post("confirm", {"proposal_id": result["proposal"]["id"]}).json(), {"applied": 1})
        with self.sessions() as db:
            self.assertEqual(db.query(models.Event).count(), 3)
            self.assertEqual(db.query(models.Notification).count(), 1)


if __name__ == "__main__":
    unittest.main()
