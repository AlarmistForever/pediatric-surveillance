from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    window_start TEXT,
    window_end TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    branch TEXT NOT NULL,
    query_string TEXT NOT NULL,
    query_version TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT
    ,count INTEGER NOT NULL DEFAULT 0
    ,retrieved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pmid TEXT,
    doi TEXT,
    title TEXT NOT NULL,
    abstract TEXT,
    journal TEXT,
    published_date TEXT,
    entry_date TEXT,
    authors TEXT,
    source_branch TEXT,
    first_seen_run_id INTEGER REFERENCES runs(id),
    last_seen_run_id INTEGER REFERENCES runs(id),
    screening TEXT NOT NULL DEFAULT 'maybe',
    screening_reason TEXT,
    publication_types TEXT,
    UNIQUE(pmid), UNIQUE(doi)
);
CREATE TABLE IF NOT EXISTS work_ids (
    work_id INTEGER NOT NULL REFERENCES works(id),
    id_type TEXT NOT NULL,
    id_value TEXT NOT NULL,
    PRIMARY KEY(id_type, id_value)
);
CREATE TABLE IF NOT EXISTS appraisals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES works(id),
    appraisal_version TEXT NOT NULL,
    based_on TEXT NOT NULL,
    design TEXT,
    population TEXT,
    sample_size TEXT,
    intervention TEXT,
    comparator TEXT,
    primary_outcome TEXT,
    main_results TEXT,
    reliability TEXT NOT NULL,
    reliability_reason TEXT,
    spin_flags TEXT NOT NULL,
    novelty TEXT,
    clinical_relevance TEXT,
    clinical_relevance_reason TEXT,
    ru_applicability TEXT,
    ru_reason TEXT,
    requires_ru_guideline_check INTEGER NOT NULL DEFAULT 0,
    actionability TEXT NOT NULL,
    rationale TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(work_id, appraisal_version)
);
CREATE TABLE IF NOT EXISTS full_text_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES works(id),
    pmid TEXT NOT NULL,
    doi TEXT,
    source_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    access_status TEXT NOT NULL,
    retrieval_status TEXT NOT NULL,
    license TEXT,
    checked_at TEXT NOT NULL,
    notes TEXT,
    UNIQUE(work_id, source_url)
);
-- Редакционный контекст (вручную проверенные КР и мероприятия).
-- Таблицы новые, поэтому CREATE TABLE IF NOT EXISTS безопасен для уже
-- существующих баз: старые таблицы и данные не затрагиваются.
-- first_included_at / last_included_at — дата выпуска (YYYY-MM-DD), в который
-- запись попала впервые / последний раз; NULL = ещё не показывалась.
CREATE TABLE IF NOT EXISTS guideline_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    practical_meaning TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('high', 'important', 'watch')),
    -- new_edition / substantial_update попадают в дайджест, minor_update — нет.
    update_kind TEXT NOT NULL DEFAULT 'new_edition'
        CHECK (update_kind IN ('new_edition', 'substantial_update', 'minor_update')),
    official_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    edition_or_version TEXT NOT NULL,
    published_or_updated_at TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    first_included_at TEXT,
    last_included_at TEXT,
    UNIQUE(official_url, edition_or_version)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('offline', 'hybrid', 'online')),
    starts_at TEXT NOT NULL,          -- ISO 8601; время — со смещением (+03:00)
    ends_at TEXT,
    timezone TEXT NOT NULL,
    city TEXT,
    venue TEXT,
    organizer TEXT NOT NULL,
    cost TEXT,                        -- NULL = не указано / не подтверждено
    cme_credits TEXT,                 -- НМО/ЗЕТ; NULL = не указано / не подтверждено
    registration_url TEXT,
    official_url TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    first_included_at TEXT,
    last_included_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('high', 'important', 'watch')),
    UNIQUE(official_url, starts_at)
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for statement in ("ALTER TABLE queries ADD COLUMN count INTEGER NOT NULL DEFAULT 0", "ALTER TABLE queries ADD COLUMN retrieved INTEGER NOT NULL DEFAULT 0", "ALTER TABLE works ADD COLUMN publication_types TEXT"):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    return conn


def start_run(conn: sqlite3.Connection, command: str, start: str, end: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs(started_at, command, status, window_start, window_end) VALUES(datetime('now'), ?, 'running', ?, ?)",
        (command, start, end),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, errors: int = 0, notes: str = "") -> None:
    conn.execute("UPDATE runs SET finished_at=datetime('now'), status=?, error_count=?, notes=? WHERE id=?", (status, errors, notes, run_id))
    conn.commit()


def upsert_work(conn: sqlite3.Connection, work: dict, run_id: int) -> tuple[int, bool]:
    existing = None
    if work.get("pmid"):
        existing = conn.execute("SELECT id FROM works WHERE pmid=?", (work["pmid"],)).fetchone()
    if existing is None and work.get("doi"):
        existing = conn.execute("SELECT id FROM works WHERE doi=?", (work["doi"],)).fetchone()
    if existing:
        conn.execute("UPDATE works SET last_seen_run_id=?, source_branch=COALESCE(source_branch, ?) WHERE id=?", (run_id, work.get("source_branch"), existing["id"]))
        conn.commit()
        return int(existing["id"]), False
    cur = conn.execute(
        """INSERT INTO works(pmid, doi, title, abstract, journal, published_date, entry_date, authors, source_branch, first_seen_run_id, last_seen_run_id, publication_types)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (work.get("pmid"), work.get("doi"), work["title"], work.get("abstract", ""), work.get("journal", ""), work.get("published_date") or None, work.get("entry_date"), work.get("authors", ""), work.get("source_branch"), run_id, run_id, work.get("publication_types", "[]")),
    )
    work_id = int(cur.lastrowid)
    for id_type, value in (("pmid", work.get("pmid")), ("doi", work.get("doi"))):
        if value:
            conn.execute("INSERT OR IGNORE INTO work_ids(work_id,id_type,id_value) VALUES(?,?,?)", (work_id, id_type, value))
    conn.commit()
    return work_id, True
