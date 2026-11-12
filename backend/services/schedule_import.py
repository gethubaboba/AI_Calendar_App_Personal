from datetime import datetime
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from pydantic import ValidationError

from services.agent_changes import Change, conflict, prepare, save_preview

MAX_BYTES = 512 * 1024
MAX_ROWS = 100
COLUMNS = {"title", "date", "start_time", "end_time", "type", "description"}


def sheet_rows(raw):
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Файл больше 512 КиБ")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            parts = archive.infolist()
            if len(parts) > 128 or sum(p.file_size for p in parts) > 4 * 1024 * 1024:
                raise HTTPException(413, "Слишком большой распакованный файл")
        book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        try:
            if len(book.worksheets) != 1:
                raise HTTPException(422, "Ожидается один лист")
            sheet = book.worksheets[0]
            sheet.reset_dimensions()
            rows = []
            for index, cells in enumerate(sheet.iter_rows(), 1):
                if index > MAX_ROWS + 1 or len(cells) > len(COLUMNS):
                    raise HTTPException(422, "Допустимо 100 строк и 6 столбцов")
                values = [cell.value for cell in cells]
                formula = any(cell.data_type in ("f", "e") for cell in cells if cell.value is not None)
                rows.append((index, values, formula))
            return rows
        finally:
            book.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Не удалось прочитать файл XLSX") from None


def preview_file(raw, uid, db):
    rows = sheet_rows(raw)
    if not rows:
        raise HTTPException(422, "Пустой лист")
    headers = rows[0][1]
    if (any(not isinstance(h, str) or h not in COLUMNS for h in headers)
            or len(set(headers)) != len(headers) or not {"title", "date"} <= set(headers)):
        raise HTTPException(422, "Проверьте заголовки столбцов: title и date обязательны")
    changes, errors, days = [], [], []
    for index, values, formula in rows[1:]:
        if not any(v is not None for v in values):
            continue
        try:
            if formula or len(values) > len(headers):
                raise ValueError("Формулы, ошибки Excel и лишние ячейки не поддерживаются")
            fields = {key: val for key, val in zip(headers, values) if val is not None}
            if isinstance(fields.get("date"), datetime):
                fields["date"] = fields["date"].date()
            change = prepare(db, uid, Change(action="create", kind="event", fields=fields))
            after = change["after"]
            if any(conflict(after, c["after"]) for c in changes):
                raise ValueError("Дубликат или пересечение внутри файла")
            days.append(datetime.fromisoformat(after["date"]).date())
            changes.append(change)
        except ValidationError:
            errors.append({"row": index, "error": "Некорректное название, дата, тип или время"})
        except (ValueError, TypeError, HTTPException) as exc:
            errors.append({"row": index, "error": getattr(exc, "detail", str(exc))})
    if days and (max(days) - min(days)).days > 365:
        raise HTTPException(422, "Расписание должно укладываться в один год")
    return {"proposal": save_preview(db, uid, changes) if changes else None, "errors": errors}
