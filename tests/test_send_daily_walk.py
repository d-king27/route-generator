import contextlib
import io
import os
from pathlib import Path
import smtplib
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import send_daily_walk as walks


SECRETS = {
    "SENDER_EMAIL": "sender@example.com",
    "SENDER_PASSWORD": "fake-app-password",
    "RECIPIENT_EMAIL": "recipient@example.com",
}
SAMPLE = (
    "Overview [ ]\n"
    "[X] Walk 01: Already sent\n    First route\n\n"
    "[ ] Walk 02: Today's route\n    Second route\n\n"
    "[X] Walk 03: Also sent\n    Third route\n\n"
    "========\nSUMMARY: [ ] / 3\n"
)


class DailyWalkTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "schedule.txt"
        self.path.write_bytes(SAMPLE.encode("utf-8"))
        self.output = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(patch.dict(os.environ, SECRETS, clear=True))
        self.smtp_factory = self.enterContext(patch.object(walks.smtplib, "SMTP_SSL"))
        self.smtp = self.smtp_factory.return_value.__enter__.return_value
        self.smtp.send_message.return_value = {}

    def test_sends_only_first_pending_entry_and_changes_only_its_checkbox(self):
        self.smtp.send_message.side_effect = lambda *a, **k: self.assertEqual(
            self.path.read_bytes(), SAMPLE.encode("utf-8")
        )
        walks.run(self.path)
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "🚶 Everyday Walk: Walk 02: Today's route")
        self.assertEqual(message["From"], SECRETS["SENDER_EMAIL"])
        self.assertEqual(message["To"], SECRETS["RECIPIENT_EMAIL"])
        self.assertEqual(message.get_content_type(), "text/plain")
        self.assertEqual(
            message.get_content().split("\n\nGoogle Maps", 1)[0],
            "[ ] Walk 02: Today's route\n    Second route",
        )
        self.assertEqual(
            self.path.read_bytes(),
            SAMPLE.replace("[ ] Walk 02:", "[X] Walk 02:").encode("utf-8"),
        )
        self.smtp.login.assert_called_once_with(
            SECRETS["SENDER_EMAIL"], SECRETS["SENDER_PASSWORD"]
        )
        self.assertEqual(self.smtp_factory.call_args.args, ("smtp.gmail.com", 465))
        context = self.smtp_factory.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(list(self.path.parent.glob(".walk-*")), [])

    def test_actual_attachment_advances_all_60_walks_and_then_stops(self):
        original = walks.SCHEDULE_FILE.read_bytes()
        self.path.write_bytes(original)
        for number in range(1, 61):
            walks.run(self.path)
            message = self.smtp.send_message.call_args.args[0]
            self.assertTrue(message["Subject"].startswith(f"🚶 Everyday Walk: Walk {number:02}:"))
            body = message.get_content()
            self.assertEqual(len(body.split("\n\nGoogle Maps", 1)[0].splitlines()), 5)
            self.assertIn("Starting point:\nhttps://www.google.com/maps/search/?api=1&query=", body)
            self.assertIn("\nFind ", body)
            self.assertNotIn("SECTOR", body)
            self.assertNotIn("PROGRESS SUMMARY", body)
        self.assertEqual(self.smtp.send_message.call_count, 60)
        expected = original
        for number in range(1, 61):
            expected = expected.replace(
                f"[ ] Walk {number:02}:".encode(), f"[X] Walk {number:02}:".encode(), 1
            )
        self.assertEqual(self.path.read_bytes(), expected)
        with patch.dict(os.environ, {}, clear=True):
            walks.run(self.path)
        self.assertEqual(self.smtp.send_message.call_count, 60)
        self.assertIn("All walks are complete!", self.output.getvalue())

    def test_dividers_and_end_of_file_bound_email(self):
        for ending in ("", "\n===\nNext section", "\n---\nNext section"):
            with self.subTest(ending=ending):
                self.path.write_text("[ ] Walk 09: Last\n    Route" + ending, encoding="utf-8")
                walks.run(self.path)
                message = self.smtp.send_message.call_args.args[0]
                self.assertEqual(
                    message.get_content().split("\n\nGoogle Maps", 1)[0],
                    "[ ] Walk 09: Last\n    Route",
                )

    def test_lowercase_completed_entry_ends_pending_entry(self):
        self.path.write_text(SAMPLE.replace("[X] Walk 03", "[x] Walk 03"), encoding="utf-8")
        walks.run(self.path)
        message = self.smtp.send_message.call_args.args[0]
        self.assertNotIn("Third route", message.get_content())

    def test_crlf_and_unicode_are_preserved(self):
        original = SAMPLE.replace("Second route", "Café — riverside").replace("\n", "\r\n")
        self.path.write_bytes(original.encode("utf-8"))
        walks.run(self.path)
        self.assertEqual(
            self.path.read_bytes(),
            original.replace("[ ] Walk 02:", "[X] Walk 02:").encode("utf-8"),
        )

    def test_dry_run_needs_no_secrets_and_does_not_change_file(self):
        with patch.dict(os.environ, {}, clear=True):
            walks.run(self.path, dry_run=True)
        self.smtp_factory.assert_not_called()
        self.assertEqual(self.path.read_bytes(), SAMPLE.encode("utf-8"))
        self.assertIn("Subject: 🚶 Everyday Walk: Walk 02:", self.output.getvalue())
        self.assertIn("Google Maps (place searches):", self.output.getvalue())

    def test_same_sender_and_recipient_is_supported(self):
        with patch.dict(os.environ, {"RECIPIENT_EMAIL": SECRETS["SENDER_EMAIL"]}):
            walks.run(self.path)
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(message["From"], message["To"])
        self.assertEqual(
            self.smtp.send_message.call_args.kwargs["to_addrs"], [SECRETS["SENDER_EMAIL"]]
        )

    def test_map_links_preserve_places_and_encode_special_characters(self):
        original_walk = (
            "[ ] Walk 01: Village\n"
            "    - Target Streets: St Hilda's Rd, Café & Park Lane.\n"
            "    - Return: Home."
        )
        schedule = "Starting Location: Saint Hilda's Road, Manchester (M22 4FP)\r\n"
        body = walks.build_email_body(original_walk, schedule)
        self.assertTrue(body.startswith(original_walk + "\n\n"))
        urls = [line for line in body.splitlines() if line.startswith("https://")]
        self.assertEqual(len(urls), 3)
        expected_places = [
            "Saint Hilda's Road, Manchester (M22 4FP)",
            "St Hilda's Rd, Manchester, UK",
            "Café & Park Lane, Manchester, UK",
        ]
        for url, place in zip(urls, expected_places):
            parsed = urlsplit(url)
            self.assertEqual(parsed.netloc, "www.google.com")
            self.assertEqual(parsed.path, "/maps/search/")
            self.assertEqual(parse_qs(parsed.query), {"api": ["1"], "query": [place]})
        self.assertIn("not the complete walking route", body)

    def test_missing_location_fields_use_area_map(self):
        body = walks.build_email_body("[ ] Walk 01: A walk", "No location header")
        self.assertIn("Walk area:", body)
        self.assertNotIn("Starting point:", body)
        self.assertNotIn("\nFind ", body)
        url = next(line for line in body.splitlines() if line.startswith("https://"))
        self.assertEqual(parse_qs(urlsplit(url).query)["query"], ["Northenden, Manchester, UK"])

    def test_missing_secrets_fail_before_sending(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL"):
                walks.run(self.path)
        self.smtp_factory.assert_not_called()
        self.assertEqual(self.path.read_bytes(), SAMPLE.encode("utf-8"))

    def test_authentication_failure_does_not_advance_checklist(self):
        self.smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Rejected")
        with self.assertRaises(smtplib.SMTPAuthenticationError):
            walks.run(self.path)
        self.smtp.send_message.assert_not_called()
        self.assertEqual(self.path.read_bytes(), SAMPLE.encode("utf-8"))
        self.assertEqual(list(self.path.parent.glob(".walk-*")), [])

    def test_send_failure_does_not_advance_checklist(self):
        self.smtp.send_message.side_effect = smtplib.SMTPException("Send failed")
        with self.assertRaises(smtplib.SMTPException):
            walks.run(self.path)
        self.assertEqual(self.path.read_bytes(), SAMPLE.encode("utf-8"))
        self.assertEqual(list(self.path.parent.glob(".walk-*")), [])

    def test_missing_schedule_does_not_send(self):
        with self.assertRaises(FileNotFoundError):
            walks.run(self.path.parent / "missing.txt")
        self.smtp_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
