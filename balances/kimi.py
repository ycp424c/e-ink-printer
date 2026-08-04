"""Kimi Coding Plan 套餐额度查询。

接口：GET https://api.kimi.com/coding/v1/usages
鉴权：Authorization: Bearer <api_key>
返回：{ usage: { limit, used, remaining, resetTime },
        limits: [{ window: { duration, timeUnit }, detail: { limit, remaining, resetTime } }],
        user: { membership: { level } } }
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime

import config
from balances.base import AccountBalance, WindowUsage, error_balance

USAGES_URL = "https://api.kimi.com/coding/v1/usages"
# plan 模式：剩余配额低于该值时红色高亮
ALERT_REMAINING = 20

LEVEL_LABELS = {
    "LEVEL_BASIC": "基础",
    "LEVEL_INTERMEDIATE": "中阶",
    "LEVEL_ADVANCED": "高阶",
    "LEVEL_PRO": "专业",
}


def _fmt_reset(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return iso[:16]


def _get_usages(key: str) -> dict:
    req = urllib.request.Request(
        USAGES_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch() -> AccountBalance:
    key = config.kimi_api_key()
    if not key:
        return error_balance("KIMI", "未找到 Kimi API Key（cc-switch 或 .env）")
    try:
        body = _get_usages(key)
    except Exception as exc:  # noqa: BLE001
        return error_balance("KIMI", f"请求失败: {exc}")

    usage = body.get("usage") or {}
    level = (body.get("user") or {}).get("membership", {}).get("level", "")
    plan = LEVEL_LABELS.get(level, level.replace("LEVEL_", "") or "会员")

    try:
        limit = float(usage.get("limit") or 0)
        used = float(usage.get("used") or 0)
        remaining = float(usage.get("remaining") or 0)
    except ValueError:
        limit = used = remaining = 0.0

    reset = _fmt_reset(usage.get("resetTime", ""))

    # 5 小时滚动窗口
    window_usages: list[WindowUsage] = []
    for item in body.get("limits") or []:
        detail = item.get("detail") or {}
        if (item.get("window") or {}).get("duration") == 300:
            fh_limit = float(detail.get("limit") or 0)
            fh_remaining = float(detail.get("remaining") or 0)
            fh_used = max(0.0, fh_limit - fh_remaining)
            fh_pct = (fh_used / fh_limit * 100.0) if fh_limit > 0 else 0.0
            window_usages.append(WindowUsage(label="5h窗", pct=fh_pct))
            break

    usage_pct = (used / limit * 100.0) if limit > 0 else None
    if usage_pct is not None:
        window_usages.insert(0, WindowUsage(label="套餐", pct=usage_pct, sub=f"重置 {reset}" if reset else ""))

    sub = f"重置 {reset}" if reset else ""
    headline = f"{int(usage_pct)}%" if usage_pct is not None else "—"
    # plan 模式：剩余配额低于阈值，或用量占比过高 → 红色高亮
    quota_low = limit > 0 and remaining < ALERT_REMAINING
    alert = quota_low or (usage_pct is not None and usage_pct > 80)
    return AccountBalance(
        name="KIMI",
        headline=headline,
        plan=f"Coding Plan · {plan}",
        sub=sub,
        usage_pct=usage_pct,
        alert=alert,
        windows=window_usages,
        raw=f"level={level} limit={limit} used={used} remaining={remaining} reset={usage.get('resetTime')}",
    )


if __name__ == "__main__":
    r = fetch()
    print(json.dumps({k: getattr(r, k) for k in ("name", "headline", "plan", "sub", "usage_pct", "status", "alert", "raw")}, ensure_ascii=False, indent=2))
