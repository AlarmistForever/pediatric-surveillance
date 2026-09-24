"""Редакционная презентация готовых appraisal-результатов для врача.

Модуль ничего не ищет, не скринит и не оценивает. Он получает строки,
уже выбранные из SQLite (works + appraisals + ссылка на источник), и
превращает их в русскоязычный дайджест: Markdown, HTML-письмо,
plain-text и .eml (multipart/alternative).

Русский текст карточек хранится в PRESENTATION_PROFILES и привязан к
версии appraisal. Если для приоритетной работы нет профиля или версия
appraisal изменилась, сборка останавливается: лучше не выпустить
письмо, чем показать врачу английские внутренние поля или устаревший
пересказ.

Технические поля (health, run, screening, access/retrieval-статусы,
based_on, rationale, spin_flags, пути к файлам, abstract) сюда
намеренно не попадают.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import textwrap
from dataclasses import dataclass, field
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse

from . import context


# Версия appraisal, по которой написаны русские профили ниже.
PROFILE_APPRAISAL_VERSION = "2026-09-23-oa-1"


# ---------------------------------------------------------------------------
# Статусы
# ---------------------------------------------------------------------------

STATUSES = {
    "high": {"emoji": "🔴", "label": "высокий приоритет", "color": "#c62828", "bg": "#fdecea", "rank": 0},
    "important": {"emoji": "🟠", "label": "важно знать", "color": "#e65100", "bg": "#fff3e0", "rank": 1},
    "watch": {"emoji": "🟡", "label": "наблюдаем", "color": "#9a7b00", "bg": "#fff8d6", "rank": 2},
}

# Как оценка надёжности из appraisal называется для врача.
RELIABILITY_LABELS = {
    "low": "Низкий риск систематических ошибок",
    "some_concerns": "Умеренные сомнения",
    "serious_concerns": "Серьёзные сомнения",
    "not_fully_assessed": "Оценено не полностью",
}


def status_for(row, profile: dict) -> str:
    """Статус карточки выводится из уже готового appraisal, а не придумывается.

    🔴 — приоритетная работа высокой клинической значимости без существенных
         сомнений в надёжности (может менять практику);
    🟠 — приоритетная работа с умеренными сомнениями: важно знать, но это не
         основание менять практику;
    🟡 — всё остальное, в том числе серьёзные сомнения в надёжности.
    Профиль может явно переопределить статус полем ``status``.
    """
    if profile.get("status"):
        return profile["status"]
    action = _get(row, "actionability")
    reliability = _get(row, "reliability")
    relevance = _get(row, "clinical_relevance")
    if action == "digest_priority" and reliability == "low" and relevance == "high":
        return "high"
    if action == "digest_priority" and reliability == "some_concerns":
        return "important"
    return "watch"


# ---------------------------------------------------------------------------
# Разделы выпуска (порядок фиксирован; пустые разделы не выводятся)
# ---------------------------------------------------------------------------

SECTIONS = [
    ("main", "🔥 Главное"),
    ("ru_guidelines", "🇷🇺 Клинические рекомендации РФ"),
    ("events_offline", "📍 Очные и гибридные мероприятия"),
    ("events_online", "💻 Онлайн: можно участвовать из Новосибирска"),
    ("one_minute", "📌 Если сегодня есть только минута"),
]


# ---------------------------------------------------------------------------
# Русские профили карточек (редакционный пересказ appraisal 2026-09-23-oa-1)
# ---------------------------------------------------------------------------
# Правило: только то, что есть в appraisal. Числа, ДИ, I² и ограничения
# переносятся без округления и без усиления выводов.

PRESENTATION_PROFILES: dict[str, dict] = {
    "42764858": {
        "appraisal_version": "2026-09-23-oa-1",
        "title_ru": "Кортикостероиды при внебольничной пневмонии у детей: данных мало, пользы в объединённом анализе не показано",
        "design_ru": "Систематический обзор и метаанализ РКИ",
        "population_ru": "3 РКИ, 251 ребёнок до 18 лет (125 — кортикостероиды, 126 — контроль) с внебольничной пневмонией, обратившиеся за неотложной помощью",
        "studied": (
            "Добавление системных кортикостероидов к стандартному лечению в сравнении со стандартным "
            "лечением или плацебо. Исходы: клинические исходы по протоколам отдельных РКИ, длительность "
            "госпитализации, летальность и нежелательные явления."
        ),
        "result": [
            "Длительность госпитализации: разница средних −2,10 сут (95% ДИ от −6,79 до 2,59; I² = 91%). "
            "Интервал включает отсутствие эффекта, неоднородность между исследованиями очень высокая.",
            "Летальность: ОР 0,74 (95% ДИ 0,14–3,85) — статистически значимой разницы нет. "
            "Это не доказательство эквивалентности: интервал слишком широкий.",
            "Польза, описанная в отдельных РКИ, неоднородна. Наиболее отчётливый сигнал нежелательных "
            "явлений — транзиторная гипергликемия.",
        ],
        "trust": (
            "Оценка по полному тексту. Риск систематической ошибки в РКИ (RoB 2) авторы оценили как низкий, "
            "но включено всего 3 клинически разнородных РКИ; нет проспективной регистрации, "
            "3 отчёта получить не удалось, часть медиан пересчитана в средние, объединённые оценки неточны. "
            "Схемы терапии и фенотипы пациентов различаются — общий «эффект класса» из этих данных не следует."
        ),
        "meaning": (
            "Обзор не даёт оснований для рутинного назначения системных кортикостероидов детям с "
            "внебольничной пневмонией. Но и отсутствие эффекта не доказано: данных мало, и вопрос о пользе "
            "у отдельных фенотипов и при разной тяжести остаётся открытым. Если кортикостероиды "
            "рассматриваются, учитывайте риск гипергликемии."
        ),
        "ru_practice": (
            "С оговорками: заболевание и вмешательство актуальны, но структура тяжести и "
            "маршрутизация пациентов в исследованиях могут отличаться от российских. Вывод стоит сверить "
            "с действующими клиническими рекомендациями Минздрава РФ."
        ),
    },
    "42764851": {
        "appraisal_version": "2026-09-23-oa-1",
        "title_ru": "Программы контроля антимикробной терапии в неотложной помощи: сигнал снижения назначений, доказательства слабые",
        "design_ru": "Систематический обзор с нарративным синтезом (без метаанализа)",
        "population_ru": "12 завершённых исследований в пунктах неотложной помощи (взрослые, детские и смешанные); объём — от небольших детских когорт до 1,4 млн визитов",
        "studied": (
            "Программы контроля антимикробной терапии (antimicrobial stewardship): обучение, локальные рекомендации, системы поддержки "
            "решений, аудит с обратной связью, проверка назначений фармацевтом, мультидисциплинарные команды — "
            "в сравнении с обычной практикой или периодом до внедрения. Исходы: объём и обоснованность "
            "назначений антибиотиков, а также клинические, микробиологические и экономические исходы."
        ),
        "result": [
            "В 11 из 12 завершённых исследований назначений стало меньше или они стали обоснованнее. "
            "Эффекты неоднородны; общей метрики и объединённой оценки нет.",
            "Клинические исходы в целом не изменились; микробиологических и экономических данных мало.",
            "В одном исследовании на фоне снижения использования антибиотиков отмечен рост инфекций кровотока.",
        ],
        "trust": (
            "Оценка по полному тексту. Ни одно включённое исследование не было завершённым РКИ; большинство — "
            "«до-после» или квазиэкспериментальные, поэтому речь идёт об ассоциации, а не о доказанном "
            "причинном эффекте. Исходы несопоставимы для объединения, риск систематических ошибок описан "
            "ограниченно, а в статье есть внутреннее противоречие (12 или 13 исследований). Счёт «11 из 12» "
            "без общей меры эффекта может создавать завышенное впечатление."
        ),
        "meaning": (
            "Есть сигнал в пользу комплексных мер (обучение, рекомендации, поддержка решений, аудит с обратной "
            "связью) в неотложной помощи, но размер эффекта неизвестен, а данные только частично детские. "
            "«Меньше антибиотиков» — не самоцель: важны обоснованность назначений и безопасность пациентов. "
            "Может служить ориентиром при обсуждении локальных мер, но не доказательством их эффективности."
        ),
        "ru_practice": (
            "Проблема напрямую актуальна, но штат, правила назначения и организация неотложной помощи в РФ "
            "отличаются от описанных в исследованиях. Перед переносом — сверить с действующими клиническими "
            "рекомендациями и локальными протоколами."
        ),
    },
}


class PresentationError(RuntimeError):
    """Нельзя собрать пользовательский дайджест без редакционного профиля."""


# ---------------------------------------------------------------------------
# Модель выпуска
# ---------------------------------------------------------------------------

@dataclass
class Card:
    pmid: str
    title_ru: str
    original_title: str
    source_line: str
    design_ru: str
    population_ru: str
    studied: str
    result: list[str]
    trust_label: str
    trust: str
    meaning: str
    ru_practice: str
    status: str
    links: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Issue:
    generated_at: dt.datetime
    sections: dict[str, list]  # section key -> cards (main) или простые элементы

    @property
    def cards(self) -> list[Card]:
        return self.sections.get("main", [])


def _get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
MONTHS_SHORT = {"Jan": "янв.", "Feb": "февр.", "Mar": "март", "Apr": "апр.", "May": "май", "Jun": "июнь",
                "Jul": "июль", "Aug": "авг.", "Sep": "сент.", "Oct": "окт.", "Nov": "нояб.", "Dec": "дек."}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def ru_date(value: dt.datetime | dt.date) -> str:
    return f"{value.day} {MONTHS_GEN[value.month - 1]} {value.year}, {WEEKDAYS[value.weekday()]}"


def _publication_date(raw: str) -> str:
    match = re.match(r"^(\d{4})\s*([A-Za-z]{3})?", raw or "")
    if not match:
        return ""
    year, month = match.groups()
    return f"{MONTHS_SHORT.get(month, '')} {year}".strip() if month else year


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _is_web_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def links_for(row) -> list[tuple[str, str]]:
    """Publisher URL — только сохранённый в БД; PubMed и DOI — детерминированные."""
    links = []
    source_url = _get(row, "source_url", "")
    if _is_web_url(source_url):
        links.append(("Оригинальная публикация", source_url))
    pmid = str(_get(row, "pmid", "")).strip()
    if pmid.isdigit():
        links.append(("PubMed", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"))
    doi = str(_get(row, "doi", "")).strip()
    if doi.startswith("10."):
        links.append(("DOI", "https://doi.org/" + quote(doi, safe="/()._-;:")))
    return links


def build_card(row) -> Card:
    pmid = str(_get(row, "pmid", ""))
    profile = PRESENTATION_PROFILES.get(pmid)
    if profile is None:
        raise PresentationError(f"Нет русского presentation-профиля для PMID {pmid}; письмо не собрано.")
    version = _get(row, "appraisal_version")
    if version and version != profile["appraisal_version"]:
        raise PresentationError(
            f"Профиль PMID {pmid} написан для appraisal {profile['appraisal_version']}, "
            f"а в БД {version}; обновите профиль перед выпуском."
        )
    journal = _get(row, "journal", "")
    pub = _publication_date(_get(row, "published_date", ""))
    source_line = " · ".join(x for x in (journal, pub) if x)
    reliability = _get(row, "reliability", "")
    return Card(
        pmid=pmid,
        title_ru=profile["title_ru"],
        original_title=_get(row, "title", "").strip(),
        source_line=source_line,
        design_ru=profile["design_ru"],
        population_ru=profile["population_ru"],
        studied=profile["studied"],
        result=list(profile["result"]),
        trust_label=RELIABILITY_LABELS.get(reliability, "Оценка надёжности не указана"),
        trust=profile["trust"],
        meaning=profile["meaning"],
        ru_practice=profile["ru_practice"],
        status=status_for(row, profile),
        links=links_for(row),
    )


@dataclass
class GuidelineItem:
    title: str
    summary: str
    practical_meaning: str
    status: str
    update_label: str
    edition: str
    source_name: str
    updated_at: str
    url: str | None


@dataclass
class EventItem:
    title: str
    description: str
    status: str
    kind: str
    format_label: str
    when: str
    novosibirsk_when: str | None
    place: str | None
    organizer: str
    cost: str
    cme: str
    registration_url: str | None
    official_url: str | None


@dataclass
class MinuteItem:
    emoji: str
    text: str
    url: str | None


NOT_SPECIFIED = "не указано"
UPDATE_LABELS = {"new_edition": "Действующая редакция", "substantial_update": "Существенное обновление"}
EVENT_FORMATS = {"offline": "Очно", "hybrid": "Гибрид: очно и онлайн", "online": "Онлайн"}


def _ru_day(d: dt.date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def _date_range(a: dt.date, b: dt.date) -> str:
    if a == b:
        return _ru_day(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {MONTHS_GEN[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day} {MONTHS_GEN[a.month - 1]} – {b.day} {MONTHS_GEN[b.month - 1]} {a.year}"
    return f"{_ru_day(a)} – {_ru_day(b)}"


def _time_range(start: dt.datetime, end: dt.datetime | None) -> str:
    if end is None:
        return f"{_ru_day(start.date())}, {start:%H:%M}"
    if end.date() == start.date():
        return f"{_ru_day(start.date())}, {start:%H:%M}–{end:%H:%M}"
    return f"{_ru_day(start.date())}, {start:%H:%M} – {_ru_day(end.date())}, {end:%H:%M}"


def event_when(starts_at: str, ends_at: str | None, timezone_label: str, with_novosibirsk: bool) -> tuple[str, str | None]:
    """Дата для врача по времени организатора и (для онлайн/гибрида) по Новосибирску.

    Смещение в starts_at — источник истины для пересчёта; поле timezone
    выводится как подпись, которую указал редактор.
    """
    start = context.parse_when(starts_at)
    end = context.parse_when(ends_at) if ends_at else None
    if not isinstance(start, dt.datetime):
        return _date_range(start, end or start), None
    local = f"{_time_range(start, end)} ({timezone_label})"
    if not with_novosibirsk:
        return local, None
    nsk_start = start.astimezone(context.NOVOSIBIRSK)
    nsk_end = end.astimezone(context.NOVOSIBIRSK) if end else None
    return local, _time_range(nsk_start, nsk_end)


def build_guideline(row) -> GuidelineItem:
    updated = _get(row, "published_or_updated_at", "")
    try:
        updated_ru = _ru_day(dt.date.fromisoformat(updated))
    except ValueError:
        updated_ru = ""
    url = _get(row, "official_url")
    return GuidelineItem(
        title=_get(row, "title", ""),
        summary=_get(row, "summary", ""),
        practical_meaning=_get(row, "practical_meaning", ""),
        status=_get(row, "status") if _get(row, "status") in STATUSES else "watch",
        update_label=UPDATE_LABELS.get(_get(row, "update_kind", "new_edition"), "Обновление"),
        edition=_get(row, "edition_or_version", ""),
        source_name=_get(row, "source_name", ""),
        updated_at=updated_ru,
        url=url if _is_web_url(url) else None,
    )


def build_event(row) -> EventItem:
    kind = _get(row, "event_kind", "offline")
    when, nsk = event_when(_get(row, "starts_at"), _get(row, "ends_at"), _get(row, "timezone", ""),
                           with_novosibirsk=kind in ("online", "hybrid"))
    place = ", ".join(x for x in (_get(row, "city"), _get(row, "venue")) if x) or None
    reg, official = _get(row, "registration_url"), _get(row, "official_url")
    return EventItem(
        title=_get(row, "title", ""),
        description=_get(row, "description", ""),
        status=_get(row, "status") if _get(row, "status") in STATUSES else "watch",
        kind=kind,
        format_label=EVENT_FORMATS.get(kind, kind),
        when=when,
        novosibirsk_when=nsk,
        place=place if kind != "online" else None,
        organizer=_get(row, "organizer", ""),
        # NULL в БД = «не указано / не подтверждено»; ничего не домысливаем.
        cost=_get(row, "cost") or NOT_SPECIFIED,
        cme=_get(row, "cme_credits") or NOT_SPECIFIED,
        registration_url=reg if _is_web_url(reg) else None,
        official_url=official if _is_web_url(official) else None,
    )


def build_one_minute(sections: dict[str, list], limit: int = 5) -> list[MinuteItem]:
    """«Одна минута» — только пересказ заголовков уже вошедших в выпуск пунктов.

    Новых фактов здесь нет: текст берётся из заголовков карточек, КР и
    мероприятий; ссылка — первая из тех, что уже есть в пункте.
    """
    pool: list[tuple[str, MinuteItem]] = []
    # Везде эмодзи статуса (как в карточках), тип пункта — словом в начале.
    for c in sections.get("main", []):
        # PubMed — детерминированная ссылка, поэтому для короткого тезиса она надёжнее издательской.
        links = dict(c.links)
        url = links.get("PubMed") or (c.links[0][1] if c.links else None)
        pool.append((c.status, MinuteItem(STATUSES[c.status]["emoji"], c.title_ru, url)))
    for g in sections.get("ru_guidelines", []):
        text = f"КР, {g.update_label.lower()}: {g.title} ({g.edition})"
        pool.append((g.status, MinuteItem(STATUSES[g.status]["emoji"], text, g.url)))
    short = {"offline": "Очно", "hybrid": "Гибрид", "online": "Онлайн"}
    for key in ("events_offline", "events_online"):
        for e in sections.get(key, []):
            date = f"{e.novosibirsk_when} по Новосибирску" if e.novosibirsk_when else e.when
            text = f"{short.get(e.kind, e.format_label)}: {e.title} — {date}"
            pool.append((e.status, MinuteItem(STATUSES[e.status]["emoji"], text, e.registration_url or e.official_url)))
    pool.sort(key=lambda p: STATUSES[p[0]]["rank"])  # стабильно: порядок разделов внутри статуса
    return [item for _, item in pool[:limit]]


def build_issue(rows, generated_at: dt.datetime | None = None, context_data: dict | None = None) -> Issue:
    """Собирает выпуск.

    context_data — результат context.load_for_digest: уже отобранные КР и
    мероприятия. Отбор (что новое, что уже показывали) делает context.py;
    здесь только оформление.
    """
    cards = sorted((build_card(r) for r in rows), key=lambda c: STATUSES[c.status]["rank"])
    sections: dict[str, list] = {"main": cards}
    context_data = context_data or {}
    guidelines = [build_guideline(r) for r in context_data.get("guidelines", [])]
    events = [build_event(r) for r in context_data.get("events", [])]
    sections["ru_guidelines"] = sorted(guidelines, key=lambda g: STATUSES[g.status]["rank"])
    sections["events_offline"] = [e for e in events if e.kind in ("offline", "hybrid")]
    sections["events_online"] = [e for e in events if e.kind == "online"]
    sections["one_minute"] = build_one_minute(sections)
    return Issue(generated_at=generated_at or dt.datetime.now().astimezone(), sections=sections)


def _visible_sections(issue: Issue):
    for key, title in SECTIONS:
        items = issue.sections.get(key) or []
        if key == "main" or items:
            yield key, title, items


def subject(issue: Issue) -> str:
    n = len(issue.cards)
    date = issue.generated_at.strftime("%d.%m.%Y")
    if not n:
        return f"Педиатрический дайджест — {date}"
    return f"Педиатрический дайджест — {date}: {n} {_plural(n, 'работа', 'работы', 'работ')}"


def _lead(issue: Issue) -> str:
    n = len(issue.cards)
    if not n:
        lead = "Сегодня приоритетных публикаций нет."
    else:
        lead = (f"{n} {_plural(n, 'приоритетная работа', 'приоритетные работы', 'приоритетных работ')} "
                "за последние дни. Каждая карточка — пересказ уже проведённой оценки, без усиления выводов авторов.")
    extra = []
    g = len(issue.sections.get("ru_guidelines", []))
    e = len(issue.sections.get("events_offline", [])) + len(issue.sections.get("events_online", []))
    if g:
        extra.append(f"{g} {_plural(g, 'обновление', 'обновления', 'обновлений')} КР")
    if e:
        extra.append(f"{e} {_plural(e, 'мероприятие', 'мероприятия', 'мероприятий')}")
    if extra:
        lead += " Также в выпуске: " + " и ".join(extra) + "."
    return lead


FOOTER = ("Дайджест — обзор публикаций, а не клиническая рекомендация. Решения о диагностике и лечении "
          "принимаются по действующим клиническим рекомендациям Минздрава РФ и клинической ситуации.")
EVENTS_FOOTER = " Даты, стоимость и НМО мероприятий уточняйте на официальной странице организатора."


def footer(issue: Issue) -> str:
    has_events = issue.sections.get("events_offline") or issue.sections.get("events_online")
    return FOOTER + (EVENTS_FOOTER if has_events else "")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _md_escape(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", text)


def render_markdown(issue: Issue) -> str:
    out = [f"# 🩺 Педиатрический дайджест", "", f"*{ru_date(issue.generated_at)}*", "", _lead(issue), ""]
    for key, title, items in _visible_sections(issue):
        out += [f"## {title}", ""]
        if key == "main":
            if not items:
                out += ["Сегодня приоритетных публикаций нет.", ""]
            for i, c in enumerate(items, 1):
                s = STATUSES[c.status]
                out += [f"### {i}. {_md_escape(c.title_ru)}", "",
                        f"{s['emoji']} **{s['label']}** · {_md_escape(c.design_ru)}", "",
                        f"*{_md_escape(c.population_ru)}*", "",
                        f"**Что изучали.** {_md_escape(c.studied)}", "",
                        "**Результат.**", ""]
                out += [f"- {_md_escape(x)}" for x in c.result]
                out += ["", f"**Насколько можно доверять.** *{c.trust_label}.* {_md_escape(c.trust)}", "",
                        f"**Что это значит врачу.** {_md_escape(c.meaning)}", "",
                        f"**Применимость в РФ.** {_md_escape(c.ru_practice)}", ""]
                if c.links:
                    out += ["🔗 " + " · ".join(f"[{label}](<{url}>)" for label, url in c.links), ""]
                meta = " · ".join(x for x in (c.source_line, f"ориг. название: {c.original_title}") if x)
                out += [f"<sub>{_md_escape(meta)}</sub>", "", "---", ""]
        else:
            out += _md_section(key, items)
    out += [f"*{footer(issue)}*", ""]
    return "\n".join(out)


# --- Markdown: КР, мероприятия, «одна минута» ---------------------------------

def _md_link(label: str, url: str | None) -> str:
    return f"[{_md_escape(label)}](<{url}>)" if url else NOT_SPECIFIED


def _md_section(key: str, items) -> list[str]:
    out: list[str] = []
    if key == "ru_guidelines":
        for g in items:
            s = STATUSES[g.status]
            meta = " · ".join(x for x in (g.update_label, f"редакция: {g.edition}", g.source_name,
                                          g.updated_at and f"от {g.updated_at}") if x)
            out += [f"### {_md_escape(g.title)}", "", f"{s['emoji']} **{s['label']}** · {_md_escape(meta)}", "",
                    f"**Что изменилось.** {_md_escape(g.summary)}", "",
                    f"**Что это значит врачу.** {_md_escape(g.practical_meaning)}", ""]
            if g.url:
                out += [f"🔗 {_md_link('Официальный текст', g.url)}", ""]
            out += ["---", ""]
    elif key in ("events_offline", "events_online"):
        for e in items:
            s = STATUSES[e.status]
            out += [f"### {_md_escape(e.title)}", "", f"{s['emoji']} **{s['label']}** · {e.format_label}", "",
                    f"**Что это.** {_md_escape(e.description)}", "",
                    f"- **Дата:** {_md_escape(e.when)}"]
            if e.novosibirsk_when:
                out.append(f"- **По Новосибирску:** {_md_escape(e.novosibirsk_when)}")
            if e.place:
                out.append(f"- **Где:** {_md_escape(e.place)}")
            out += [f"- **Формат:** {e.format_label}",
                    f"- **Организатор:** {_md_escape(e.organizer)}",
                    f"- **Стоимость:** {_md_escape(e.cost)}",
                    f"- **НМО/ЗЕТ:** {_md_escape(e.cme)}",
                    f"- **Регистрация:** {_md_link('Регистрация', e.registration_url)}",
                    f"- **Источник:** {_md_link('Официальная страница', e.official_url)}", "", "---", ""]
    elif key == "one_minute":
        for m in items:
            text = _md_escape(m.text)
            out.append(f"- {m.emoji} " + (f"[{text}](<{m.url}>)" if m.url else text))
        out.append("")
    return out


# ---------------------------------------------------------------------------
# HTML (email-совместимый: таблицы, inline-стили, без JavaScript)
# ---------------------------------------------------------------------------

E = html.escape
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif"


def _html_link_button(label: str, url: str) -> str:
    return (f'<a href="{E(url, quote=True)}" target="_blank" rel="noopener" '
            f'style="display:inline-block;margin:0 6px 6px 0;padding:7px 12px;border:1px solid #1565c0;'
            f'border-radius:6px;color:#1565c0;text-decoration:none;font-size:14px;">{E(label)}</a>')


def _html_field(label: str, body_html: str) -> str:
    return (f'<p style="margin:14px 0 4px;font-size:13px;font-weight:bold;color:#37474f;'
            f'text-transform:uppercase;letter-spacing:.3px;">{E(label)}</p>'
            f'<div style="margin:0;font-size:15px;line-height:1.5;color:#212121;">{body_html}</div>')


def _html_card(i: int, c: Card) -> str:
    s = STATUSES[c.status]
    result = "".join(f'<li style="margin:0 0 6px;">{E(x)}</li>' for x in c.result)
    links = "".join(_html_link_button(label, url) for label, url in c.links)
    meta = " · ".join(E(x) for x in (c.source_line,) if x)
    orig = f'<br>Оригинальное название: <i>{E(c.original_title)}</i>' if c.original_title else ""
    return f"""
