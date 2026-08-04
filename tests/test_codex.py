import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from balances import codex


class CodexCredentialSafetyTests(unittest.TestCase):
    def test_expired_login_is_reported_without_refreshing_or_rewriting_auth_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            original = {
                "tokens": {
                    "access_token": "expired-access",
                    "refresh_token": "must-remain-untouched",
                    "account_id": "account-id",
                },
                "last_refresh": "2026-08-04T00:00:00+00:00",
            }
            auth_path.write_text(json.dumps(original))

            with (
                patch.object(config, "CODEX_AUTH_JSON", auth_path),
                patch.dict(os.environ, {}, clear=True),
                patch.object(codex, "_request", return_value=(401, None)),
                patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError("不应调用 OAuth token 刷新接口"),
                ),
            ):
                result = codex.fetch()

            self.assertEqual(
                result.sub,
                "Codex 登录已失效，请重新登录以刷新凭据",
            )
            self.assertEqual(json.loads(auth_path.read_text()), original)


if __name__ == "__main__":
    unittest.main()
