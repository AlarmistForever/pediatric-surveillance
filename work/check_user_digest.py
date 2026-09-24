"""Проверка пользовательского русскоязычного дайджеста (HTML, Markdown, .eml).

Скрипт только читает файлы и открывает SQLite в режиме read-only.
Discovery, screening и appraisal не запускаются.

Пример:
    python work\\check_user_digest.py outputs\\final_digest_ru\\digest-YYYYMMDD-HHMMSS.html --db data\\clean.sqlite3
Если путь к HTML не указан, берётся самый свежий digest-*.html в --dir.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

APPRAISAL_VERSION = "2026-09-23-oa-1"
PRIORITY_PMIDS = {"42764858", "42764851"}

# Показатели, которые не должны меняться от очередного discovery/screening.
# Размер каталога и число запусков растут в каждом цикле, поэтому здесь их нет.
EXPECTED_COUNTS = {
    "appraisals": 12,
    "full_text_sources": 6,
    "screening_include": 6,
    "screening_exclude": 73,
    "oa_appraisals": 6,
    "oa_digest_priority": 2,
}

FORBIDDEN = [
    "Health", "Screening:", "Screening", "oa_confirmed", "full_text_read", "retrieval_status",
    "access_status", "abstract_fallback", "captcha_blocked", "based_on", "digest_priority",
    "worth_knowing", "some_concerns", "serious_concerns", "with_caveats", "requires_ru_guideline_check",
    "actionability", "rationale", "spin_flags", "appraisal", "run=", "status=", "окно=",
    ".sqlite3", "outputs/", "outputs\\", "data/", "data\\",
]
REQUIRED_FIELDS = ["Что изучали", "Результат", "Насколько можно доверять", "Что это значит врачу"]
STATUS_LABELS = ["🔴 высокий приоритет", "🟠 важно знать", "🟡 наблюдаем"]
LOCAL_PATH = re.compile(r"(?:[A-Za-z]:\\|file://|/home/|/Users/|/workspace/)")
CYR = re.compile(r"[А-Яа-яЁё]")


class Parsed(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards = 0
        self.links: list[tuple[str, str]] = []
        self.headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
        self.text: list[str] = []
        self.scripts = 0
        self.card_titles: list[int] = []  # индексы h3 — заголовков карточек публикаций
        self.event_attrs = 0
        self._href: str | None = None
        self._link_text: list[str] = []
        self._heading: str | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "script":
            self.scripts += 1
        if any(name.lower().startswith("on") for name, _ in attrs):
            self.event_attrs += 1
        if tag in ("style", "title", "script"):
            self._skip += 1
        if "card" in (attrs_d.get("class") or "").split():
            self.cards += 1
        if tag == "a":
            self._href, self._link_text = attrs_d.get("href"), []
        if tag in self.headings:
            self._heading = tag
            self.headings[tag].append("")
            if tag == "h3" and "card-title" in (attrs_d.get("class") or "").split():
                self.card_titles.append(len(self.headings["h3"]) - 1)

    def handle_endtag(self, tag):
        if tag in ("style", "title", "script"):
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append(("".join(self._link_text).strip(), self._href))
            self._href = None
        if tag == self._heading:
            self._heading = None

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        if self._href is not None:
            self._link_text.append(data)
        if self._heading:
            self.headings[self._heading][-1] += data


def norm(text: str) -> str:
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text)


def db_facts(db_path: Path) -> dict:
    """Read-only запросы к SQLite."""
    import sqlite3

    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        counts = {t: q(f"SELECT count(*) FROM {t}") for t in ("runs", "queries", "works", "work_ids", "appraisals", "full_text_sources")}
        for s in ("include", "maybe", "exclude"):
            counts[f"screening_{s}"] = q("SELECT count(*) FROM works WHERE screening=?", s)
        counts["oa_appraisals"] = q("SELECT count(*) FROM appraisals WHERE appraisal_version=?", APPRAISAL_VERSION)
        counts["oa_digest_priority"] = q("SELECT count(*) FROM appraisals WHERE appraisal_version=? AND actionability='digest_priority'", APPRAISAL_VERSION)
        rows = conn.execute(
            """SELECT w.pmid, w.doi, w.abstract, a.main_results, a.sample_size,
                      (SELECT source_url FROM full_text_sources s WHERE s.work_id=w.id
                       ORDER BY s.checked_at DESC, s.id DESC LIMIT 1) AS source_url
               FROM works w JOIN appraisals a ON a.work_id=w.id
               WHERE a.appraisal_version=? AND a.actionability='digest_priority'""",
            (APPRAISAL_VERSION,),
        ).fetchall()
        priority = [dict(r) for r in rows]
    finally:
        conn.close()
    return {"counts": counts, "priority": priority, "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest()}


def key_numbers(*texts: str) -> set[str]:
    """Числа из appraisal, которые обязаны дойти до врача (в русской записи)."""
    found = set()
    for text in texts:
        for m in re.finditer(r"-?\d+(?:\.\d+)?", text or ""):
            found.add(m.group(0).replace(".", ","))
    return found


def check_file_text(name: str, text: str, errors: list[str]) -> None:
    for word in FORBIDDEN:
        if word in text:
            errors.append(f"{name}: найдено техническое поле/слово {word!r}")
    if LOCAL_PATH.search(text):
        errors.append(f"{name}: найден локальный путь")
    for field in REQUIRED_FIELDS:
        if field.lower() not in text.lower():
            errors.append(f"{name}: нет поля {field!r}")
    if "🔥 Главное" not in text:
        errors.append(f"{name}: нет раздела «🔥 Главное»")


def check_no_abstract(name: str, text: str, priority: list[dict], errors: list[str]) -> None:
    flat = norm(text)
    for row in priority:
        abstract = norm(row.get("abstract") or "")
        for sentence in re.split(r"(?<=[.!?])\s+", abstract):
            if len(sentence) >= 40 and sentence in flat:
                errors.append(f"{name}: найден фрагмент английского abstract PMID {row['pmid']}: {sentence[:60]!r}…")
                break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html_path", nargs="?", type=Path)
    ap.add_argument("--dir", type=Path, default=Path("outputs/final_digest_ru"))
    ap.add_argument("--db", type=Path, default=Path("data/clean.sqlite3"))
    args = ap.parse_args()

    html_path = args.html_path or max(args.dir.glob("digest-*.html"), default=None, key=lambda p: p.stat().st_mtime)
    errors: list[str] = []
    if not html_path or not html_path.exists():
        print("FAIL: HTML-дайджест не найден"); return 1
    md_path, eml_path = html_path.with_suffix(".md"), html_path.with_suffix(".eml")
    for p in (md_path, eml_path):
        if not p.exists():
            errors.append(f"нет файла {p.name}")
    if errors:
        print("FAIL:\n- " + "\n- ".join(errors)); return 1

    facts = db_facts(args.db)
    counts, priority = facts["counts"], facts["priority"]

    # --- upstream -----------------------------------------------------------
    for key, expected in EXPECTED_COUNTS.items():
        if counts.get(key) != expected:
            errors.append(f"SQLite: {key}={counts.get(key)}, ожидалось {expected}")
    if {r["pmid"] for r in priority} != PRIORITY_PMIDS:
        errors.append(f"SQLite: digest_priority PMID = {sorted(r['pmid'] for r in priority)}")

    # --- HTML ---------------------------------------------------------------
    source = html_path.read_text(encoding="utf-8")
    page = Parsed(); page.feed(source)
    visible = "".join(page.text)
    check_file_text("HTML", visible, errors)
    for word in ("Health", "Screening:", "oa_confirmed", "full_text_read", "retrieval_status"):
        if word in source:
            errors.append(f"HTML (исходник): найдено {word!r}")
    check_no_abstract("HTML", source, priority, errors)
    if '<meta charset="utf-8">' not in source.lower():
        errors.append("HTML: нет meta charset utf-8")
    if 'name="viewport"' not in source:
        errors.append("HTML: нет meta viewport для телефона")
    if not re.search(r"max-width:\s*(6[89]\d|7[0-2]\d)px", source):
        errors.append("HTML: ширина письма не в диапазоне 680–720 px")
    if page.scripts or page.event_attrs or "javascript:" in source.lower():
        errors.append("HTML: найден JavaScript")
    if page.cards != len(PRIORITY_PMIDS):
        errors.append(f"HTML: карточек {page.cards}, ожидалось {len(PRIORITY_PMIDS)}")
    # h3 есть и у КР/мероприятий, поэтому проверяем только заголовки карточек публикаций.
    card_titles = [page.headings["h3"][i] for i in page.card_titles]
    if len(card_titles) != page.cards or not all(CYR.search(h) for h in card_titles):
        errors.append("HTML: заголовки карточек не на русском или не совпадают с числом карточек")
    if not all(CYR.search(h) for h in page.headings["h1"] + page.headings["h2"]):
        errors.append("HTML: есть не русские заголовки разделов")
    for field in REQUIRED_FIELDS:
        # «Что это значит врачу» есть и в КР, поэтому «не меньше числа карточек».
        if visible.count(field) < page.cards:
            errors.append(f"HTML: поле {field!r} встречается {visible.count(field)} раз, карточек {page.cards}")
    if sum(visible.count(s) for s in STATUS_LABELS) < page.cards:
        errors.append("HTML: не у каждой карточки есть статус 🔴/🟠/🟡")
    links = set(page.links)
    for row in priority:
        expected = [("PubMed", f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/"), ("DOI", f"https://doi.org/{row['doi']}")]
        if row.get("source_url"):
            expected.append(("Оригинальная публикация", row["source_url"]))
        for label, url in expected:
            if (label, url) not in links:
                errors.append(f"HTML: нет кликабельной ссылки {label} → {url}")
    for label, url in page.links:
        if not url.startswith(("https://", "http://")):
            errors.append(f"HTML: ссылка не http(s): {url}")

    # Числа, ДИ и I² из appraisal должны сохраниться (в русской записи).
    flat_visible = norm(visible)
    for row in priority:
        for number in key_numbers(row["main_results"], row["sample_size"]):
            if number not in flat_visible and number.lstrip("-") not in flat_visible:
                errors.append(f"HTML: PMID {row['pmid']}: число из appraisal {number} не найдено")
    for must in ("95% ДИ", "I² = 91%", "ассоциац", "эквивалентност", "РФ"):
        if must not in visible:
            errors.append(f"HTML: нет обязательной оговорки {must!r}")

    # --- Markdown -----------------------------------------------------------
    md = md_path.read_text(encoding="utf-8")
    check_file_text("Markdown", md, errors)
    check_no_abstract("Markdown", md, priority, errors)
    for row in priority:
        for url in (f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/", f"https://doi.org/{row['doi']}"):
            if f"(<{url}>)" not in md:
                errors.append(f"Markdown: нет ссылки {url}")

    # --- .eml ---------------------------------------------------------------
    msg = email.message_from_bytes(eml_path.read_bytes(), policy=email.policy.default)
    if msg.get_content_type() != "multipart/alternative":
        errors.append(f".eml: тип {msg.get_content_type()}, ожидался multipart/alternative")
    parts = {p.get_content_type(): p.get_content() for p in msg.iter_parts()}
    plain, html_part = parts.get("text/plain"), parts.get("text/html")
    if not plain:
        errors.append(".eml: нет text/plain")
    else:
        check_file_text(".eml text/plain", plain, errors)
        check_no_abstract(".eml text/plain", plain, priority, errors)
        for row in priority:
            if f"https://pubmed.ncbi.nlm.nih.gov/{row['pmid']}/" not in plain:
                errors.append(f".eml text/plain: нет URL PubMed {row['pmid']}")
    if not html_part:
        errors.append(".eml: нет text/html")
    elif html_part.strip() != source.strip():
        errors.append(".eml: text/html не совпадает с HTML-файлом")
    to = str(msg.get("To", ""))
    if to and not to.endswith(("@example.com", "@localhost")):
        errors.append(f".eml: реальный получатель {to!r}")

    if errors:
        print("FAIL:\n- " + "\n- ".join(errors))
        return 1
    print(f"OK: {html_path.name}; карточек={page.cards}; ссылок={len(page.links)}; "
          f"appraisal={APPRAISAL_VERSION}; digest_priority={counts['oa_digest_priority']}; "
          f"upstream counts без изменений; db sha256={facts['sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
