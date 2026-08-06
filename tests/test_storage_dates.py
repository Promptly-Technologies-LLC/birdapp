from __future__ import annotations

import unittest
from datetime import UTC, datetime

from birdapp.storage import dates as storage_dates


class TestStorageDates(unittest.TestCase):
    def test_coerce_datetime_parses_sqlite_timestamp(self) -> None:
        value = "2026-01-22 21:04:29.000000"
        parsed = storage_dates.coerce_datetime(value)

        expected = datetime(2026, 1, 22, 21, 4, 29, tzinfo=UTC)
        self.assertEqual(parsed, expected)

    def test_coerce_datetime_handles_none(self) -> None:
        self.assertIsNone(storage_dates.coerce_datetime(None))
