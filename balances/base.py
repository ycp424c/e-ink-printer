"""归一化的账户余额数据，供渲染层直接消费。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WindowUsage:
    """一个额度窗口的用量，用于在卡片内渲染独立进度条。"""

    label: str       # 显示标签，如 "周窗"、"5h窗"、"Plan"
    pct: float       # 0~100 用量百分比
    sub: str = ""    # 补充文字，如重置时间（可选）


@dataclass
class AccountBalance:
    name: str                        # 账户名，如 "CODEX"
    headline: str = "—"              # 主数字，如 "¥62.94"、"58/100"、"21%"
    plan: str = ""                   # 套餐/等级，如 "prolite"、"中阶"
    sub: str = ""                    # 次行说明，如 "重置 08:00 · 5h窗 100"
    usage_pct: float | None = None   # 0~100，供进度条；余额类账户为 None
    status: str = "ok"               # ok / error / pending
    alert: bool = False              # True 时渲染层用红色高亮（低余额/高用量）
    raw: str = ""                    # 原始摘要（仅日志，不渲染）
    queried_at: datetime = field(default_factory=datetime.now)
    windows: list[WindowUsage] = field(default_factory=list)  # 多窗口进度条


def error_balance(name: str, message: str) -> AccountBalance:
    return AccountBalance(
        name=name,
        headline="查询失败",
        plan="",
        sub=message[:60],
        status="error",
        alert=True,
        raw=message,
    )
