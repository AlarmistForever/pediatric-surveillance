"""Редакционный контекст дайджеста: вручную проверенные КР РФ и мероприятия.

Модуль ничего не ищет в сети. Он:
  * валидирует локальный JSON (data/editorial_context.json);
  * загружает его в SQLite через upsert в одной транзакции (всё или ничего);
  * отбирает записи для очередного выпуска;
  * отмечает, какие записи уже были показаны.

Правило повторов (см. select_for_digest):
  запись показывается, пока её last_included_at пуст, либо совпадает с датой
  текущего выпуска. Второе нужно, чтобы повторная сборка письма в тот же день
  (например, после правки текста) давала тот же выпуск, а не «теряла» пункты.
  В следующий день запись уже не показывается. Новая редакция КР — это новая
  строка (UNIQUE(official_url, edition_or_version)), у неё last_included_at
  пуст, поэтому она попадёт в ближайший выпуск.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # sqlite3 нужен только функциям работы с БД (импорт внутри них),
    import sqlite3  # поэтому валидация и отбор работают и без драйвера SQLite.

# Россия с 2014 года не переходит на летнее время, Новосибирск — постоянно UTC+7.
# Фиксированное смещение вместо zoneinfo: на Windows без пакета tzdata
# ZoneInfo("Asia/Novosibirsk") недоступен.
NOVOSIBIRSK = dt.timezone(dt.timedelta(hours=7), "Новосибирск")

STATUSES = ("high", "important", "watch")
UPDATE_KINDS = ("new_edition", "substantial_update", "minor_update")
SHOWN_UPDATE_KINDS = ("new_edition", "substantial_update")
EVENT_KINDS = ("offline", "hybrid", "online")

# Поля, которыми управляет только конвейер; во входном файле их быть не должно,
# иначе редактор мог бы случайно «обнулить» историю показов.
MANAGED_FIELDS = ("id", "first_included_at", "last_included_at")

GUIDELINE_REQUIRED = ("title", "summary", "practical_meaning", "status", "update_kind", "official_url",
                      "source_name", "edition_or_version", "published_or_updated_at", "verified_at")
GUIDELINE_OPTIONAL: tuple[str, ...] = ()

EVENT_REQUIRED = ("title", "description", "event_kind", "starts_at", "timezone", "organizer",
                  "official_url", "verified_at", "status")
# Ключ обязан присутствовать, значение может быть null: редактор явно
# подтверждает, что стоимость / НМО не указаны или не подтверждены.
EVENT_EXPLICIT_NULLABLE = ("cost", "cme_credits")
EVENT_OPTIONAL = ("ends_at", "city", "venue", "registration_url")

MAX_LEN = {"title": 300, "edition_or_version": 200, "timezone": 60}
DEFAULT_MAX_LEN = 3000

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)$")


class ContextValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Файл контекста отклонён:\n- " + "\n- ".join(errors))


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------

def is_web_url(value) -> bool:
    if not isinstance(value, str) or value != value.strip() or re.search(r"[\s\x00-\x1f\x7f]", value):
        return False
    parsed = urlparse(value)
    # "@" в netloc (user:pass@host) запрещаем: так маскируют реальный адрес.
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and "@" not in parsed.netloc


def _text(errors, where, record, key, required=True):
    value = record.get(key)
    if value is None:
        if required:
            errors.append(f"{where}.{key}: обязательное поле пусто или отсутствует")
        return None
    if not isinstance(value, str):
        errors.append(f"{where}.{key}: ожидается строка")
        return None
    value = value.strip()
    if not value:
        # Пустую строку не принимаем даже в необязательных полях: «не указано»
        # должно быть записано явным null, а не случайно пустым значением.
        errors.append(f"{where}.{key}: пустая строка; используйте null, если значение не указано")
        return None
    if len(value) > MAX_LEN.get(key, DEFAULT_MAX_LEN):
        errors.append(f"{where}.{key}: слишком длинное значение")
    return value


def _url(errors, where, record, key, required=True):
    value = _text(errors, where, record, key, required)
    if value is not None and not is_web_url(value):
        errors.append(f"{where}.{key}: разрешены только http/https-адреса")
        return None
    return value


def _date(errors, where, record, key):
    value = _text(errors, where, record, key)
    if value is None:
        return None
    try:
        if not DATE_RE.match(value):
            raise ValueError
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        errors.append(f"{where}.{key}: ожидается дата YYYY-MM-DD")
        return None


def parse_when(value: str) -> dt.date | dt.datetime:
    """Дата (весь день) или время со смещением. Время без смещения запрещено."""
    if DATE_RE.match(value):
        return dt.date.fromisoformat(value)
    if DATETIME_RE.match(value):
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(value)


def _canonical_when(value: dt.date | dt.datetime) -> str:
    # Канонизация важна для UNIQUE(official_url, starts_at): "10:00+03:00" и
    # "10:00:00+03:00" должны давать одну и ту же строку.
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="minutes")
    return value.isoformat()


def _when(errors, where, record, key, required=True):
    value = _text(errors, where, record, key, required)
    if value is None:
        return None
    try:
        return parse_when(value)
    except ValueError:
        errors.append(f"{where}.{key}: ожидается YYYY-MM-DD или YYYY-MM-DDTHH:MM+03:00 (время — только со смещением)")
        return None


def _choice(errors, where, record, key, allowed):
    value = _text(errors, where, record, key)
    if value is not None and value not in allowed:
        errors.append(f"{where}.{key}: допустимо {', '.join(allowed)}")
        return None
    return value


def _check_keys(errors, where, record, allowed):
    for key in record:
        if key in MANAGED_FIELDS:
            errors.append(f"{where}.{key}: поле заполняет конвейер, во входном файле его быть не должно")
        elif key not in allowed:
            errors.append(f"{where}.{key}: неизвестное поле (опечатка?)")


def _validate_guideline(errors, where, record) -> dict:
    _check_keys(errors, where, record, GUIDELINE_REQUIRED + GUIDELINE_OPTIONAL)
    out = {key: _text(errors, where, record, key) for key in
           ("title", "summary", "practical_meaning", "source_name", "edition_or_version")}
    out["status"] = _choice(errors, where, record, "status", STATUSES)
    out["update_kind"] = _choice(errors, where, record, "update_kind", UPDATE_KINDS)
    out["official_url"] = _url(errors, where, record, "official_url")
    out["published_or_updated_at"] = _date(errors, where, record, "published_or_updated_at")
    out["verified_at"] = _date(errors, where, record, "verified_at")
    return out


def _validate_event(errors, where, record) -> dict:
    _check_keys(errors, where, record, EVENT_REQUIRED + EVENT_EXPLICIT_NULLABLE + EVENT_OPTIONAL)
    out = {key: _text(errors, where, record, key) for key in ("title", "description", "timezone", "organizer")}
    out["event_kind"] = _choice(errors, where, record, "event_kind", EVENT_KINDS)
    out["status"] = _choice(errors, where, record, "status", STATUSES)
    out["official_url"] = _url(errors, where, record, "official_url")
    out["registration_url"] = _url(errors, where, record, "registration_url", required=False)
    out["verified_at"] = _date(errors, where, record, "verified_at")
    for key in EVENT_EXPLICIT_NULLABLE:
        if key not in record:
            errors.append(f"{where}.{key}: ключ обязателен; укажите null, если значение не указано или не подтверждено")
        out[key] = _text(errors, where, record, key, required=False)
    out["city"] = _text(errors, where, record, "city", required=False)
    out["venue"] = _text(errors, where, record, "venue", required=False)
    if out["event_kind"] in ("offline", "hybrid") and not out["city"]:
        errors.append(f"{where}.city: для очного/гибридного мероприятия нужен город")
    starts = _when(errors, where, record, "starts_at")
    ends = _when(errors, where, record, "ends_at", required=False)
    if starts is not None and ends is not None:
        if isinstance(starts, dt.datetime) != isinstance(ends, dt.datetime):
            errors.append(f"{where}.ends_at: формат должен совпадать с starts_at (обе даты или оба времени)")
        elif ends < starts:
            errors.append(f"{where}.ends_at: окончание раньше начала")
    out["starts_at"] = _canonical_when(starts) if starts is not None else None
    out["ends_at"] = _canonical_when(ends) if ends is not None else None
    return out


def validate(payload) -> dict:
    """Проверяет весь файл целиком и возвращает нормализованные записи.

    Ошибки собираются все сразу, чтобы редактор исправил файл за один проход.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise ContextValidationError(["корень файла должен быть объектом {\"guidelines\": [], \"events\": []}"])
    for key in payload:
        if key not in ("guidelines", "events"):
            errors.append(f"{key}: неизвестный раздел")
    result: dict[str, list[dict]] = {"guidelines": [], "events": []}
    for section, validator, unique in (
        ("guidelines", _validate_guideline, ("official_url", "edition_or_version")),
        ("events", _validate_event, ("official_url", "starts_at")),
    ):
        items = payload.get(section)
        if not isinstance(items, list):
            errors.append(f"{section}: ожидается массив (может быть пустым)")
            continue
        seen = set()
        for i, record in enumerate(items):
            where = f"{section}[{i}]"
            if not isinstance(record, dict):
                errors.append(f"{where}: ожидается объект")
                continue
            clean = validator(errors, where, record)
            key = tuple(clean.get(k) for k in unique)
            if all(key):
                if key in seen:
                    errors.append(f"{where}: дубликат по {' + '.join(unique)}")
                seen.add(key)
            result[section].append(clean)
    if errors:
        raise ContextValidationError(errors)
    return result


