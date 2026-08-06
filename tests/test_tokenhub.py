import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from balances import tokenhub
from balances.base import AccountBalance

# 官方 SDK 交叉验证向量（tencentcloud-sdk-python 3.1.150 的 Sign.sign_tc3 生成，
# 规范化步骤与其 abstract_client._get_tc3_signature 完全一致）
SDK_VECTOR = (
    "TC3-HMAC-SHA256 Credential=test-secret-id/2025-08-04/tokenhub/tc3_request, "
    "SignedHeaders=content-type;host, "
    "Signature=33f458587d2560497f6bd00c230a07649a4c974ed421dccb4de0116ae5ccb64d"
)

SAMPLE_DETAIL = {
    "TeamId": "tp-ent-abcdefgh",
    "Name": "生产环境套餐",
    "ProductType": "enterprise",
    "Status": "enable",
    "StopReason": "NORMAL",
    "ApiKeyCount": 5,
    "PackageInfo": {
        "TotalQuota": "1000000",
        "TotalUsed": "100000",
        "TotalCycles": 6,
        "CycleUnit": "month",
        "StartTime": "2026-04-01T00:00:00Z",
        "ExpireTime": "2027-04-01T00:00:00Z",
        "CycleQuota": "200000",
        "CurrentCycle": 2,
        "RemainCycles": 4,
    },
}

NO_ENV_FILE = Path("/nonexistent-tokenhub/.env")


class Tc3SignatureTests(unittest.TestCase):
    def test_signature_matches_official_sdk_vector(self) -> None:
        sig = tokenhub._sign(
            secret_key="test-secret-key",
            secret_id="test-secret-id",
            timestamp=1754294400,
            date="2025-08-04",
            payload=b'{"TeamId":"tp-ent-test"}',
        )
        self.assertEqual(sig, SDK_VECTOR)


class TokenHubParseTests(unittest.TestCase):
    def test_parse_enterprise_plan(self) -> None:
        r = tokenhub._parse_plan(SAMPLE_DETAIL)
        self.assertIsInstance(r, AccountBalance)
        self.assertEqual(r.name, "TOKENHUB")
        self.assertEqual(r.headline, "900,000 credits")
        self.assertEqual(r.plan, "生产环境套餐")
        self.assertAlmostEqual(r.usage_pct or 0, 10.0)
        self.assertIn("第2/6期", r.sub)
        self.assertIn("到期 2027-04-01", r.sub)
        self.assertEqual(r.status, "ok")
        self.assertFalse(r.alert)
        self.assertEqual(len(r.windows), 1)
        self.assertEqual(r.windows[0].label, "主包")

    def test_parse_enterprise_auto_uses_tokens_unit(self) -> None:
        sample = dict(SAMPLE_DETAIL, ProductType="enterprise-auto")
        r = tokenhub._parse_plan(sample)
        self.assertEqual(r.headline, "900,000 tokens")

    def test_parse_high_usage_alerts(self) -> None:
        sample = json.loads(json.dumps(SAMPLE_DETAIL))
        sample["PackageInfo"]["TotalUsed"] = "900000"
        r = tokenhub._parse_plan(sample)
        self.assertTrue(r.alert)
        self.assertEqual(r.headline, "100,000 credits")

    def test_parse_exhausted_stop_reason_alerts(self) -> None:
        sample = dict(SAMPLE_DETAIL, StopReason="EXHAUSTED")
        r = tokenhub._parse_plan(sample)
        self.assertTrue(r.alert)
        self.assertEqual(r.status, "ok")

    def test_parse_disabled_plan_marks_error(self) -> None:
        sample = dict(SAMPLE_DETAIL, Status="disable")
        r = tokenhub._parse_plan(sample)
        self.assertEqual(r.status, "error")

    def test_parse_empty_package(self) -> None:
        r = tokenhub._parse_plan({"TeamId": "tp-x"})
        self.assertEqual(r.headline, "0 units")
        self.assertIsNone(r.usage_pct)
        self.assertFalse(r.alert)


SAMPLE_BALANCE = {
    "Uin": 100010216979,
    "RealBalance": 3232,
    "CashAccountBalance": 3232,
    "IncomeIntoAccountBalance": 0,
    "PresentAccountBalance": 0,
    "FreezeAmount": 0,
    "OweAmount": 0,
    "Balance": 3232,
}


class TokenHubBalanceParseTests(unittest.TestCase):
    def test_parse_account_balance_converts_fen_to_yuan(self) -> None:
        r = tokenhub._parse_balance(SAMPLE_BALANCE)
        self.assertEqual(r.name, "TOKENHUB")
        # 接口金额单位为"分"：3232 分 = ¥32.32
        self.assertEqual(r.headline, "¥32.32")
        self.assertEqual(r.plan, "TokenHub 按量计费")
        self.assertIn("充值 ¥32.32", r.sub)
        self.assertIsNone(r.usage_pct)
        self.assertEqual(r.status, "ok")
        self.assertFalse(r.alert)
        self.assertIn('"mode": "balance"', r.raw)
        self.assertIn('"unit": "分"', r.raw)

    def test_parse_low_balance_alerts(self) -> None:
        # 500 分 = ¥5.00，低于 ¥10 阈值
        sample = dict(SAMPLE_BALANCE, Balance=500, CashAccountBalance=500)
        r = tokenhub._parse_balance(sample)
        self.assertTrue(r.alert)
        self.assertEqual(r.headline, "¥5.00")

    def test_parse_owe_amount_marks_error_and_alerts(self) -> None:
        # 欠费 5000 分 = ¥50.00
        sample = dict(SAMPLE_BALANCE, Balance=-5000, OweAmount=5000)
        r = tokenhub._parse_balance(sample)
        self.assertEqual(r.status, "error")
        self.assertTrue(r.alert)
        self.assertEqual(r.headline, "¥-50.00")


