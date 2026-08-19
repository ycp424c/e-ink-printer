import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _http_error(code: int) -> Exception:
    return urllib.error.HTTPError(codex.USAGE_URL, code, "err", {}, None)


def _ok_resp(payload: bytes = b'{"plan_type": "prolite"}') -> MagicMock:
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.status = 200
    resp.read.return_value = payload
    return resp


class CodexRetryTests(unittest.TestCase):
    """_request 对瞬时故障重试、对登录失效直接返回。"""

    def test_http_5xx_retries_then_succeeds(self) -> None:
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen",
                side_effect=[_http_error(502), _http_error(502), _ok_resp()],
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual((status, body), (200, {"plan_type": "prolite"}))
        self.assertEqual(mock_sleep.call_count, 2)

    def test_network_error_retries_then_succeeds(self) -> None:
        err = urllib.error.URLError("boom")
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen",
                side_effect=[err, err, _ok_resp()],
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual((status, body), (200, {"plan_type": "prolite"}))
        self.assertEqual(mock_sleep.call_count, 2)

    def test_401_not_retried(self) -> None:
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen", side_effect=[_http_error(401)]
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual(status, 401)
        self.assertEqual(mock_sleep.call_count, 0)

    def test_404_not_retried(self) -> None:
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen", side_effect=[_http_error(404)]
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual(status, 404)
        self.assertEqual(mock_sleep.call_count, 0)

    def test_5xx_exhausted_returns_last_status(self) -> None:
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen",
                side_effect=[_http_error(503)] * codex.MAX_ATTEMPTS,
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual(status, 503)
        self.assertEqual(body, None)
        self.assertEqual(mock_sleep.call_count, codex.MAX_ATTEMPTS - 1)

    def test_network_error_exhausted_raises(self) -> None:
        err = urllib.error.URLError("boom")
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen",
                side_effect=[err] * codex.MAX_ATTEMPTS,
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    codex._request(codex.USAGE_URL, token="tok", account_id="acc")
        self.assertIn("网络错误", str(ctx.exception))
        self.assertEqual(mock_sleep.call_count, codex.MAX_ATTEMPTS - 1)

    def test_bad_json_retries(self) -> None:
        with patch("balances.codex.time.sleep") as mock_sleep:
            with patch(
                "urllib.request.urlopen",
                side_effect=[
                    _ok_resp(b"<html>not json</html>"),
                    _ok_resp(),
                ],
            ):
                status, body = codex._request(
                    codex.USAGE_URL, token="tok", account_id="acc"
                )
        self.assertEqual((status, body), (200, {"plan_type": "prolite"}))
        self.assertEqual(mock_sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
