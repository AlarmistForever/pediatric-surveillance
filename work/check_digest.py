"""Проверяет, что HTML-дайджест согласован с SQLite и имеет health-блок."""

from __future__ import annotations

import argparse
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path


class DigestParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headings = 0
        self.text_parts: list[str] = []
        self.in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self.headings += 1
            self.in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.in_heading = False

    def handle_data(self, data: str) -> None:
        if self.in_heading:
            self.text_parts.append(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html_path", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/surveillance.sqlite3"))
    args = parser.parse_args()

    source = args.html_path.read_text(encoding="utf-8")
    parsed = DigestParser()
    parsed.feed(source)
    assert "<meta charset='utf-8'>" in source, "HTML не содержит UTF-8 meta charset"
    health = re.search(r"Health:</strong> run=(\d+); status=(\w+); окно=([^;]+); ошибок=(\d+)", source)
    assert health, "health-блок не найден или имеет неверный формат"
    assert health.group(2) == "ok", f"дайджест создан из запуска со статусом {health.group(2)}"
    assert int(health.group(4)) == 0, "в health-блоке есть ошибки"
    assert parsed.headings > 0, "в дайджесте нет карточек"
    assert source.count("Screening:") == parsed.headings, "у карточек не совпадает число screening-полей"

    conn = sqlite3.connect(args.db)
    run_id = int(health.group(1))
    run = conn.execute("SELECT status, error_count FROM runs WHERE id=?", (run_id,)).fetchone()
    assert run == ("ok", 0), f"health ссылается на несоответствующий run: {run}"
    db_count = conn.execute("SELECT count(*) FROM works WHERE screening='include'").fetchone()[0]
    assert parsed.headings == db_count, f"карточек в HTML={parsed.headings}, кандидатов в БД={db_count}"
    assert source.count("PMID:") == parsed.headings, "не у каждой карточки есть PMID"
    conn.close()
    print(f"OK: карточек={parsed.headings}; run={run_id}; status=ok; ошибок=0")


if __name__ == "__main__":
    main()
