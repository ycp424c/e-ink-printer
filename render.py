"""把各账户余额渲染成 400x300 黑白红墨水屏图片（epdiy UC8176）。

颜色约定：
- 黑色 (0,0,0)       文字 / 边框 / 进度条
- 红色 (204,0,0)     告警、高风险进度条和少量结构性视觉锚点

注意：次要文字不再用灰色。电子墨水屏是 1-bit，灰色只能依靠 Floyd-Steinberg
抖动模拟成半调点阵，会让 10~11px 小字发糊，所以统一用黑色 + 字号/字重区分层级。
"""

from __future__ import annotations

import argparse
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from balances import AccountBalance, WindowUsage, fetch_all

WIDTH, HEIGHT = 400, 300
BG = (255, 255, 255)
FG = (0, 0, 0)
RED = (204, 0, 0)
DEFAULT_TITLE = "AI Dashboard"

MARGIN = 8
GAP = 8
GRID_TOP = 47
GRID_BOTTOM = HEIGHT - MARGIN

PINGFANG = "/System/Library/Fonts/PingFang.ttc"
HELVETICA = "/System/Library/Fonts/Helvetica.ttc"
# PingFang.ttc index：2 Regular / 5 Medium / 8 Semibold / 11 Light
# Helvetica.ttc index：0 Regular / 1 Bold