class TeamIdPickTests(unittest.TestCase):
    def test_prefers_enabled_plan(self) -> None:
        plans = {
            "TokenPlanSet": [
                {"TeamId": "tp-disabled", "Status": "disable"},
                {"TeamId": "tp-enabled", "Status": "enable"},
            ]
        }
        self.assertEqual(tokenhub._pick_team_id(plans), "tp-enabled")

    def test_falls_back_to_first_plan(self) -> None:
        plans = {"TokenPlanSet": [{"TeamId": "tp-only", "Status": "disable"}]}
        self.assertEqual(tokenhub._pick_team_id(plans), "tp-only")

    def test_raises_when_empty(self) -> None:
        with self.assertRaises(RuntimeError):
            tokenhub._pick_team_id({"TokenPlanSet": []})


class TokenHubCredentialTests(unittest.TestCase):
    def test_credentials_read_from_environment(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TENCENTCLOUD_SECRET_ID": "sid",
                    "TENCENTCLOUD_SECRET_KEY": "skey",
                    "TOKENHUB_TEAM_ID": "tp-1",
                },
                clear=False,
            ),
            patch.object(config, "ENV_FILE", NO_ENV_FILE),
        ):
            creds = config.tokenhub_credentials()
        self.assertEqual(creds["secret_id"], "sid")
        self.assertEqual(creds["secret_key"], "skey")
        self.assertEqual(creds["team_id"], "tp-1")

    def test_fetch_reports_missing_credentials_without_network(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "ENV_FILE", NO_ENV_FILE),
            patch("urllib.request.urlopen", side_effect=AssertionError("不应发起网络请求")),
        ):
            r = tokenhub.fetch()
        self.assertEqual(r.status, "error")
        self.assertIn("SecretId/SecretKey", r.raw)

    def test_fetch_uses_explicit_team_id_in_single_call(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TENCENTCLOUD_SECRET_ID": "sid",
                    "TENCENTCLOUD_SECRET_KEY": "skey",
                    "TOKENHUB_TEAM_ID": "tp-1",
                },
                clear=False,
            ),
            patch.object(config, "ENV_FILE", NO_ENV_FILE),
            patch.object(tokenhub, "_call", return_value=SAMPLE_DETAIL) as call,
        ):
            r = tokenhub.fetch()
        self.assertEqual(r.status, "ok")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[2], "DescribeTokenPlan")
        self.assertEqual(call.call_args.args[3], {"TeamId": "tp-1"})

    def test_fetch_auto_picks_team_id_with_two_calls(self) -> None:
        plan_list = {
            "TokenPlanSet": [
                {"TeamId": "tp-disabled", "Status": "disable"},
                {"TeamId": "tp-enabled", "Status": "enable"},
            ]
        }
        with (
            patch.dict(
                os.environ,
                {"TENCENTCLOUD_SECRET_ID": "sid", "TENCENTCLOUD_SECRET_KEY": "skey"},
                clear=False,
            ),
            patch.object(config, "ENV_FILE", NO_ENV_FILE),
            patch.object(
                tokenhub, "_call", side_effect=[plan_list, SAMPLE_DETAIL]
            ) as call,
        ):
            r = tokenhub.fetch()
        self.assertEqual(r.status, "ok")
        actions = [c.args[2] for c in call.call_args_list]
        self.assertEqual(actions, ["DescribeTokenPlanList", "DescribeTokenPlan"])
        self.assertEqual(call.call_args_list[1].args[3], {"TeamId": "tp-enabled"})

    def test_fetch_falls_back_to_account_balance_without_plans(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"TENCENTCLOUD_SECRET_ID": "sid", "TENCENTCLOUD_SECRET_KEY": "skey"},
                clear=False,
            ),
            patch.object(config, "ENV_FILE", NO_ENV_FILE),
            patch.object(
                tokenhub, "_call", side_effect=[{"TokenPlanSet": []}, SAMPLE_BALANCE]
            ) as call,
        ):
            r = tokenhub.fetch()
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.headline, "¥32.32")
        actions = [c.args[2] for c in call.call_args_list]
        self.assertEqual(actions, ["DescribeTokenPlanList", "DescribeAccountBalance"])
        self.assertEqual(call.call_args_list[1].kwargs["service"], tokenhub.BILLING_SERVICE)


if __name__ == "__main__":
    unittest.main()
