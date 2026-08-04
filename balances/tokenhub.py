"""腾讯云 TokenHub 余额 — 待配置占位。

调研结论：tokenhub.tencentmaas.com 网关没有公开的余额 REST 接口
（/v1/user/balance、/v1/balance 等实测全 404，仅 /v1/models 存在）。
官方查询方式走控制台统计页，或腾讯云云 API 3.0 的 DescribeTokenPlan（需
SecretId/SecretKey + TeamId，TC3 签名）。

拿到凭据后只需补这个模块：实现 fetch() 返回 AccountBalance 即可，其余不动。
"""

from __future__ import annotations

from .base import AccountBalance


def fetch() -> AccountBalance:
    return AccountBalance(
        name="TOKENHUB",
        headline="待配置",
        plan="腾讯云 TokenHub",
        sub="暂无查询凭据",
        status="pending",
        alert=False,
        raw="tokenhub 余额查询尚未接入；需 TokenHub key 或腾讯云 SecretId/TeamId",
    )


if __name__ == "__main__":
    import json

    r = fetch()
    print(json.dumps({k: getattr(r, k) for k in ("name", "headline", "plan", "sub", "status", "alert", "raw")}, ensure_ascii=False, indent=2))
