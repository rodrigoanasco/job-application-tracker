from __future__ import annotations

import unittest
from datetime import datetime, timezone

from job_tracker.email_client import filter_relevant_emails
from job_tracker.models import EmailRecord


KEYWORDS = [
    "thank you for applying",
    "your application",
    "interview",
    "assessment",
    "unfortunately",
]

EXCLUDES = [
    "jobs for you",
    "more jobs in",
    "apply now",
]


class EmailFilterTests(unittest.TestCase):
    def test_skips_job_alert_subjects(self) -> None:
        email = EmailRecord(
            message_id="alert",
            subject="DevOps Engineer at Monark and 7 more jobs in Chilliwack, BC for you. Apply Now.",
            from_address="jobs@example.com",
            date=datetime(2026, 6, 9, tzinfo=timezone.utc),
            body="These recommended jobs match your profile. Apply now to this role.",
        )

        self.assertEqual(filter_relevant_emails([email], KEYWORDS, EXCLUDES), [])

    def test_keeps_application_update(self) -> None:
        email = EmailRecord(
            message_id="update",
            subject="Update on your application",
            from_address="Acme Careers <careers@acme.com>",
            date=datetime(2026, 6, 9, tzinfo=timezone.utc),
            body="Thank you for applying to Acme. We would like to schedule an interview.",
        )

        self.assertEqual(filter_relevant_emails([email], KEYWORDS, EXCLUDES), [email])

    def test_weak_body_words_do_not_select_newsletters(self) -> None:
        email = EmailRecord(
            message_id="newsletter",
            subject="Your weekly roundup",
            from_address="jobs@example.com",
            date=datetime(2026, 6, 9, tzinfo=timezone.utc),
            body="This role is a good match. See the position details and application link.",
        )

        self.assertEqual(
            filter_relevant_emails(
                [email],
                ["application", "position", "role", "interview"],
                EXCLUDES,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