_ALERT_PCT = 80.0  # 用量超过该值红色高亮
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _pf(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    index = {"regular": 2, "medium": 5, "semibold": 8, "light": 11}[weight]
    return ImageFont.truetype(PINGFANG, size, index=index)


def _hv(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(HELVETICA, size, index=1 if bold else 0)


def _display_font(text: str, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """为中文内容选用有完整字形的 PingFang，其余内容使用 Helvetica。"""
    if any(ord(char) > 127 for char in text):
        return _pf(size, "semibold" if bold else "regular")
    return _hv(size, bold)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, start: int, max_w: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """从 start 开始递减字号直到 text 宽度不超过 max_w。"""
    size = start
    while size > 10:
        font = _display_font(text, size, bold=bold)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size -= 2
    return _display_font(text, 10, bold=bold)


def _ellipsize_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    """把 text 截断到不超过 max_w，必要时加省略号。

    注意：不能用 ``text[:-1] + '…'`` 这种简单替换，因为 ``…`` 可能比被替换字符更宽，
    导致宽度不减反增，陷入死循环。
    """
    if not text or draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…" if text else "…"


def _draw_text_at_visual_top(
    draw: ImageDraw.ImageDraw,
    x: float,
    visual_top: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    *,
    right_aligned: bool = False,
) -> None:
    """按字形实际边界定位文字，消除不同字体内部留白造成的错位。"""
    left, top, right, _ = draw.textbbox((0, 0), text, font=font)
    visual_width = right - left
    visual_left = x - visual_width if right_aligned else x
    draw.text((round(visual_left - left), round(visual_top - top)), text, font=font, fill=fill)


def _window_label(label: str) -> str:
    """把短标签补成更易读的展示文案。"""
    if label.endswith("窗"):
        return f"{label[:-1]}窗口"
    return label


def _draw_card_frame(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    balance: AccountBalance,
) -> None:
    """绘制卡片边框和红色视觉锚点。

    健康状态只使用一小段红线作为装饰；告警/错误状态扩展为整条红线，
    从而让红色既能平衡画面，又不会削弱告警语义。
    """
    x0, y0, x1, _ = box
    draw.rectangle(box, outline=FG, width=1)
    accent_end = x1 - 1 if (balance.alert or balance.status == "error") else x0 + 30
    draw.line((x0 + 1, y0 + 1, accent_end, y0 + 1), fill=RED, width=2)


def _draw_card_header(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    balance: AccountBalance,
) -> None:
    """绘制账户名，以及互不碰撞的套餐或状态标签。"""
    x0, y0, x1, _ = box
    pad = 8
    accent = RED if (balance.alert or balance.status == "error") else FG
    name_font = _hv(13, bold=True)
    draw.text((x0 + pad, y0 + 6), balance.name, font=name_font, fill=accent)

    status_label = ""
    if balance.status == "pending":
        status_label = "未接入"
    elif balance.status == "error":
        status_label = "查询异常"
    right_text = status_label or balance.plan
    if not right_text:
        return

    right_font = _display_font(right_text, 11, bold=bool(status_label))
    name_w = draw.textlength(balance.name, font=name_font)
    available = max(20, x1 - x0 - 2 * pad - name_w - 10)
    right_text = _ellipsize_text(draw, right_text, right_font, available)
    right_w = draw.textlength(right_text, font=right_font)
    draw.text(
        (x1 - pad - right_w, y0 + 6),
        right_text,
        font=right_font,
        fill=RED if status_label else FG,
    )


def _draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    pct: float,
    *,
    alert: bool,
) -> None:
    """绘制硬边进度条，避免二值化后边缘出现灰色噪点。"""
    height = 9
    pct = max(0.0, min(100.0, pct))
    draw.rectangle((x, y, x + width, y + height), outline=FG, width=1)
    inner_width = max(0, width - 2)
    fill_width = round(inner_width * pct / 100.0)
    if fill_width > 0:
        draw.rectangle(
            (x + 1, y + 1, x + fill_width, y + height - 1),
            fill=RED if alert else FG,
        )


def _draw_usage_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    balance: AccountBalance,
) -> None:
    """绘制订阅用量卡：主百分比只出现一次，进度条负责视觉编码。"""
    x0, y0, x1, y1 = box
    pad = 8
    accent = RED if (balance.alert or balance.status == "error") else FG

    headline_font = _fit_font(draw, balance.headline, 30, x1 - x0 - 2 * pad - 28)
    headline_y = y0 + 25
    draw.text((x0 + pad, headline_y), balance.headline, font=headline_font, fill=accent)
    headline_w = draw.textlength(balance.headline, font=headline_font)
    used_font = _pf(11, "semibold")
    draw.text((x0 + pad + headline_w + 5, y0 + 39), "已用", font=used_font, fill=RED)

    windows = list(balance.windows)
    if not windows and balance.usage_pct is not None:
        windows = [WindowUsage(label="", pct=balance.usage_pct)]

    if not windows:
        return

    label_font = _pf(11, "medium")
    first = windows[0]
    first_label = _window_label(first.label) or "当前窗口"
    draw.text((x0 + pad, y0 + 62), first_label, font=label_font, fill=FG)

    sub_text = _ellipsize_text(draw, balance.sub or "", label_font, 112)
    if sub_text:
        sub_w = draw.textlength(sub_text, font=label_font)
        draw.text((x1 - pad - sub_w, y0 + 62), sub_text, font=label_font, fill=FG)

    bar_width = x1 - x0 - 2 * pad
    _draw_progress_bar(
        draw,
        x0 + pad,
        y0 + 78,
        bar_width,
        first.pct,
        alert=balance.alert or first.pct >= _ALERT_PCT,
    )

    # 400x300 屏幕最多展示两个窗口；更多窗口由数据层保留，避免越界。
    if len(windows) > 1 and y0 + 122 < y1:
        second = windows[1]
        second_label = _window_label(second.label) or "次级窗口"
        second_pct = f"{int(max(0.0, min(100.0, second.pct)))}%"
        second_pct_w = draw.textlength(second_pct, font=label_font)
        second_alert = balance.alert or second.pct >= _ALERT_PCT
        draw.text((x0 + pad, y0 + 98), second_label, font=label_font, fill=FG)
        draw.text(
            (x1 - pad - second_pct_w, y0 + 98),
            second_pct,
            font=label_font,
            fill=RED if second_alert else FG,
        )
        _draw_progress_bar(
            draw,
            x0 + pad,
            y0 + 114,
            bar_width,
            second.pct,
            alert=second_alert,
        )


def _draw_value_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    balance: AccountBalance,
) -> None:
    """绘制余额、待配置和错误状态等紧凑卡片。"""
    x0, y0, x1, _ = box
    pad = 8
    accent = RED if (balance.alert or balance.status == "error") else FG
    headline_start = 25 if balance.status == "pending" else 29
    headline_font = _fit_font(draw, balance.headline, headline_start, x1 - x0 - 2 * pad)
    _draw_text_at_visual_top(
        draw,
        x0 + pad,
        y0 + 29,
        balance.headline,
        headline_font,
        accent,
    )

    detail = balance.sub or ""
    if balance.status == "pending" and balance.plan:
        detail = f"{balance.plan} · {detail}" if detail else balance.plan
    detail_font = _display_font(detail, 11)
    detail = _ellipsize_text(draw, detail, detail_font, x1 - x0 - 2 * pad)
    if detail:
        draw.text((x0 + pad, y0 + 63), detail, font=detail_font, fill=FG)


