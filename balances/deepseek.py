"""DeepSeek API 平台余额查询。

接口：GET https://api.deepseek.com/user/balance
鉴权：Authorization: Bearer <api_key>
返回：{ is_available, balance_infos: [{ currency, total_balance, granted_balance, topped_up_balance }] }
"""

from __future__ import annotations

import json
import urllib.request

import config
from balances.base import AccountBalance, error_balance

BALANCE_URL = "https://api.deepseek.com/user/balance"
# 余额模式：总余额低于该阈值（CNY）时红色高亮
LOW_BALANCE_CNY = 10.0


def _get_balance(key: str) -> dict:
    req = urllib.request.Request(
        BALANCE_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


_SYMBOLS = {"CNY": "¥", "USD": "$"}


def _parse(infos: list[dict]) -> tuple[str, str]:
    """按 currency 返回 (display_text, cny_total)；优先 CNY，其次 USD。

    显示统一为符号前缀（¥/$），与 TokenHub 余额卡片风格一致。
    """
    by_currency = {info.get("currency"): info for info in infos}
    for currency in ("CNY", "USD"):
        if currency in by_currency:
            total = by_currency[currency].get("total_balance") or "0.00"
            return f"{_SYMBOLS.get(currency, currency + ' ')}{total}", total
    return "—", "0.00"


def fetch() -> AccountBalance:
    key = config.deepseek_api_key()
    if not key:
        return error_balance("DEEPSEEK", "未找到 DeepSeek API Key（cc-switch 或 .env）")
    try:
        body = _get_balance(key)
    except Exception as exc:  # noqa: BLE001
        return error_balance("DEEPSEEK", f"请求失败: {exc}")

    infos = body.get("balance_infos") or []
    display, cny_total = _parse(infos)
    cny = next((i for i in infos if i.get("currency") == "CNY"), {})
    granted = cny.get("granted_balance") or "0.00"
    topped_up = cny.get("topped_up_balance") or "0.00"
    try:
        low = float(cny_total) < LOW_BALANCE_CNY
    except ValueError:
        low = False
    return AccountBalance(
        name="DEEPSEEK",
        headline=display,
        plan="API 余额",
        sub=f"充值 ¥{topped_up} · 赠金 ¥{granted}",
        status="ok" if body.get("is_available", True) else "error",
        alert=low,
        raw=f"is_available={body.get('is_available')} infos={json.dumps(infos, ensure_ascii=False)}",
    )


if __name__ == "__main__":
    r = fetch()
    print(json.dumps({k: getattr(r, k) for k in ("name", "headline", "plan", "sub", "status", "alert", "raw")}, ensure_ascii=False, indent=2))
