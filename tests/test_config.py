import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class CredentialResolutionTests(unittest.TestCase):
    def test_explicit_codex_environment_overrides_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_auth = Path(temp_dir) / "missing-auth.json"
            with (
                patch.object(config, "CODEX_AUTH_JSON", missing_auth),
                patch.dict(
                    os.environ,
                    {
                        "CODEX_ACCESS_TOKEN": "explicit-access",
                        "CODEX_ACCOUNT_ID": "explicit-account",
                    },
                    clear=False,
                ),
            ):
                tokens = config.codex_tokens()

        self.assertEqual(tokens.get("access_token"), "explicit-access")
        self.assertEqual(tokens.get("account_id"), "explicit-account")

    def test_codex_refresh_token_is_not_exposed_to_providers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "tokens": {
                            "access_token": "access",
                            "refresh_token": "refresh-must-stay-private",
                            "account_id": "account",
                        }
                    }
                )
            )
            with (
                patch.object(config, "CODEX_AUTH_JSON", auth_path),
                patch.dict(os.environ, {}, clear=True),
            ):
                tokens = config.codex_tokens()

        self.assertEqual(tokens["access_token"], "access")
        self.assertEqual(tokens["account_id"], "account")
        self.assertNotIn("refresh_token", tokens)


if __name__ == "__main__":
    unittest.main()
