"""
routers/events.py — CRUD-эндпоинты для событий.

GET    /api/events          — список событий пользователя за период
POST   /api/events          — создать событие
GET    /api/events/{id}     — получить событие по ID
PUT    /api/events/{id}     — обновить событие
DELETE /api/events/{id}     — удалить событие
"""

from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from db import get_session
import models
import schemas
from auth import get_current_user

router = APIRouter(prefix="/api/events", tags=["events"])


def _validate_interval(start: Optional[time], end: Optional[time]) -> None:
    if (start is None) != (end is None):
        raise HTTPException(422, "Укажите и начало, и конец интервала")
    if start is not None:
        if start.tzinfo is not None or end.tzinfo is not None:
            raise HTTPException(422, "Укажите местное время без часового пояса")
        if end <= start:
            raise HTTPException(422, "Конец должен быть позже начала")


def _sync_reminder(event: models.Event) -> None:
    reminder = next(iter(event.notifications), None)
    if reminder is None:
        reminder = models.Notification(user_id=event.user_id)
        event.notifications.append(reminder)
    scheduled = datetime.combine(event.date, time.min)
    message = f"{event.date:%d.%m.%Y} — {event.title}"
    if reminder.send_at != scheduled or reminder.message != message:
        reminder.send_at = scheduled
        reminder.message = message
        reminder.is_read = False


def _get_event_or_404(event_id: int, user_id: int, db: Session, lock: bool = False) -> models.Event:
    """Вспомогательная функция: находит событие или бросает 404."""
    query = db.query(models.Event).filter(
        models.Event.id == event_id,
        models.Event.user_id == user_id,
    )
    event = (query.with_for_update() if lock else query).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Событие не найдено")
    return event


@router.get("", response_model=List[schemas.EventOut])
def get_events(
    from_date: Optional[date] = Query(None, description="Начало диапазона дат (YYYY-MM-DD)"),
    to_date: Optional[date] = Query(None, description="Конец диапазона дат (YYYY-MM-DD)"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Возвращает события текущего пользователя за указанный период."""
    query = db.query(models.Event).filter(models.Event.user_id == current_user.id)
    if from_date:
        query = query.filter(models.Event.date >= from_date)
    if to_date:
        query = query.filter(models.Event.date <= to_date)
    return query.order_by(models.Event.date, models.Event.start_time).all()


@router.post("", response_model=schemas.EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    data: schemas.EventCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Создаёт новое событие для текущего пользователя."""
    _validate_interval(data.start_time, data.end_time)
    if data.template_id is not None:
        template = db.query(models.EventTemplate).filter_by(id=data.template_id, user_id=current_user.id).with_for_update().first()
        if template is None:
            raise HTTPException(404, "Шаблон не найден")
    event = models.Event(**data.model_dump(), user_id=current_user.id)
    _sync_reminder(event)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}", response_model=schemas.EventOut)
def get_event(
    event_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Возвращает событие по его ID."""
    return _get_event_or_404(event_id, current_user.id, db)


@router.put("/{event_id}", response_model=schemas.EventOut)
def update_event(
    event_id: int,
    data: schemas.EventUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Обновляет поля события. Передавать только изменяемые поля."""
    event = _get_event_or_404(event_id, current_user.id, db, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if any(changes.get(field, True) is None for field in ("type", "date", "title")):
        raise HTTPException(422, "Название, дата и тип обязательны")
    _validate_interval(changes.get("start_time", event.start_time), changes.get("end_time", event.end_time))
    for field, value in changes.items():
        setattr(event, field, value)
    _sync_reminder(event)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Удаляет событие по его ID."""
    event = _get_event_or_404(event_id, current_user.id, db)
    db.delete(event)
    db.commit()
