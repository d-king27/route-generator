#!/usr/bin/env python3
"""Email the next unchecked walk, then mark that entry as sent."""

import argparse
import os
from pathlib import Path
import re
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from urllib.parse import urlencode


SCHEDULE_FILE = Path(__file__).resolve().with_name(
    "constituency_every_house_walks_m22_4fp.txt"
)
WALK_PATTERN = re.compile(
    r"^\[ \] (?P<title>Walk \d{2}: [^\r\n]+)(?:\r?\n|\Z)"
    r".*?"
    r"(?=^\[[ Xx]\] Walk \d{2}:|^[ \t]*(?:={3,}|-{3,})[ \t]*\r?$|\Z)",
    re.MULTILINE | re.DOTALL,
)


def maps_search_url(query: str) -> str:
    """Build a Google Maps place search without an API key or network call."""
    return "https://www.google.com/maps/search/?" + urlencode(
        {"api": "1", "query": query}
    )


def build_email_body(walk_text: str, schedule_text: str) -> str:
    """Append map searches; street descriptions do not define an exact route."""
    lines = [walk_text, "", "Google Maps (place searches):"]
    start = re.search(r"^Starting Location:[ \t]*([^\r\n]+)", schedule_text, re.MULTILINE)
    if start:
        lines.extend(["Starting point:", maps_search_url(start.group(1).strip())])
    else:
        lines.extend(["Walk area:", maps_search_url("Northenden, Manchester, UK")])

    targets = re.search(
        r"^[ \t]*-[ \t]*Target Streets:[ \t]*([^\r\n]+)", walk_text, re.MULTILINE
    )
    if targets:
        # Keep descriptions verbatim; Google searches them rather than treating
        # them as verified coordinates. Manchester disambiguates common names.
        for target in targets.group(1).rstrip(". ").split(","):
            target = target.strip()
            if target:
                lines.extend(["", f"Find {target}:", maps_search_url(f"{target}, Manchester, UK")])

    lines.extend([
        "",
        "These links search for places, not the complete walking route. "
        "Broad descriptions may need refining in Maps. Check the locations "
        "and follow the written walk instructions.",
    ])
    return "\n".join(lines)


def run(schedule_file: Path = SCHEDULE_FILE, *, dry_run: bool = False) -> None:
    # Reading bytes preserves the original line endings and UTF-8 encoding.
    text = schedule_file.read_bytes().decode("utf-8")
    match = WALK_PATTERN.search(text)
    if match is None:
        print("All walks are complete! No uncompleted walks remain.")
        return

    subject = f"\U0001f6b6 Everyday Walk: {match.group('title').strip()}"
    body = build_email_body(match.group(0).strip(), text)
    if dry_run:
        print(f"Subject: {subject}\n\n{body}\n\nPreview only; nothing changed.")
        return

    names = ("SENDER_EMAIL", "SENDER_PASSWORD", "RECIPIENT_EMAIL")
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise SystemExit("Missing environment variables: " + ", ".join(missing))

    sender = os.environ["SENDER_EMAIL"].strip()
    recipient = os.environ["RECIPIENT_EMAIL"].strip()
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    # Replace only this entry's checkbox, preserving every other byte.
    start = match.start()
    updated = text[:start] + "[X]" + text[start + 3:]

    # Stage the update before sending, then atomically replace the schedule
    # after SMTP succeeds. Failed authentication/sending leaves it unchanged.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=schedule_file.parent, prefix=".walk-", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(updated.encode("utf-8"))

        with smtplib.SMTP_SSL(
            "smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30
        ) as smtp:
            smtp.login(sender, os.environ["SENDER_PASSWORD"])
            smtp.send_message(message, from_addr=sender, to_addrs=[recipient])

        temporary_path.replace(schedule_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    print(f"Email sent and checklist updated: {match.group('title')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without email or file changes."
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
