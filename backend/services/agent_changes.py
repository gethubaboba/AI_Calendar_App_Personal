"""Prepare immutable previews and apply them once in the owner's transaction."""
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from models import AgentProposal, Event, Note
from routers.events import _validate_interval, _sync_reminder
from schemas import EventCreate


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["create", "update", "delete"]
    kind: Literal["event", "note"]
    entry_id: int | None = Field(default=None, gt=0)
    fields: dict = Field(default_factory=dict)


COLUMNS = {"event": ("title", "date", "start_time", "end_time", "type", "description"),
           "note": ("title", "text", "date")}


def snapshot(item, kind):
    return {key: (v.isoformat() if hasattr(v, "isoformat") else v)
            for key in COLUMNS[kind] for v in [getattr(item, key)]}


def target(db, uid, change, lock=False):
    cls = Event if change.kind == "event" else Note
    query = db.query(cls).filter_by(id=change.entry_id, user_id=uid)
    item = (query.with_for_update() if lock else query).first()
    if item is None:
        raise ValueError("Запись не найдена")
    return item


def normalized(kind, fields):
    if any(isinstance(value, str) and "\x00" in value for value in fields.values()):
        raise ValueError("Текст содержит недопустимый символ")
    if kind == "event":
        value = EventCreate.model_validate(fields)
        _validate_interval(value.start_time, value.end_time)
        fields = value.model_dump(include=set(COLUMNS[kind]), mode="json")
    else:
        fields = {"title": "Без названия", "date": None, **fields}
        if fields["date"] is not None:
            fields["date"] = date.fromisoformat(fields["date"]).isoformat()
        if not isinstance(fields.get("text"), str) or not fields["text"].strip() or len(fields["text"]) > 5000:
            raise ValueError("Введите текст до 5000 символов")
    if not isinstance(fields.get("title"), str) or not fields["title"].strip() or len(fields["title"]) > 512:
        raise ValueError("Введите название до 512 символов")
    if len(fields.get("description") or "") > 5000:
        raise ValueError("Описание слишком длинное")
    return fields


def conflict(a, b):
    if a["date"] != b["date"]:
        return False
    if a["title"].strip().casefold() == b["title"].strip().casefold() and a["start_time"] == b["start_time"]:
        return True
    return bool(a["start_time"] and a["end_time"] and b["start_time"] and b["end_time"]
                and a["start_time"] < b["end_time"] and b["start_time"] < a["end_time"])


def prepare(db, uid, change):
    if (change.action == "create") != (change.entry_id is None):
        raise ValueError("Проверьте идентификатор записи")
    if set(change.fields) - set(COLUMNS[change.kind]) or (change.action == "delete" and change.fields):
        raise ValueError("Недопустимые поля")
    before = snapshot(target(db, uid, change), change.kind) if change.entry_id else None
    after = None
    if change.action != "delete":
        after = normalized(change.kind, {**(before or {}), **change.fields})
        if change.kind == "event":
            query = db.query(Event).filter_by(user_id=uid, date=date.fromisoformat(after["date"]))
            if change.entry_id:
                query = query.filter(Event.id != change.entry_id)
            if any(conflict(after, snapshot(other, "event")) for other in query):
                raise ValueError("Дубликат или пересечение времени")
    return {"action": change.action, "kind": change.kind, "entry_id": change.entry_id,
            "before": before, "after": after}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def save_preview(db, uid, changes):
    db.query(AgentProposal).filter(AgentProposal.expires_at <= utcnow()).delete()
    proposal = AgentProposal(id=secrets.token_urlsafe(32), user_id=uid, changes=changes,
                             expires_at=utcnow() + timedelta(minutes=10))
    db.add(proposal)
    db.commit()
    return {"id": proposal.id, "changes": changes}


def apply_preview(db, uid, proposal_id):
    proposal = db.query(AgentProposal).filter_by(id=proposal_id, user_id=uid).with_for_update().first()
    if proposal is None or proposal.expires_at <= utcnow():
        raise HTTPException(404, "Предложение истекло или уже использовано")
    # Serialize conflict checks with regular event writers during this short transaction.
    if db.get_bind().dialect.name == "postgresql" and any(c["kind"] == "event" for c in proposal.changes):
        db.execute(text("LOCK TABLE events IN SHARE ROW EXCLUSIVE MODE"))
    try:
        for row in proposal.changes:
            change = Change(action=row["action"], kind=row["kind"], entry_id=row["entry_id"],
                            fields=row["after"] or {})
            item = target(db, uid, change, lock=True) if change.entry_id else None
            if prepare(db, uid, change) != row:
                raise ValueError("Запись изменилась после предпросмотра")
            if change.action == "delete":
                db.delete(item)
            else:
                fields = change.fields.copy()
                if change.kind == "event":
                    fields = EventCreate(**fields).model_dump(include=set(COLUMNS["event"]))
                    item = item or Event(user_id=uid)
                else:
                    fields["date"] = date.fromisoformat(fields["date"]) if fields["date"] else None
                    item = item or Note(user_id=uid)
                for key, value in fields.items():
                    setattr(item, key, value)
                if change.kind == "event":
                    _sync_reminder(item)
                db.add(item)
            db.flush()
        count = len(proposal.changes)
        db.delete(proposal)
        db.commit()
        return {"applied": count}
    except (ValueError, HTTPException) as exc:
        db.rollback()
        raise HTTPException(409, "Данные изменились. Создайте новый предпросмотр.") from exc
