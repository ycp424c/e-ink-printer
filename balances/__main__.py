"""`python -m balances`：打印全部账户余额摘要。"""

from __future__ import annotations

import json

from balances import fetch_all


def main() -> None:
    for balance in fetch_all():
        print(json.dumps(
            {k: getattr(balance, k) for k in ("name", "headline", "plan", "sub", "usage_pct", "status", "alert", "raw")},
            ensure_ascii=False, default=str,
        ))


if __name__ == "__main__":
    main()
