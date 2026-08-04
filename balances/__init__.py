"""余额查询聚合入口。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .base import AccountBalance, WindowUsage, error_balance
from . import codex, deepseek, kimi, tokenhub

PROVIDERS = (
    ("codex", codex.fetch),
    ("kimi", kimi.fetch),
    ("deepseek", deepseek.fetch),
    ("tokenhub", tokenhub.fetch),
)


def fetch_all() -> list[AccountBalance]:
    """并发查询全部账户，单个失败不影响其余。"""
    results: list[AccountBalance] = []
    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as pool:
        futures = {pool.submit(fetch_fn): name for name, fetch_fn in PROVIDERS}
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                results.append(error_balance(futures[future].upper(), f"未捕获异常: {exc}"))
    return sorted(results, key=lambda r: [name for name, _ in PROVIDERS].index(r.name.lower()))


if __name__ == "__main__":
    import json

    for balance in fetch_all():
        print(json.dumps(
            {k: getattr(balance, k) for k in ("name", "headline", "plan", "sub", "usage_pct", "status", "alert", "raw")},
            ensure_ascii=False, default=str,
        ))
