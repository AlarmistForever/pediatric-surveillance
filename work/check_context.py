"""Проверка редакционного контекста (КР РФ и мероприятия) в пользовательском digest.

Работает только на ВРЕМЕННОЙ КОПИИ базы: рабочая data/clean.sqlite3 не
меняется (это проверяется по sha256 до и после). Сетевых запросов нет,
письма не отправляются. Все тестовые записи — выдуманные, на example.org.

    python work\\check_context.py --db data\\clean.sqlite3
    python work\\check_context.py --pure-only      # без SQLite: валидация и рендер
    python work\\check_context.py --keep           # не удалять временную папку
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import email
import email.policy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pediatric_surveillance import context, presentation  # noqa: E402

MSK = dt.timezone(dt.timedelta(hours=3))
NSK = context.NOVOSIBIRSK
# Тестовые «часы»: выпуски D1, D2, D3 (утро по Новосибирску).
D1 = dt.datetime(2030, 3, 1, 7, 0, tzinfo=NSK)
D2 = D1 + dt.timedelta(days=1)
D3 = D1 + dt.timedelta(days=2)

T_GUIDE = "ТЕСТ: условная клиническая рекомендация (не существует)"
T_GUIDE_MINOR = "ТЕСТ: мелкая правка условной рекомендации (не должна выводиться)"
T_OFFLINE = "ТЕСТ: условная очная конференция"
T_HYBRID = "ТЕСТ: условный гибридный семинар"
T_ONLINE = "ТЕСТ: условный вебинар"
T_PAST = "ТЕСТ: прошедший вебинар (не должен выводиться)"

FIXTURE = {
    "guidelines": [
        {
            "title": T_GUIDE,
            "summary": "Тестовое описание изменений в новой редакции.",
            "practical_meaning": "Тестовый практический вывод для проверки вёрстки.",
            "status": "important",
            "update_kind": "new_edition",
            "official_url": "https://example.org/test-guideline",
            "source_name": "Тестовый источник",
            "edition_or_version": "test-v1",
            "published_or_updated_at": "2030-02-20",
            "verified_at": "2030-02-25",
        },
        {
            "title": T_GUIDE_MINOR,
            "summary": "Тестовая мелкая правка.",
            "practical_meaning": "Не должна попасть в письмо.",
            "status": "watch",
            "update_kind": "minor_update",
            "official_url": "https://example.org/test-guideline-minor",
            "source_name": "Тестовый источник",
            "edition_or_version": "test-minor-1",
            "published_or_updated_at": "2030-02-21",
            "verified_at": "2030-02-25",
        },
    ],
    "events": [
        {
            "title": T_OFFLINE,
            "description": "Тестовое очное мероприятие без подтверждённой цены и НМО.",
            "event_kind": "offline",
            "starts_at": "2030-03-10",
            "ends_at": "2030-03-11",
            "timezone": "время площадки (тест)",
            "city": "Тестоград",
            "venue": "Тестовая площадка",
            "organizer": "Тестовый организатор",
            "cost": None,
            "cme_credits": None,
            "registration_url": None,
            "official_url": "https://example.org/test-offline",
            "verified_at": "2030-02-25",
            "status": "watch",
        },
        {
            "title": T_HYBRID,
            "description": "Тестовое гибридное мероприятие.",
            "event_kind": "hybrid",
            "starts_at": "2030-03-12T10:00+03:00",
            "ends_at": "2030-03-12T12:00:00+03:00",
            "timezone": "МСК (тест)",
            "city": "Тестоград",
            "venue": None,
            "organizer": "Тестовый организатор",
            "cost": "тестовая стоимость",
            "cme_credits": "тестовые баллы",
            "registration_url": "https://example.org/test-hybrid/register",
            "official_url": "https://example.org/test-hybrid",
            "verified_at": "2030-02-25",
            "status": "important",
        },
        {
            "title": T_ONLINE,
            "description": "Тестовый онлайн-вебинар.",
            "event_kind": "online",
            "starts_at": "2030-03-15T09:00+03:00",
            "ends_at": "2030-03-15T11:00+03:00",
            "timezone": "МСК (тест)",
            "organizer": "Тестовый организатор",
            "cost": None,
            "cme_credits": "тестовые баллы",
            "registration_url": "https://example.org/test-online/register?a=1&b=2",
            "official_url": "https://example.org/test-online",
            "verified_at": "2030-02-25",
            "status": "high",
        },
        {
            "title": T_PAST,
            "description": "Тестовый вебинар в прошлом.",
            "event_kind": "online",
            "starts_at": "2030-02-01T10:00+03:00",
            "timezone": "МСК (тест)",
            "organizer": "Тестовый организатор",
            "cost": None,
            "cme_credits": None,
            "official_url": "https://example.org/test-past",
            "verified_at": "2030-01-25",
            "status": "watch",
        },
    ],
}


def _bad_payloads() -> list[tuple[str, object]]:
    """Каждый вариант обязан быть отклонён целиком."""
    def g(**patch):
        p = copy.deepcopy(FIXTURE); p["guidelines"][0].update(patch); return p

    def e(i=0, drop=(), **patch):
        p = copy.deepcopy(FIXTURE); p["events"][i].update(patch)
        for k in drop:
            p["events"][i].pop(k)
        return p

    dup = copy.deepcopy(FIXTURE); dup["guidelines"].append(copy.deepcopy(dup["guidelines"][0]))
    return [
        ("корень — массив", []),
        ("нет раздела events", {"guidelines": []}),
        ("неизвестный раздел", {"guidelines": [], "events": [], "extra": []}),
        ("javascript: URL", g(official_url="javascript:alert(1)")),
        ("ftp URL", g(official_url="ftp://example.org/x")),
        ("file URL", e(official_url="file:///C:/x.html")),
        ("URL без хоста", g(official_url="https://")),
        ("URL с пробелом", e(registration_url="https://example.org/a b")),
        ("URL с user@host", g(official_url="https://user@example.org/")),
        ("пустой title", g(title="   ")),
        ("title = null", g(title=None)),
        ("пустая строка вместо null в cost", e(cost="")),
        ("недопустимый статус", g(status="urgent")),
        ("недопустимый update_kind", g(update_kind="patch")),
        ("недопустимый event_kind", e(event_kind="webinar")),
        ("нет ключа cost", e(drop=("cost",))),
        ("нет ключа cme_credits", e(drop=("cme_credits",))),
        ("управляемое поле last_included_at", e(last_included_at="2030-01-01")),
        ("неизвестное поле", g(url="https://example.org")),
        ("время без смещения", e(1, starts_at="2030-03-12T10:00")),
        ("окончание раньше начала", e(1, ends_at="2030-03-12T09:00+03:00")),
        ("дата и время вперемешку", e(0, ends_at="2030-03-11T10:00+03:00")),
        ("очное без города", e(0, city=None)),
        ("кривая дата", g(published_or_updated_at="20.02.2030")),
        ("дубликат URL+редакция", dup),
        ("число вместо строки", g(summary=42)),
    ]


class Checker:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.passed = 0

    def ok(self, cond: bool, message: str) -> None:
        if cond:
            self.passed += 1
        else:
            self.errors.append(message)


# ---------------------------------------------------------------------------
# HTML-хелперы
# ---------------------------------------------------------------------------

SECTION_TITLES = {key: title for key, title in presentation.SECTIONS}


def html_sections(page: str) -> dict[str, str]:
    """Разбивает HTML по <h2> и возвращает {ключ раздела: html раздела}."""
    parts = re.split(r"<h2\b[^>]*>(.*?)</h2>", page, flags=re.S)
    by_title = {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    out = {}
    for key, title in SECTION_TITLES.items():
        if title in by_title:
            out[key] = by_title[title]
    return out


def hrefs(fragment: str) -> set[str]:
    import html as _html
    return {_html.unescape(h) for h in re.findall(r'<a\s[^>]*href="([^"]+)"', fragment)}


def fact(fragment: str, box_title: str, label: str) -> str | None:
    """Значение строки «label» в карточке мероприятия с заголовком box_title."""
    import html as _html
    start = fragment.find(_html.escape(box_title))
    if start < 0:
        return None
    end = fragment.find("</table>\n</td></tr>", start)
    box = fragment[start:end if end > 0 else None]
    m = re.search(rf">{re.escape(label)}</td><td[^>]*>(.*?)</td>", box, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


# ---------------------------------------------------------------------------
# Тесты без SQLite
# ---------------------------------------------------------------------------

def test_validation(c: Checker, tmp: Path) -> None:
    good = context.validate(copy.deepcopy(FIXTURE))
    c.ok(len(good["guidelines"]) == 2 and len(good["events"]) == 4, "валидный тестовый файл не прошёл валидацию")
    c.ok(good["events"][1]["ends_at"] == "2030-03-12T12:00+03:00", "starts_at/ends_at не канонизируются")
    c.ok(good["events"][0]["cost"] is None and good["events"][0]["cme_credits"] is None, "null в cost/НМО не сохраняется как None")
    for name, payload in _bad_payloads():
        try:
            context.validate(payload)
            c.ok(False, f"валидация пропустила некорректный файл: {name}")
        except context.ContextValidationError:
            c.ok(True, "")
    broken = tmp / "broken.json"
    broken.write_text('{"guidelines": [', encoding="utf-8")
    try:
        context.load_json(broken)
        c.ok(False, "битый JSON не отклонён")
    except context.ContextValidationError:
        c.ok(True, "")
    example = PROJECT_ROOT / "data" / "editorial_context.example.json"
    c.ok(context.load_json(example) == {"guidelines": [], "events": []}, "шаблон editorial_context.example.json не пустой")


def _as_rows(payload: dict) -> tuple[list[dict], list[dict]]:
    data = context.validate(copy.deepcopy(payload))
    gl = [{**r, "id": i, "first_included_at": None, "last_included_at": None} for i, r in enumerate(data["guidelines"], 1)]
    ev = [{**r, "id": i, "first_included_at": None, "last_included_at": None} for i, r in enumerate(data["events"], 1)]
    return gl, ev


def check_rendered_context(c: Checker, page: str, text: str, md: str, label: str) -> None:
    sec = html_sections(page)
    c.ok("ru_guidelines" in sec and T_GUIDE in sec["ru_guidelines"], f"{label}: КР не в разделе 🇷🇺")
    c.ok(T_GUIDE_MINOR not in page, f"{label}: minor_update КР попала в письмо")
    off, onl = sec.get("events_offline", ""), sec.get("events_online", "")
    c.ok(T_OFFLINE in off and T_HYBRID in off and T_ONLINE not in off, f"{label}: неверный состав раздела 📍")
    c.ok(T_ONLINE in onl and T_OFFLINE not in onl and T_HYBRID not in onl, f"{label}: неверный состав раздела 💻")
    c.ok(T_PAST not in page, f"{label}: прошедшее мероприятие попало в письмо")
    c.ok(fact(off, T_OFFLINE, "Стоимость") == "не указано", f"{label}: NULL-стоимость не показана как «не указано»")
    c.ok(fact(off, T_OFFLINE, "НМО/ЗЕТ") == "не указано", f"{label}: NULL-НМО не показано как «не указано»")
    c.ok(fact(off, T_OFFLINE, "Регистрация") == "не указано", f"{label}: пустая регистрация не показана как «не указано»")
    c.ok(fact(onl, T_ONLINE, "Стоимость") == "не указано", f"{label}: NULL-стоимость онлайн не «не указано»")
    c.ok(fact(off, T_HYBRID, "НМО/ЗЕТ") == "тестовые баллы", f"{label}: указанное НМО не выведено")
    c.ok(fact(onl, T_ONLINE, "По Новосибирску") == "15 марта 2030, 13:00–15:00", f"{label}: неверный пересчёт на время Новосибирска")
    c.ok(fact(off, T_OFFLINE, "Дата") == "10–11 марта 2030", f"{label}: неверная дата очного мероприятия")
    c.ok(fact(off, T_OFFLINE, "Где") == "Тестоград, Тестовая площадка", f"{label}: нет города/площадки")
    links = hrefs(page)
    for url in ("https://example.org/test-guideline", "https://example.org/test-offline",
                "https://example.org/test-hybrid/register", "https://example.org/test-hybrid",
                "https://example.org/test-online/register?a=1&b=2", "https://example.org/test-online"):
        c.ok(url in links, f"{label}: нет кликабельной ссылки {url}")
        c.ok(url in text, f"{label}: в plain-text нет URL {url}")
        c.ok(f"(<{url}>)" in md, f"{label}: в Markdown нет ссылки {url}")
    c.ok("&amp;b=2" in page, f"{label}: & в URL не экранирован в HTML")
    minute = sec.get("one_minute", "")
    items = re.findall(r"<li\b", minute)
    c.ok(2 <= len(items) <= 5, f"{label}: в «одной минуте» {len(items)} пунктов, ожидалось 2–5")
    h2_titles = [re.sub(r"<[^>]+>", "", t).strip() for t in re.findall(r"<h2\b[^>]*>(.*?)</h2>", page, re.S)]
    c.ok(bool(h2_titles) and h2_titles[-1] == SECTION_TITLES["one_minute"], f"{label}: «одна минута» не последний раздел")
    visible_html = re.sub(r'href="[^"]*"', "", page)
    visible_text = re.sub(r"https?://\S+", "", text)
    for word in ("verified_at", "first_included_at", "last_included_at", "event_kind", "update_kind",
                 "new_edition", "minor_update", "offline", "hybrid", "2030-02-25"):
        c.ok(word not in visible_html and word not in visible_text,
             f"{label}: техническое поле {word!r} попало в письмо")


def test_render_pure(c: Checker, tmp: Path) -> None:
    gl, ev = _as_rows(FIXTURE)
    selected = context.select_for_digest(gl, ev, D1)
    c.ok(selected["issue_date"] == "2030-03-01", "дата выпуска считается не по Новосибирску")
    issue = presentation.build_issue([], D1, selected)
    check_rendered_context(c, presentation.render_html(issue), presentation.render_text(issue),
                           presentation.render_markdown(issue), "pure")
    # Пустой контекст: новых разделов нет (и «минуты» нет, раз нет ни одного пункта).
    empty = presentation.render_html(presentation.build_issue([], D1, {"guidelines": [], "events": []}))
    for key in ("ru_guidelines", "events_offline", "events_online", "one_minute"):
        c.ok(SECTION_TITLES[key] not in empty, f"pure: пустой контекст создал раздел {SECTION_TITLES[key]}")
    # Повторы: отмеченные вчерашним выпуском записи не выбираются, сегодняшние — да.
    for r in gl + ev:
        r["last_included_at"] = "2030-03-01"
    again = context.select_for_digest(gl, ev, D1)
    c.ok(len(again["guidelines"]) == 1 and len(again["events"]) == 3, "pure: повторная сборка в тот же день потеряла пункты")
    next_day = context.select_for_digest(gl, ev, D2)
    c.ok(not next_day["guidelines"] and not next_day["events"], "pure: записи повторились на следующий день")


# ---------------------------------------------------------------------------
# Сквозной тест на копии SQLite
# ---------------------------------------------------------------------------

UPSTREAM_TABLES = ("runs", "queries", "works", "work_ids", "appraisals", "full_text_sources")


def upstream_fingerprint(conn) -> dict[str, str]:
    out = {}
    for table in UPSTREAM_TABLES:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        out[table] = hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()
    return out


def test_db_flow(c: Checker, db_src: Path, tmp: Path) -> None:
    import sqlite3
    from pediatric_surveillance import pipeline
    from pediatric_surveillance.db import connect

    db = tmp / "test-copy.sqlite3"
    shutil.copy2(db_src, db)
    ro = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    before = upstream_fingerprint(ro); ro.close()

    def write(name, payload) -> Path:
        path = tmp / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def count(table) -> int:
        conn = sqlite3.connect(db)
        try:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def run(day: dt.datetime, name: str, mark: bool = True) -> tuple[dict, str, str, str, email.message.EmailMessage]:
        res = pipeline.digest(str(db), str(tmp / name), mark_included=mark, generated_at=day)
        page = Path(res["html"]).read_text(encoding="utf-8")
        msg = email.message_from_bytes(Path(res["eml"]).read_bytes(), policy=email.policy.default)
        return res, page, Path(res["text"]).read_text(encoding="utf-8"), Path(res["markdown"]).read_text(encoding="utf-8"), msg

    # 0. Пустой контекст: до импорта digest работает и новых разделов не создаёт.
    res, page, *_ = run(D1 - dt.timedelta(days=1), "d0-before-import")
    for key in ("ru_guidelines", "events_offline", "events_online"):
        c.ok(SECTION_TITLES[key] not in page, f"db: без контекста появился раздел {SECTION_TITLES[key]}")
    c.ok(res["context_marked"] is None, "db: digest без контекста пытался писать в базу")

    conn = connect(str(db))
    try:
        c.ok(context.import_context(conn, PROJECT_ROOT / "data" / "editorial_context.example.json")
             == {"guidelines_inserted": 0, "guidelines_updated": 0, "events_inserted": 0, "events_updated": 0},
             "db: импорт пустого шаблона что-то изменил")
        # 1. Некорректные файлы отклоняются целиком, база не меняется.
        for name, payload in _bad_payloads()[:6]:
            try:
                context.import_context(conn, write("bad.json", payload))
                c.ok(False, f"db: импорт пропустил некорректный файл: {name}")
            except context.ContextValidationError:
                c.ok(True, "")
        c.ok(count("guideline_updates") == 0 and count("events") == 0, "db: частичный импорт некорректного файла")
    finally:
        conn.close()

    res, page, *_ = run(D1 - dt.timedelta(hours=12), "d0-empty-context")
    for key in ("ru_guidelines", "events_offline", "events_online"):
        c.ok(SECTION_TITLES[key] not in page, f"db: пустой контекст создал раздел {SECTION_TITLES[key]}")
    c.ok(SECTION_TITLES["one_minute"] in page, "db: нет «одной минуты» при наличии карточек публикаций")

    # 2. Импорт тестового контекста; повторный импорт не дублирует строки.
    fixture_path = write("fixture.json", FIXTURE)
    conn = connect(str(db))
    try:
        first = context.import_context(conn, fixture_path)
        second = context.import_context(conn, fixture_path)
    finally:
        conn.close()
    c.ok(first["guidelines_inserted"] == 2 and first["events_inserted"] == 4, f"db: неверный первый импорт {first}")
    c.ok(second["guidelines_updated"] == 2 and second["events_updated"] == 4 and count("events") == 4, "db: повторный импорт создал дубликаты")

    # 3. Предпросмотр не отмечает показ; выпуск D1 показывает всё и отмечает.
    res, page, *_ = run(D1, "d1-preview", mark=False)
    c.ok(res["context_marked"] is None and T_GUIDE in page, "db: предпросмотр работает неверно")
    res, page, text, md, msg = run(D1, "d1")
    check_rendered_context(c, page, text, md, "db D1")
    c.ok(res["context_marked"] == {"issue_date": "2030-03-01", "guidelines": 1, "events": 3}, f"db: неверная отметка показа {res['context_marked']}")
    c.ok(msg.get_content_type() == "multipart/alternative"
         and [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"], "db: .eml не multipart/alternative text+html")
    c.ok("https://example.org/test-online" in next(p for p in msg.iter_parts() if p.get_content_type() == "text/plain").get_content(),
         "db: в text/plain .eml нет обычного URL мероприятия")

    # Проверка публикационной части тем же скриптом, что и для обычного выпуска.
    import check_user_digest
    saved = sys.argv
    sys.argv = ["check_user_digest.py", res["html"], "--db", str(db)]
    try:
        c.ok(check_user_digest.main() == 0, "db D1: check_user_digest не прошёл")
    finally:
        sys.argv = saved

    # 4. Повторная сборка в тот же день — тот же состав (идемпотентно).
    res, page, *_ = run(D1 + dt.timedelta(hours=2), "d1-rerun")
    c.ok(T_GUIDE in page and T_ONLINE in page, "db: повторная сборка в тот же день потеряла пункты")

    # 5. Следующий день: уже включённое не повторяется.
    res, page, *_ = run(D2, "d2")
    for key in ("ru_guidelines", "events_offline", "events_online"):
        c.ok(SECTION_TITLES[key] not in page, f"db D2: повторился раздел {SECTION_TITLES[key]}")
    c.ok(res["context_marked"] is None, "db D2: отмечены записи, которых нет в выпуске")

    # 6. Правка текста той же редакции не возвращает КР; новая редакция — возвращает.
    updated = copy.deepcopy(FIXTURE)
    updated["guidelines"][0]["summary"] = "Тестовая правка текста той же редакции."
    new_edition = copy.deepcopy(FIXTURE["guidelines"][0])
    new_edition.update(edition_or_version="test-v2", title="ТЕСТ: новая редакция условной рекомендации",
                       published_or_updated_at="2030-03-02")
    updated["guidelines"].append(new_edition)
    conn = connect(str(db))
    try:
        context.import_context(conn, write("fixture-v2.json", updated))
        v1 = conn.execute("SELECT first_included_at, last_included_at FROM guideline_updates WHERE edition_or_version='test-v1'").fetchone()
    finally:
        conn.close()
    c.ok(tuple(v1) == ("2030-03-01", "2030-03-01"), f"db: импорт сбросил историю показа {tuple(v1)}")
    res, page, *_ = run(D3, "d3")
    guide = html_sections(page).get("ru_guidelines", "")
    c.ok("новая редакция условной рекомендации" in guide and T_GUIDE not in guide, "db D3: новая редакция КР не показана или показана старая")
    c.ok(SECTION_TITLES["events_online"] not in page, "db D3: мероприятия повторились")

    # 7. Upstream-таблицы копии не изменились.
    ro = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    after = upstream_fingerprint(ro); ro.close()
    for table in UPSTREAM_TABLES:
        c.ok(before[table] == after[table], f"db: изменилась upstream-таблица {table}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("data/clean.sqlite3"))
    ap.add_argument("--pure-only", action="store_true", help="только проверки без SQLite")
    ap.add_argument("--keep", action="store_true", help="не удалять временную папку с копией базы и выпусками")
    args = ap.parse_args()

    c = Checker()
    tmp = Path(tempfile.mkdtemp(prefix="ps-context-check-"))
    sha_before = hashlib.sha256(args.db.read_bytes()).hexdigest() if args.db.exists() else None
    try:
        test_validation(c, tmp)
        test_render_pure(c, tmp)
        if not args.pure_only:
            if sha_before is None:
                c.ok(False, f"база не найдена: {args.db}")
            else:
                test_db_flow(c, args.db, tmp)
                c.ok(hashlib.sha256(args.db.read_bytes()).hexdigest() == sha_before, f"{args.db} изменилась!")
    finally:
        if args.keep:
            print(f"Временная папка: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    if c.errors:
        print("FAIL:\n- " + "\n- ".join(c.errors))
        return 1
    scope = "без SQLite (--pure-only)" if args.pure_only else f"включая сквозной тест на копии {args.db}"
    print(f"OK: {c.passed} проверок, {scope}; рабочая база не изменена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
