import io
import logging
import unittest

import refresh
from balances import AccountBalance


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
                headline="CNY 58.73",
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
