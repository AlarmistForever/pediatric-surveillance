from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .context import ContextValidationError, import_context, load_json
from .db import connect
from .pipeline import appraise, digest, discover, email_draft, screen


def main() -> None:
    p = argparse.ArgumentParser(prog="pediatric-surveillance")
    p.add_argument("command", choices=["init-db", "discover", "screen", "appraise", "digest", "email-draft", "import-context", "run-all"])
    p.add_argument("--db", default=os.getenv("PEDIATRIC_DB", "data/surveillance.sqlite3"))
    p.add_argument("--output", default=os.getenv("PEDIATRIC_OUTPUT", "outputs"))
    p.add_argument("--file", default="", help="HTML-файл для email-draft или JSON для import-context")
    p.add_argument("--preview", action="store_true", help="digest без отметки показанных КР/мероприятий")
    p.add_argument("--recipient", default=os.getenv("DIGEST_TO", ""))
    p.add_argument("--overlap-days", type=int, default=3)
    args = p.parse_args()
    if args.command == "init-db":
        conn = connect(args.db); conn.close(); print(f"DB initialized: {args.db}"); return
    if args.command == "discover": print(discover(args.db, args.overlap_days, os.getenv("NCBI_API_KEY"))); return
    if args.command == "screen": print(screen(args.db, args.output)); return
    if args.command == "appraise": print(appraise(args.db, args.output)); return
    if args.command == "digest": print(digest(args.db, args.output, args.recipient, mark_included=not args.preview)); return
    if args.command == "import-context":
        # Только локальный JSON: никаких сетевых запросов и отправки.
        source = args.file or "data/editorial_context.json"
        try:
            # Сначала проверяем файл: при ошибке база даже не открывается
            # (connect() создал бы новые таблицы).
            load_json(source)
            conn = connect(args.db)
            try:
                print(import_context(conn, source))
            finally:
                conn.close()
        except ContextValidationError as exc:
            print(exc, file=sys.stderr); raise SystemExit(2)
        return
    if args.command == "email-draft":
        if not args.file:
            raise SystemExit("Для email-draft укажите --file путь\к\дайджесту.html")
        target = Path(args.output) / (Path(args.file).stem + ".eml")
        print(email_draft(args.file, str(target), args.recipient)); return
    discovery = discover(args.db, args.overlap_days, os.getenv("NCBI_API_KEY"))
    print(discovery)
    if discovery["status"] == "failed":
        print("Discovery failed for every branch; digest was not generated.", file=sys.stderr)
        raise SystemExit(1)
    print(screen(args.db, args.output))
    print(digest(args.db, args.output, args.recipient, mark_included=not args.preview))


if __name__ == "__main__":
    main()
