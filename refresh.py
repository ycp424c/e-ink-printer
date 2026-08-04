#!/usr/bin/env python3
"""主流程：查询全部账户余额 → 渲染 400x300 墨水屏图片 → BLE 上传刷新。

用法：
    .venv/bin/python refresh.py              # 完整流程（查余额 + 渲染 + 上传）
    .venv/bin/python refresh.py --dry-run    # 只查余额 + 渲染，不连蓝牙

launchd 每 30 分钟调用一次（见 scheduler/）。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from balances import AccountBalance, fetch_all
from render import DEFAULT_TITLE, render_image

ROOT = Path(__file__).resolve().parent
VENDOR_DISPLAY = ROOT / "vendor" / "epdiy_display.py"
LOG_DIR = ROOT / "logs"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("eink")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler = logging.FileHandler(LOG_DIR / "refresh.log", encoding="utf-8")
    handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(handler)
    logger.addHandler(console)
    return logger


def log_balance_summaries(
    logger: logging.Logger,
    balances: list[AccountBalance],
    *,
    include_values: bool = False,
) -> None:
    """记录查询状态；默认不把余额、套餐或重置时间写入持久日志。"""
    for balance in balances:
        if include_values:
            logger.info(
                "  %-9s %-12s %-14s %s [pct=%s status=%s alert=%s]",
                balance.name,
                balance.headline,
                balance.plan,
                balance.sub,
                f"{balance.usage_pct:.0f}%" if balance.usage_pct is not None else "—",
                balance.status,
                balance.alert,
            )
        else:
            logger.info(
                "  %-9s status=%s alert=%s",
                balance.name,
                balance.status,
                balance.alert,
            )


def run_upload(
    logger: logging.Logger,
    image_path: Path,
    *,
    slot: int,
    name_prefix: str,
    ble_timeout: float,
) -> bool:
    """调用 vendor/epdiy_display.py 完成 BLE 上传 + 刷新。"""
    # 小字在 1-bit 屏上最怕 Floyd-Steinberg 抖动破坏笔画边缘，
    # 因此用硬阈值二值化并抬高 black_threshold，让抗锯齿边缘也能黑得实。
    cmd = [
        sys.executable,
        str(VENDOR_DISPLAY),
        "upload",
        str(image_path),
        "--slot",
        str(slot),
        "--overwrite-slot",
        "--name-prefix",
        name_prefix,
        "--timeout",
        str(ble_timeout),
        "--dither",
        "none",
        "--black-threshold",
        "160",
    ]
    logger.info("upload cmd: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        logger.error("BLE 上传超时（180s）")
        return False
    for line in (proc.stdout or "").splitlines():
        logger.info("display: %s", line)
    for line in (proc.stderr or "").splitlines():
        logger.warning("display(stderr): %s", line)
    if proc.returncode != 0:
        logger.error("BLE 上传失败，退出码 %s", proc.returncode)
        return False
    try:
        result = json.loads(proc.stdout)
        logger.info(
            "upload ok: device=%s slot=%s refresh_sent=%s slot_persisted=%s",
            result.get("device_name"),
            result.get("slot"),
            result.get("refresh_sent"),
            result.get("slot_persisted"),
        )
    except json.JSONDecodeError:
        logger.warning("upload 输出无法解析为 JSON，但退出码为 0")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只查询 + 渲染，不连蓝牙")
    parser.add_argument("--out", default=str(LOG_DIR / "latest.png"), help="渲染输出 PNG")
    parser.add_argument("--title", default=DEFAULT_TITLE, help=f"看板标题（默认 {DEFAULT_TITLE}）")
    parser.add_argument(
        "--verbose-balances",
        action="store_true",
        help="在日志中记录余额、套餐和重置时间（默认脱敏）",
    )
    parser.add_argument("--slot", type=int, default=0, help="墨水屏槽位（默认 0）")
    parser.add_argument("--name-prefix", default="NRF_EPD_", help="BLE 设备名前缀")
    parser.add_argument(
        "--ble-timeout",
        type=float,
        default=60.0,
        help="BLE 设备发现/连接超时秒数（默认 60）",
    )
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("===== 开始刷新 =====")

    balances = fetch_all()
    log_balance_summaries(logger, balances, include_values=args.verbose_balances)

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image = render_image(balances, title=args.title)
    image.save(out_path)
    logger.info("已渲染 %d 个账户 -> %s", len(balances), out_path)

    if args.dry_run:
        logger.info("dry-run：跳过 BLE 上传")
        return 0

    ok = run_upload(
        logger,
        out_path,
        slot=args.slot,
        name_prefix=args.name_prefix,
        ble_timeout=args.ble_timeout,
    )
    logger.info("===== 刷新%s =====", "成功" if ok else "失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
