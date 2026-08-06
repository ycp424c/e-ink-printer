import io
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import refresh
from balances import AccountBalance


class RefreshLockTests(unittest.TestCase):
    def test_second_acquire_is_denied_while_first_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "refresh.lock"
            first = refresh.acquire_lock(lock_path)
            self.assertIsNotNone(first)
            second = refresh.acquire_lock(lock_path)
            self.assertIsNone(second)
            first.close()
            third = refresh.acquire_lock(lock_path)
            self.assertIsNotNone(third)
            third.close()

    def test_lock_records_current_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "refresh.lock"
            handle = refresh.acquire_lock(lock_path)
            self.assertEqual(lock_path.read_text().strip(), str(os.getpid()))
            handle.close()

    def test_main_skips_early_when_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "refresh.lock"
            with (
                patch.object(refresh, "LOCK_FILE", lock_path),
                patch.object(
                    refresh,
                    "fetch_all",
                    side_effect=AssertionError("锁被占用时不应发起查询"),
                ),
                patch.object(sys, "argv", ["refresh.py", "--dry-run"]),
            ):
                first = refresh.acquire_lock(refresh.LOCK_FILE)
                code = refresh.main()
                first.close()
        self.assertEqual(code, 0)


class RefreshLoggingPrivacyTests(unittest.TestCase):
    def test_default_balance_logs_omit_financial_and_reset_details(self) -> None:
        stream = io.StringIO()
        logger = logging.getLogger(self.id())
        logger.handlers.clear()
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(stream))
        balances = [
            AccountBalance(
                name="DEEPSEEK",
                headline="¥58.73",
                plan="API 余额",
                sub="充值 ¥58.73 · 赠金 ¥0.00 · 重置 08-11 09:25",
                status="ok",
            )
        ]

        refresh.log_balance_summaries(logger, balances)

        output = stream.getvalue()
        self.assertIn("DEEPSEEK", output)
        self.assertIn("status=ok", output)
        self.assertNotIn("58.73", output)
        self.assertNotIn("08-11", output)


if __name__ == "__main__":
    unittest.main()
