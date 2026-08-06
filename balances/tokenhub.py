"""腾讯云 TokenHub 余额查询（双模式自动切换）。

TokenHub 有两种计费方式，查询通道都是腾讯云 API 3.0（TC3-HMAC-SHA256 签名，
仅标准库实现）：

1. Token Plan 预付费套餐（tokenhub.tencentcloudapi.com，版本 2026-03-22）：
   - DescribeTokenPlanList：列出账号下的套餐（含 PackageInfo 额度包信息）
   - DescribeTokenPlan：查询单个套餐详情（含当前周期 Token 用量明细）
   通过 TOKENHUB_TEAM_ID 指定套餐；未指定时自动选择第一个启用中的套餐。

2. 按量计费（billing.tencentcloudapi.com，版本 2018-07-09）：
   - DescribeAccountBalance：腾讯云账户余额（TokenHub 按日从账户余额扣费）
   账号下没有任何套餐时自动回退到该模式。

凭据来源见 config.tokenhub_credentials()（进程环境变量 / 项目 .env）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import config
from balances.base import AccountBalance, WindowUsage, error_balance

HOST = "tokenhub.tencentcloudapi.com"
SERVICE = "tokenhub"
VERSION = "2026-03-22"
REGION = "ap-guangzhou"
ENDPOINT = f"https://{HOST}/"
TIMEOUT = 15

# 套餐主包用量超过该百分比时红色高亮（与 Codex 卡片口径一致）
HIGH_USAGE_PCT = 80.0
# 按量计费账户余额低于该阈值（CNY）时红色高亮（与 DeepSeek 卡片口径一致）
LOW_BALANCE_CNY = 10.0

# 套餐类型：企业版专业套餐（credits）/ 企业版轻享套餐（tokens）
PRODUCT_ENTERPRISE = "enterprise"
PRODUCT_ENTERPRISE_AUTO = "enterprise-auto"

# 按量计费回退查询（腾讯云账户余额）
BILLING_SERVICE = "billing"
BILLING_HOST = "billing.tencentcloudapi.com"
BILLING_VERSION = "2018-07-09"


def _sign(
    secret_key: str,
    secret_id: str,
    timestamp: int,
    date: str,
    payload: bytes,
    *,
    service: str = SERVICE,
    host: str = HOST,
) -> str:
    """腾讯云 API 3.0 TC3-HMAC-SHA256 签名（仅标准库实现）。"""
    content_type = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{content_type}\nhost:{host}\n"
    signed_headers = "content-type;host"
    payload_hash = hashlib.sha256(payload).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, payload_hash]
    )
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            str(timestamp),
            f"{date}/{service}/tc3_request",
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    secret_date = hmac.new(f"TC3{secret_key}".encode(), date.encode(), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, service.encode(), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return (
        f"TC3-HMAC-SHA256 Credential={secret_id}/{date}/{service}/tc3_request, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


def _http_error(exc: urllib.error.HTTPError) -> RuntimeError:
    """把云 API 的 HTTP 错误响应（含 Error 结构）转成可读异常。"""
    try:
        parsed = json.loads(exc.read())
        error = (parsed.get("Response") or {}).get("Error") or {}
        code, message = error.get("Code", ""), error.get("Message", "")
        detail = f"{code}: {message}" if code else str(exc)
        return RuntimeError(f"HTTP {exc.code} {detail}".strip())
    except (json.JSONDecodeError, AttributeError):
        return RuntimeError(f"HTTP {exc.code}")


def _call(
    secret_id: str,
    secret_key: str,
    action: str,
    payload: dict,
    *,
    service: str = SERVICE,
    host: str = HOST,
    version: str = VERSION,
) -> dict:
    """发起一次云 API 3.0 请求并返回 Response 对象；出错时抛异常。"""
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
    authorization = _sign(secret_key, secret_id, timestamp, date, body, service=service, host=host)
    req = urllib.request.Request(
        f"https://{host}/",
        data=body,
        method="POST",
        headers={
            "Host": host,
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": authorization,
            "X-TC-Action": action,
            "X-TC-Version": version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": REGION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    response = (json.loads(raw) or {}).get("Response") or {}
    error = response.get("Error")
    if error:
        raise RuntimeError(f"{error.get('Code', '')}: {error.get('Message', '')}".strip())
    return response


def _pick_team_id(plan_list: dict) -> str:
    """从 DescribeTokenPlanList 响应中选择套餐 ID：优先启用中的套餐。"""
    plans = plan_list.get("TokenPlanSet") or []
    if not plans:
        raise RuntimeError("TokenPlanSet 为空：账号下没有 Token Plan 套餐")
    chosen = next((p for p in plans if p.get("Status") == "enable"), plans[0])
    team_id = chosen.get("TeamId")
    if not team_id:
        raise RuntimeError("套餐缺少 TeamId")
    return team_id


def _quota_unit(product_type: str) -> str:
    if product_type == PRODUCT_ENTERPRISE:
        return "credits"
    if product_type == PRODUCT_ENTERPRISE_AUTO:
        return "tokens"
    return "units"


def _to_number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: float) -> str:
    return f"{int(round(value)):,}"


def _parse_plan(detail: dict) -> AccountBalance:
    """把 DescribeTokenPlan 响应解析为 AccountBalance（套餐模式）。"""
    package = detail.get("PackageInfo") or {}
    total = _to_number(package.get("TotalQuota"))
    used = _to_number(package.get("TotalUsed"))
    unit = _quota_unit(detail.get("ProductType", ""))
    remaining = max(total - used, 0.0)
    usage_pct = used / total * 100 if total else None

    sub_parts: list[str] = []
    cycle, cycles = package.get("CurrentCycle"), package.get("TotalCycles")
    if cycle is not None and cycles:
        sub_parts.append(f"第{cycle}/{cycles}期")
    expire = package.get("ExpireTime", "")
    if expire:
        try:
            when = datetime.fromisoformat(expire.replace("Z", "+00:00"))
            sub_parts.append(f"到期 {when:%Y-%m-%d}")
        except ValueError:
            sub_parts.append(f"到期 {expire[:10]}")
    if cycle_quota := _to_number(package.get("CycleQuota")):
        sub_parts.append(f"当期 {_fmt(cycle_quota)}")

    stop = detail.get("StopReason", "NORMAL")
    alert = bool(usage_pct is not None and usage_pct > HIGH_USAGE_PCT) or stop in (
        "EXHAUSTED",
        "ISOLATED",
    )
    windows = []
    if usage_pct is not None:
        windows.append(
            WindowUsage(label="主包", pct=usage_pct, sub=f"{_fmt(used)}/{_fmt(total)}")
        )

    return AccountBalance(
        name="TOKENHUB",
        headline=f"{_fmt(remaining)} {unit}",
        plan=detail.get("Name") or "Token Plan",
        sub=" · ".join(sub_parts),
        usage_pct=usage_pct,
        status="ok" if detail.get("Status") == "enable" else "error",
        alert=alert,
        raw=json.dumps(
            {
                "mode": "plan",
                "team_id": detail.get("TeamId"),
                "product_type": detail.get("ProductType"),
                "status": detail.get("Status"),
                "stop_reason": stop,
                "total": package.get("TotalQuota"),
                "used": package.get("TotalUsed"),
                "cycle_quota": package.get("CycleQuota"),
                "expire": expire,
            },
            ensure_ascii=False,
        ),
        windows=windows,
    )


def _parse_balance(response: dict) -> AccountBalance:
    """把 DescribeAccountBalance 响应解析为 AccountBalance（按量计费模式）。

    注意：接口所有金额字段单位均为"分"（见
    https://cloud.tencent.com.cn/document/api/555/20253），此处统一除以 100 转元。
    """
    balance_fen = _to_number(response.get("Balance"))
    cash_fen = _to_number(response.get("CashAccountBalance"))
    present_fen = _to_number(response.get("PresentAccountBalance"))
    owe_fen = _to_number(response.get("OweAmount"))
    balance = balance_fen / 100
    return AccountBalance(
        name="TOKENHUB",
        headline=f"¥{balance:,.2f}",
        plan="TokenHub 按量计费",
        sub=f"充值 ¥{cash_fen / 100:,.2f} · 赠金 ¥{present_fen / 100:,.2f}",
        status="ok" if owe_fen == 0 else "error",
        alert=balance < LOW_BALANCE_CNY or owe_fen > 0,
        raw=json.dumps(
            {
                "mode": "balance",
                "unit": "分",
                "balance_fen": balance_fen,
                "cash_fen": cash_fen,
                "present_fen": present_fen,
                "owe_fen": owe_fen,
            },
            ensure_ascii=False,
        ),
    )


def fetch() -> AccountBalance:
    creds = config.tokenhub_credentials()
    if not creds.get("secret_id") or not creds.get("secret_key"):
        return error_balance("TOKENHUB", "未找到腾讯云 SecretId/SecretKey（.env 或环境变量）")
    secret_id, secret_key = creds["secret_id"], creds["secret_key"]
    team_id = creds.get("team_id")
    try:
        if team_id:
            detail = _call(secret_id, secret_key, "DescribeTokenPlan", {"TeamId": team_id})
            return _parse_plan(detail)
        plan_list = _call(secret_id, secret_key, "DescribeTokenPlanList", {})
        if plan_list.get("TokenPlanSet"):
            detail = _call(
                secret_id, secret_key, "DescribeTokenPlan", {"TeamId": _pick_team_id(plan_list)}
            )
            return _parse_plan(detail)
        balance = _call(
            secret_id,
            secret_key,
            "DescribeAccountBalance",
            {},
            service=BILLING_SERVICE,
            host=BILLING_HOST,
            version=BILLING_VERSION,
        )
        return _parse_balance(balance)
    except Exception as exc:  # noqa: BLE001
        return error_balance("TOKENHUB", f"请求失败: {exc}")


if __name__ == "__main__":
    r = fetch()
    print(json.dumps({k: getattr(r, k) for k in ("name", "headline", "plan", "sub", "status", "alert", "raw")}, ensure_ascii=False, indent=2))