<table role="presentation" class="card" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 20px;border:1px solid #e0e0e0;border-left:5px solid {s['color']};border-radius:8px;background:#ffffff;">
<tr><td class="card-pad" style="padding:18px 20px;font-family:{FONT};">
  <span style="display:inline-block;padding:3px 10px;border-radius:12px;background:{s['bg']};color:{s['color']};font-size:13px;font-weight:bold;">{s['emoji']} {E(s['label'])}</span>
  <h3 class="card-title" style="margin:10px 0 6px;font-size:19px;line-height:1.3;color:#102a43;">{i}. {E(c.title_ru)}</h3>
  <p style="margin:0 0 4px;font-size:14px;color:#455a64;"><b>{E(c.design_ru)}</b></p>
  <p style="margin:0;font-size:14px;line-height:1.45;color:#455a64;">{E(c.population_ru)}</p>
  {_html_field("Что изучали", E(c.studied))}
  {_html_field("Результат", f'<ul style="margin:0;padding-left:20px;">{result}</ul>')}
  {_html_field("Насколько можно доверять", f'<b>{E(c.trust_label)}.</b> {E(c.trust)}')}
  <div style="margin:16px 0 0;padding:12px 14px;background:#e8f1fb;border-radius:6px;">
    <p style="margin:0 0 4px;font-size:13px;font-weight:bold;color:#0d47a1;text-transform:uppercase;letter-spacing:.3px;">Что это значит врачу</p>
    <p style="margin:0;font-size:15px;line-height:1.5;color:#102a43;">{E(c.meaning)}</p>
    <p style="margin:10px 0 0;font-size:14px;line-height:1.45;color:#37474f;"><b>Применимость в РФ.</b> {E(c.ru_practice)}</p>
  </div>
  <div style="margin:16px 0 0;">{links}</div>
  <p style="margin:8px 0 0;font-size:12px;line-height:1.4;color:#78909c;">{meta}{orig}</p>
