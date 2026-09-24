"""Отправляет свежий HTML-дайджест через Gmail SMTP.

Пароль читается только из переменной окружения GitHub Actions и не попадает в файл.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def main() -> None:
    html_path = Path(os.environ["DIGEST_HTML"])
    text_path = html_path.with_suffix(".txt")
    sender = os.environ["SMTP_USER"]
    password = os.environ["SMTP_APP_PASSWORD"]
    recipient = os.environ["DIGEST_TO"]
    if not html_path.is_file() or html_path.stat().st_size == 0:
        raise SystemExit(f"HTML-дайджест не найден или пуст: {html_path}")

    message = EmailMessage()
    message["Subject"] = f"Педиатрический дайджест — {os.environ.get('DIGEST_DATE', '')}".strip(" —")
    message["From"] = sender
    message["To"] = recipient
    message.set_content(text_path.read_text(encoding="utf-8") if text_path.is_file() else "Откройте HTML-версию письма.")
    message.add_alternative(html_path.read_text(encoding="utf-8"), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)
    print(f"Письмо отправлено на {recipient}")


if __name__ == "__main__":
    main()