def load_json(path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContextValidationError([f"файл не найден: {path}"]) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContextValidationError([f"некорректный JSON: {exc}"]) from None
    return validate(payload)


# ---------------------------------------------------------------------------
# Загрузка в SQLite
# ---------------------------------------------------------------------------

GUIDELINE_UPSERT = """
INSERT INTO guideline_updates(title, summary, practical_meaning, status, update_kind, official_url,
    source_name, edition_or_version, published_or_updated_at, verified_at)
VALUES(:title, :summary, :practical_meaning, :status, :update_kind, :official_url,
    :source_name, :edition_or_version, :published_or_updated_at, :verified_at)
ON CONFLICT(official_url, edition_or_version) DO UPDATE SET
    title=excluded.title, summary=excluded.summary, practical_meaning=excluded.practical_meaning,
    status=excluded.status, update_kind=excluded.update_kind, source_name=excluded.source_name,
    published_or_updated_at=excluded.published_or_updated_at, verified_at=excluded.verified_at
"""
# first/last_included_at при обновлении не трогаем: правка текста той же
# редакции — не повод показывать её снова. Для повторного показа нужна новая
# edition_or_version.

EVENT_UPSERT = """
INSERT INTO events(title, description, event_kind, starts_at, ends_at, timezone, city, venue, organizer,
    cost, cme_credits, registration_url, official_url, verified_at, status)
VALUES(:title, :description, :event_kind, :starts_at, :ends_at, :timezone, :city, :venue, :organizer,
    :cost, :cme_credits, :registration_url, :official_url, :verified_at, :status)
ON CONFLICT(official_url, starts_at) DO UPDATE SET
    title=excluded.title, description=excluded.description, event_kind=excluded.event_kind,
    ends_at=excluded.ends_at, timezone=excluded.timezone, city=excluded.city, venue=excluded.venue,
    organizer=excluded.organizer, cost=excluded.cost, cme_credits=excluded.cme_credits,
    registration_url=excluded.registration_url, verified_at=excluded.verified_at, status=excluded.status
"""


def import_context(conn: sqlite3.Connection, path: str | Path) -> dict:
    """Валидирует файл и загружает его; при любой ошибке база не меняется."""
    data = load_json(path)  # бросает ContextValidationError до любого обращения к БД
    import sqlite3
    counts = {"guidelines_inserted": 0, "guidelines_updated": 0, "events_inserted": 0, "events_updated": 0}
    try:
        with conn:  # одна транзакция: commit при успехе, rollback при исключении
            for record in data["guidelines"]:
                exists = conn.execute("SELECT 1 FROM guideline_updates WHERE official_url=? AND edition_or_version=?",
                                      (record["official_url"], record["edition_or_version"])).fetchone()
                conn.execute(GUIDELINE_UPSERT, record)
                counts["guidelines_updated" if exists else "guidelines_inserted"] += 1
            for record in data["events"]:
                exists = conn.execute("SELECT 1 FROM events WHERE official_url=? AND starts_at=?",
                                      (record["official_url"], record["starts_at"])).fetchone()
                conn.execute(EVENT_UPSERT, record)
                counts["events_updated" if exists else "events_inserted"] += 1
    except sqlite3.IntegrityError as exc:
        raise ContextValidationError([f"база отклонила запись: {exc}"]) from None
    return counts


# ---------------------------------------------------------------------------
# Отбор для выпуска
# ---------------------------------------------------------------------------

def issue_date_for(generated_at: dt.datetime) -> str:
    """Дата выпуска считается по Новосибирску, где живёт читатель письма."""
    if generated_at.tzinfo is None:
        generated_at = generated_at.astimezone()
    return generated_at.astimezone(NOVOSIBIRSK).date().isoformat()


def _not_yet_shown(row: dict, issue_date: str) -> bool:
    return row.get("last_included_at") in (None, issue_date)


def _event_not_finished(row: dict, generated_at: dt.datetime) -> bool:
    end = parse_when(row.get("ends_at") or row["starts_at"])
    if isinstance(end, dt.datetime):
        return end >= generated_at
    # Для «дневных» событий сравниваем с датой по Новосибирску.
    return end.isoformat() >= issue_date_for(generated_at)


def select_for_digest(guidelines: list[dict], events: list[dict], generated_at: dt.datetime) -> dict:
    """Чистая функция отбора; не зависит от SQLite, поэтому легко тестируется."""
    if generated_at.tzinfo is None:
        generated_at = generated_at.astimezone()
    issue_date = issue_date_for(generated_at)
    rank = {s: i for i, s in enumerate(STATUSES)}
    shown_guidelines = [g for g in guidelines
                        if g.get("update_kind", "new_edition") in SHOWN_UPDATE_KINDS and _not_yet_shown(g, issue_date)]
    # Сначала более свежие, затем стабильная сортировка по статусу (high → watch).
    shown_guidelines.sort(key=lambda g: g["published_or_updated_at"], reverse=True)
    shown_guidelines.sort(key=lambda g: rank.get(g["status"], len(rank)))
    def start_key(e):
        start = parse_when(e["starts_at"])
        if isinstance(start, dt.datetime):
            return start.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return dt.datetime.combine(start, dt.time.min)

    candidates = [e for e in events
                  if _not_yet_shown(e, issue_date) and _event_not_finished(e, generated_at)]

    # Одно и то же мероприятие РМАНПО может повторяться несколько раз в году.
    # В выпуске показываем только ближайшую ещё не прошедшую дату, чтобы старые
    # и дублирующие даты не конкурировали с актуальной записью.
    nearest_by_event: dict[tuple[str, str], dict] = {}
    for event in candidates:
        key = (event["title"].strip().casefold(), event["official_url"])
        previous = nearest_by_event.get(key)
        if previous is None or start_key(event) < start_key(previous):
            nearest_by_event[key] = event
    shown_events = list(nearest_by_event.values())

    shown_events.sort(key=start_key)
    return {"issue_date": issue_date, "guidelines": shown_guidelines, "events": shown_events}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def load_for_digest(conn: sqlite3.Connection, generated_at: dt.datetime) -> dict:
    """Читает контекст (работает и на read-only соединении).

    Если таблиц ещё нет (контекст ни разу не импортировали), разделы просто
    пустые — digest при этом не создаёт таблицы и не пишет в базу.
    """
    guidelines = events = []
    if _table_exists(conn, "guideline_updates"):
        guidelines = [dict(r) for r in conn.execute("SELECT * FROM guideline_updates")]
    if _table_exists(conn, "events"):
        events = [dict(r) for r in conn.execute("SELECT * FROM events")]
    return select_for_digest(guidelines, events, generated_at)


def mark_included(conn: sqlite3.Connection, selected: dict) -> dict:
    """Отмечает показанные записи датой выпуска (идемпотентно для той же даты)."""
    issue_date = selected["issue_date"]
    with conn:
        for table, rows in (("guideline_updates", selected["guidelines"]), ("events", selected["events"])):
            for row in rows:
                conn.execute(
                    f"UPDATE {table} SET first_included_at=COALESCE(first_included_at, ?), last_included_at=? WHERE id=?",
                    (issue_date, issue_date, row["id"]),
                )
    return {"issue_date": issue_date, "guidelines": len(selected["guidelines"]), "events": len(selected["events"])}
