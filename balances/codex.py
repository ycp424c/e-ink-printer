"""Codex / ChatGPT 订阅额度查询。

接口：GET https://chatgpt.com/backend-api/wham/usage
鉴权：Authorization: Bearer <access_token> + ChatGPT-Account-Id + User-Agent: codex-cli
返回：{ plan_type, rate_limit: { primary_window/secondary_window: { limit_window_seconds, used_percent, reset_at } }, credits }

本模块只读使用 access_token；登录过期时提示用户通过 Codex 自身重新登录，绝不刷新或
改写 ~/.codex/auth.json。
"""

from __future__ import annotations

import json
import time
import urllib.request

import config

from .base import AccountBalance, WindowUsage, error_balance

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

PLAN_LABELS = {
    "pro": "Pro",
    "prolite": "Pro Lite",
    "plus": "Plus",
    "free": "Free",
    "team": "Team",
}


def _request(url: str, *, token: str, account_id: str | None, timeout: int = 15) -> tuple[int, dict | None]:
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "codex-cli",
        "Accept": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"网络错误: {exc}") from exc


def fetch() -> AccountBalance:
    tokens = config.codex_tokens()
    access = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not access:
        return error_balance("CODEX", "未找到 Codex access_token（~/.codex/auth.json）")

    status, body = _request(USAGE_URL, token=access, account_id=account_id)
    if status in (401, 403):
        return error_balance("CODEX", "Codex 登录已失效，请重新登录以刷新凭据")
    if status != 200 or body is None:
        return error_balance("CODEX", f"wham/usage HTTP {status}")

    plan_type = body.get("plan_type", "")
    plan = PLAN_LABELS.get(plan_type, plan_type or "订阅")

    # 兼容 rate_limit.xxx 与顶层 xxx 两种响应形态
    rl = body.get("rate_limit") or {}
    windows = []
    for key in ("primary_window", "secondary_window"):
        win = rl.get(key) or (body.get(key) if not rl else None)
        if win:
            windows.append((key, win))

    used_pct: float | None = None
    window_usages: list[WindowUsage] = []
    window_sub = ""
    for key, win in windows:
        pct = win.get("used_percent")
        secs = win.get("limit_window_seconds")
        label = {18000: "5h", 604800: "周", 2_592_000: "30天"}.get(secs, f"{secs // 3600}h")
        pct_f = float(pct) if pct is not None else None
        reset = win.get("reset_at")
        reset_s = time.strftime("%m-%d %H:%M", time.localtime(int(reset))) if reset else ""
        if key == "primary_window":
            used_pct = pct_f
            if reset_s:
                window_sub = f"重置 {reset_s}"
            if pct_f is not None:
                window_usages.append(WindowUsage(label=f"{label}窗", pct=pct_f))
        else:
            if pct_f is not None:
                window_usages.append(WindowUsage(label=f"{label}窗", pct=pct_f))

    credits = body.get("credits") or {}
    balance = credits.get("balance") or "0"
    if credits.get("has_credits") and float(balance or 0) > 0:
        window_sub = (window_sub + " · " if window_sub else "") + f"credits ¥{balance}"

    headline = f"{int(used_pct)}%" if used_pct is not None else "—"
    # plan 模式：用量占比过高红色高亮；余额模式（credits）：低于 ¥10 红色高亮
    alert = used_pct is not None and used_pct > 80
    if credits.get("has_credits"):
        try:
            if float(credits.get("balance") or 0) < 10.0:
                alert = True
        except ValueError:
            pass
    return AccountBalance(
        name="CODEX",
        headline=headline,
        plan=plan,
        sub=window_sub or "额度正常",
        usage_pct=used_pct,
        alert=alert,
        windows=window_usages,
        raw=f"plan_type={plan_type} windows={json.dumps([w for _, w in windows], ensure_ascii=False)} credits={json.dumps(credits)}",
    )


if __name__ == "__main__":
    r = fetch()
    print(json.dumps({k: getattr(r, k) for k in ("name", "headline", "plan", "sub", "usage_pct", "status", "alert", "raw")}, ensure_ascii=False, indent=2))
