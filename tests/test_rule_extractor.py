from __future__ import annotations

import unittest
from datetime import datetime, timezone

from job_tracker.extractor import RuleBasedExtractor
from job_tracker.models import EmailRecord


class RuleBasedExtractorTests(unittest.TestCase):
    def test_detects_rejection(self) -> None:
        email = EmailRecord(
            message_id="msg-1",
            subject="Update regarding your Software Engineer application",
            from_address="Acme Careers <careers@acme.com>",
            date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            body=(
                "Thank you for applying to Acme for the Software Engineer position. "
                "Unfortunately, we will not be moving forward."
            ),
        )

        updates = RuleBasedExtractor(["application", "unfortunately"]).extract(email)

        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].status, "rejected")
        self.assertEqual(updates[0].company, "Acme")
        self.assertEqual(updates[0].role, "Software Engineer")

    def test_ignores_unrelated_email(self) -> None:
        email = EmailRecord(
            message_id="msg-2",
            subject="Dinner plans",
            from_address="friend@example.com",
            date=datetime(2026, 6, 1, tzinfo=timezone.utc),
            body="Want to grab dinner tomorrow?",
        )

        updates = RuleBasedExtractor(["application", "interview"]).extract(email)

        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