</td></tr>
</table>"""


# --- HTML: КР, мероприятия, «одна минута» -------------------------------------

def _html_badge(status: str) -> str:
    s = STATUSES[status]
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;background:{s["bg"]};'
            f'color:{s["color"]};font-size:13px;font-weight:bold;">{s["emoji"]} {E(s["label"])}</span>')


def _html_box(status: str, css_class: str, inner: str) -> str:
    color = STATUSES[status]["color"]
    return f"""
<table role="presentation" class="{css_class}" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="margin:0 0 16px;border:1px solid #e0e0e0;border-left:5px solid {color};border-radius:8px;background:#ffffff;">
<tr><td class="card-pad" style="padding:16px 20px;font-family:{FONT};">{inner}</td></tr>
</table>"""


def _html_link(label: str, url: str | None) -> str:
    if not url:
        return E(NOT_SPECIFIED)
    return f'<a href="{E(url, quote=True)}" target="_blank" rel="noopener" style="color:#1565c0;">{E(label)}</a>'


def _html_facts(rows: list[tuple[str, str]]) -> str:
    """Таблица «поле — значение»; значения передаются уже экранированными."""
    body = "".join(
        f'<tr><td style="padding:3px 12px 3px 0;vertical-align:top;color:#607d8b;white-space:nowrap;">{E(k)}</td>'
        f'<td style="padding:3px 0;vertical-align:top;color:#212121;">{v}</td></tr>' for k, v in rows)
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:10px 0 0;font-size:14px;line-height:1.45;">{body}</table>'


def _html_section(key: str, items) -> str:
    if key == "ru_guidelines":
        parts = []
        for g in items:
            meta = " · ".join(E(x) for x in (g.update_label, f"редакция: {g.edition}", g.source_name,
                                              g.updated_at and f"от {g.updated_at}") if x)
            link = f'<div style="margin:14px 0 0;">{_html_link_button("Официальный текст", g.url)}</div>' if g.url else ""
            parts.append(_html_box(g.status, "guideline", f"""
  {_html_badge(g.status)}
  <h3 class="item-title" style="margin:10px 0 6px;font-size:18px;line-height:1.3;color:#102a43;">{E(g.title)}</h3>
  <p style="margin:0;font-size:13px;color:#607d8b;">{meta}</p>
  {_html_field("Что изменилось", E(g.summary))}
  {_html_field("Что это значит врачу", E(g.practical_meaning))}
  {link}"""))
        return "".join(parts)
    if key in ("events_offline", "events_online"):
        parts = []
        for e in items:
            facts = [("Дата", E(e.when))]
            if e.novosibirsk_when:
                facts.append(("По Новосибирску", E(e.novosibirsk_when)))
            if e.place:
                facts.append(("Где", E(e.place)))
            facts += [("Формат", E(e.format_label)), ("Организатор", E(e.organizer)),
                      ("Стоимость", E(e.cost)), ("НМО/ЗЕТ", E(e.cme)),
                      ("Регистрация", _html_link("Регистрация", e.registration_url)),
                      ("Источник", _html_link("Официальная страница", e.official_url))]
            parts.append(_html_box(e.status, "event", f"""
  {_html_badge(e.status)}
  <h3 class="item-title" style="margin:10px 0 6px;font-size:18px;line-height:1.3;color:#102a43;">{E(e.title)}</h3>
  <p style="margin:0;font-size:15px;line-height:1.5;color:#212121;">{E(e.description)}</p>
  {_html_facts(facts)}"""))
        return "".join(parts)
    if key == "one_minute":
        rows = "".join(
            f'<li style="margin:0 0 8px;">{m.emoji} '
            + (f'<a href="{E(m.url, quote=True)}" target="_blank" rel="noopener" style="color:#1565c0;">{E(m.text)}</a>' if m.url else E(m.text))
            + "</li>" for m in items)
        return (f'<ul class="one-minute" style="margin:0 0 20px;padding-left:20px;font-family:{FONT};'
                f'font-size:15px;line-height:1.5;list-style:none;">{rows}</ul>')
    return ""


def render_html(issue: Issue) -> str:
    body = []
    for key, title, items in _visible_sections(issue):
        body.append(f'<h2 style="margin:24px 0 12px;font-size:21px;color:#102a43;font-family:{FONT};">{E(title)}</h2>')
        if key == "main":
            if not items:
                body.append(f'<p style="font-family:{FONT};font-size:15px;">Сегодня приоритетных публикаций нет.</p>')
            body.extend(_html_card(i, c) for i, c in enumerate(items, 1))
        else:
            body.append(_html_section(key, items))
    preheader = "; ".join(c.title_ru for c in issue.cards) or _lead(issue)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{E(subject(issue))}</title>
<style>
  body {{ margin:0; padding:0; background:#f2f4f7; }}
  a {{ color:#1565c0; }}
  @media only screen and (max-width: 620px) {{
    .wrap {{ width:100% !important; }}
    .outer-pad {{ padding:12px 8px !important; }}
    .card-pad {{ padding:14px 14px !important; }}
    h1 {{ font-size:22px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#f2f4f7;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{E(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f2f4f7;">
<tr><td align="center" class="outer-pad" style="padding:24px 12px;">
<table role="presentation" class="wrap" width="700" cellpadding="0" cellspacing="0" border="0" style="width:700px;max-width:700px;">
<tr><td style="padding:0 4px;font-family:{FONT};color:#212121;">
  <h1 style="margin:0 0 4px;font-size:26px;color:#102a43;">🩺 Педиатрический дайджест</h1>
  <p style="margin:0 0 12px;font-size:14px;color:#607d8b;">{E(ru_date(issue.generated_at))}</p>
  <p style="margin:0 0 8px;font-size:15px;line-height:1.5;color:#37474f;">{E(_lead(issue))}</p>
  {''.join(body)}
  <p style="margin:24px 0 0;padding-top:12px;border-top:1px solid #d0d7de;font-size:12px;line-height:1.5;color:#78909c;">{E(footer(issue))}</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def _wrap(text: str, indent: str = "", first: str | None = None) -> list[str]:
    return textwrap.wrap(text, width=76, initial_indent=first if first is not None else indent,
                         subsequent_indent=indent, break_long_words=False, break_on_hyphens=False) or [""]


# --- Plain text: КР, мероприятия, «одна минута» -------------------------------

def _text_section(key: str, items) -> list[str]:
    out: list[str] = []
    if key == "ru_guidelines":
        for g in items:
            s = STATUSES[g.status]
            out += _wrap(g.title, indent="   ", first="• ")
            out += [f"   {s['emoji']} {s['label']}"]
            meta = " · ".join(x for x in (g.update_label, f"редакция: {g.edition}", g.source_name,
                                          g.updated_at and f"от {g.updated_at}") if x)
            out += _wrap(meta, indent="   ") + [""]
            out += ["   ЧТО ИЗМЕНИЛОСЬ"] + _wrap(g.summary, indent="   ") + [""]
            out += ["   ЧТО ЭТО ЗНАЧИТ ВРАЧУ"] + _wrap(g.practical_meaning, indent="   ") + [""]
            if g.url:
                out += ["   Официальный текст:", f"   {g.url}"]
            out += ["", "-" * 60, ""]
    elif key in ("events_offline", "events_online"):
        for e in items:
            s = STATUSES[e.status]
            out += _wrap(e.title, indent="   ", first="• ")
            out += [f"   {s['emoji']} {s['label']}", ""]
            out += _wrap(e.description, indent="   ") + [""]
            out += _wrap(f"Дата: {e.when}", indent="     ", first="   ")
            if e.novosibirsk_when:
                out += _wrap(f"По Новосибирску: {e.novosibirsk_when}", indent="     ", first="   ")
            if e.place:
                out += _wrap(f"Где: {e.place}", indent="     ", first="   ")
            out += [f"   Формат: {e.format_label}"]
            out += _wrap(f"Организатор: {e.organizer}", indent="     ", first="   ")
            out += [f"   Стоимость: {e.cost}", f"   НМО/ЗЕТ: {e.cme}"]
            out += [f"   Регистрация: {e.registration_url or NOT_SPECIFIED}",
                    f"   Источник: {e.official_url or NOT_SPECIFIED}", "", "-" * 60, ""]
    elif key == "one_minute":
        for m in items:
            out += _wrap(f"{m.emoji} {m.text}", indent="   ", first="• ")
            if m.url:
                out += [f"   {m.url}"]
        out.append("")
    return out


def render_text(issue: Issue) -> str:
    out = ["ПЕДИАТРИЧЕСКИЙ ДАЙДЖЕСТ", ru_date(issue.generated_at), ""]
    out += _wrap(_lead(issue)) + [""]
    for key, title, items in _visible_sections(issue):
        out += ["=" * 60, title, "=" * 60, ""]
        if key == "main":
            if not items:
                out += ["Сегодня приоритетных публикаций нет.", ""]
            for i, c in enumerate(items, 1):
                s = STATUSES[c.status]
                out += _wrap(f"{i}. {c.title_ru}", indent="   ", first="")
                out += [f"   {s['emoji']} {s['label']}", ""]
                out += _wrap(f"{c.design_ru}. {c.population_ru}.", indent="   ") + [""]
                out += ["   ЧТО ИЗУЧАЛИ"] + _wrap(c.studied, indent="   ") + [""]
                out += ["   РЕЗУЛЬТАТ"]
                for x in c.result:
                    out += _wrap(x, indent="     ", first="   • ")
                out += ["", "   НАСКОЛЬКО МОЖНО ДОВЕРЯТЬ"] + _wrap(f"{c.trust_label}. {c.trust}", indent="   ") + [""]
                out += ["   ЧТО ЭТО ЗНАЧИТ ВРАЧУ"] + _wrap(c.meaning, indent="   ") + [""]
                out += _wrap(f"Применимость в РФ: {c.ru_practice}", indent="   ") + [""]
                for label, url in c.links:
                    out += [f"   {label}:", f"   {url}"]
                if c.source_line:
                    out += ["", f"   {c.source_line}"]
                out += ["", "-" * 60, ""]
        else:
            out += _text_section(key, items)
    out += _wrap(footer(issue)) + [""]
    return "\n".join(out)


class _TextExtractor(HTMLParser):
    """Запасной вариант plain-text для email-draft из произвольного HTML."""

    BLOCK = {"p", "div", "h1", "h2", "h3", "li", "tr", "br", "ul", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "title"):
            self.skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")
        if tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "title"):
            self.skip -= 1
        if tag == "a" and self.href:
            self.parts.append(f": {self.href}")
            self.href = None
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(source: str) -> str:
    parser = _TextExtractor()
    parser.feed(source)
    text = "".join(parser.parts)
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


# ---------------------------------------------------------------------------
# Email и запись файлов
# ---------------------------------------------------------------------------

PLACEHOLDER_RECIPIENT = "review@example.com"
SENDER = "pediatric-surveillance@localhost"


def build_email(subject_line: str, text_body: str, html_body: str, recipient: str = "") -> EmailMessage:
    """multipart/alternative: text/plain + text/html. Письмо не отправляется."""
    message = EmailMessage()
    message["Subject"] = subject_line
    message["From"] = SENDER
    message["To"] = recipient or PLACEHOLDER_RECIPIENT
    message.set_content(text_body, subtype="plain", charset="utf-8")
    message.add_alternative(html_body, subtype="html", charset="utf-8")
    return message


def write_digest(rows, output_dir: str, generated_at: dt.datetime | None = None,
                 recipient: str = "", context_data: dict | None = None) -> dict:
    """Собирает выпуск из готовых строк и пишет .md, .html, .txt и .eml."""
    issue = build_issue(rows, generated_at, context_data)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = issue.generated_at.strftime("%Y%m%d-%H%M%S")
    paths = {kind: out / f"digest-{stamp}.{kind}" for kind in ("md", "html", "txt", "eml")}
    md, page, text = render_markdown(issue), render_html(issue), render_text(issue)
    paths["md"].write_text(md, encoding="utf-8")
    paths["html"].write_text(page, encoding="utf-8")
    paths["txt"].write_text(text, encoding="utf-8")
    paths["eml"].write_bytes(build_email(subject(issue), text, page, recipient).as_bytes())
    return {
        "count": len(issue.cards),
        "statuses": {c.pmid: c.status for c in issue.cards},
        "guidelines": len(issue.sections.get("ru_guidelines", [])),
        "events_offline": len(issue.sections.get("events_offline", [])),
        "events_online": len(issue.sections.get("events_online", [])),
        "one_minute": len(issue.sections.get("one_minute", [])),
        "markdown": str(paths["md"]),
        "html": str(paths["html"]),
        "text": str(paths["txt"]),
        "eml": str(paths["eml"]),
        "sent": False,
    }