def _draw_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], balance: AccountBalance) -> None:
    _draw_card_frame(draw, box, balance)
    _draw_card_header(draw, box, balance)
    if balance.windows or balance.usage_pct is not None:
        _draw_usage_card(draw, box, balance)
    else:
        _draw_value_card(draw, box, balance)


def _row_density(row: list[AccountBalance]) -> float:
    """按一行中最复杂的卡片分配高度，避免固定网格造成上下失衡。"""
    window_count = max(
        (len(balance.windows) or (1 if balance.usage_pct is not None else 0) for balance in row),
        default=0,
    )
    if window_count >= 2:
        return 1.35
    if window_count == 1:
        return 1.10
    return 0.90


def _grid_boxes(balances: list[AccountBalance]) -> list[tuple[int, int, int, int]]:
    """为最多四张卡片生成内容感知的 2 列网格。"""
    visible = balances[:4]
    if not visible:
        return []

    rows = [visible[index : index + 2] for index in range(0, len(visible), 2)]
    available_height = GRID_BOTTOM - GRID_TOP - GAP * (len(rows) - 1)
    densities = [_row_density(row) for row in rows]
    density_total = sum(densities)
    heights: list[int] = []
    allocated = 0
    for index, density in enumerate(densities):
        height = (
            available_height - allocated
            if index == len(densities) - 1
            else round(available_height * density / density_total)
        )
        heights.append(height)
        allocated += height

    inner_width = WIDTH - 2 * MARGIN
    card_width = (inner_width - GAP) // 2
    boxes: list[tuple[int, int, int, int]] = []
    y = GRID_TOP
    for row, height in zip(rows, heights):
        for column in range(len(row)):
            x = MARGIN + column * (card_width + GAP)
            boxes.append((x, y, x + card_width, y + height))
        y += height + GAP
    return boxes


def render_image(
    balances: list[AccountBalance],
    now: datetime | None = None,
    *,
    title: str = DEFAULT_TITLE,
) -> Image.Image:
    now = now or datetime.now()
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # ── 顶栏 ────────────────────────────────────────────────
    title = title.strip() or DEFAULT_TITLE
    title_font = _fit_font(draw, title, 18, 265, bold=True)
    title = _ellipsize_text(draw, title, title_font, 265)
    _, title_top, _, title_bottom = draw.textbbox((0, 0), title, font=title_font)
    title_height = title_bottom - title_top
    title_visual_top = round((40 - title_height) / 2)
    draw.rectangle((12, title_visual_top - 2, 17, title_visual_top + title_height + 2), fill=RED)
    _draw_text_at_visual_top(draw, 24, title_visual_top, title, title_font, FG)

    date_text = f"{now:%m-%d} {_WEEKDAYS[now.weekday()]}"
    date_font = _display_font(date_text, 13)
    time_text = f"{now:%H:%M}"
    time_font = _hv(17, bold=True)
    right_x = WIDTH - 12
    _draw_text_at_visual_top(draw, right_x, 2, date_text, date_font, FG, right_aligned=True)
    _draw_text_at_visual_top(draw, right_x, 22, time_text, time_font, RED, right_aligned=True)
    draw.line((12, 40, WIDTH - 12, 40), fill=FG, width=1)
    draw.line((12, 40, 72, 40), fill=RED, width=3)

    # ── 内容感知的 2 列卡片网格 ──────────────────────────────
    for balance, box in zip(balances[:4], _grid_boxes(balances)):
        _draw_card(draw, box, balance)

    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="渲染余额墨水屏图片")
    parser.add_argument("--out", default="logs/preview.png", help="输出 PNG 路径")
    parser.add_argument("--balances", help="逗号分隔过滤（如 codex,kimi），默认全部")
    parser.add_argument("--title", default=DEFAULT_TITLE, help=f"看板标题（默认 {DEFAULT_TITLE}）")
    args = parser.parse_args()

    wanted = {name.strip().lower() for name in args.balances.split(",")} if args.balances else None
    balances = [b for b in fetch_all() if not wanted or b.name.lower() in wanted]
    img = render_image(balances, title=args.title)
    from pathlib import Path

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"rendered {len(balances)} accounts -> {args.out}")


if __name__ == "__main__":
    main()
