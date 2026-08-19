import unittest
import unittest.mock
from datetime import datetime

from PIL import Image, ImageDraw

import render
from balances import AccountBalance, WindowUsage


class FontLoadingTests(unittest.TestCase):
    def test_pf_loads_vendored_noto_by_default(self) -> None:
        font = render._pf(11, "medium")
        self.assertTrue(font.path.endswith("NotoSansSC-Medium.otf"))

    def test_hv_loads_vendored_dejavu_by_default(self) -> None:
        font = render._hv(13, bold=True)
        self.assertTrue(font.path.endswith("DejaVuSans-Bold.ttf"))

    def test_pf_falls_back_when_vendored_font_missing(self) -> None:
        # vendor 字体缺失时回退到系统字体；CI 上系统字体也不存在则明确报错。
        with unittest.mock.patch.dict(render._NOTO_FILES, {"medium": "/nonexistent/NopeSC-Medium.otf"}):
            try:
                font = render._pf(11, "medium")
            except OSError:
                return
        self.assertNotEqual(font.path, "/nonexistent/NopeSC-Medium.otf")

    def test_pf_error_lists_all_candidates_when_all_missing(self) -> None:
        with unittest.mock.patch.dict(render._NOTO_FILES, {"medium": "/nonexistent/NopeSC-Medium.otf"}):
            with unittest.mock.patch.object(render, "PINGFANG", "/nonexistent/NopePingFang.ttc"):
                with self.assertRaises(OSError) as ctx:
                    render._pf(11, "medium")
        message = str(ctx.exception)
        self.assertIn("NopeSC-Medium.otf", message)
        self.assertIn("NopePingFang.ttc", message)


class EllipsizeTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.draw = ImageDraw.Draw(Image.new("RGB", (400, 300)))
        self.font = render._pf(11, "medium")

    def test_overlong_text_is_shortened_and_fits(self) -> None:
        ellipsize = getattr(render, "_ellipsize_text", None)
        self.assertIsNotNone(ellipsize, "render._ellipsize_text 尚未实现")

        text = "Coding Plan · 中阶"
        result = ellipsize(self.draw, text, self.font, 85)

        self.assertNotEqual(result, text)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(self.draw.textlength(result, font=self.font), 85)

    def test_text_that_already_fits_is_unchanged(self) -> None:
        ellipsize = getattr(render, "_ellipsize_text", None)
        self.assertIsNotNone(ellipsize, "render._ellipsize_text 尚未实现")

        text = "Pro Lite"
        result = ellipsize(self.draw, text, self.font, 85)

        self.assertEqual(result, text)


def _sample_balances(*, alert: bool = False) -> list[AccountBalance]:
    return [
        AccountBalance(
            name="CODEX",
            headline="32%",
            plan="Pro Lite",
            sub="重置 08-08 17:15",
            usage_pct=32,
            alert=alert,
            windows=[WindowUsage(label="周窗", pct=32)],
        ),
        AccountBalance(
            name="KIMI",
            headline="11%",
            plan="Coding Plan · 中阶",
            sub="重置 08-11 09:25",
            usage_pct=11,
            windows=[
                WindowUsage(label="套餐", pct=11),
                WindowUsage(label="5h窗", pct=6),
            ],
        ),
        AccountBalance(
            name="DEEPSEEK",
            headline="¥58.81",
            plan="API 余额",
            sub="充值 ¥58.81 · 赠金 ¥0.00",
        ),
        AccountBalance(
            name="TOKENHUB",
            headline="待配置",
            plan="腾讯云 TokenHub",
            sub="暂无查询凭据",
            status="pending",
        ),
    ]


class DashboardLayoutTests(unittest.TestCase):
    def test_default_title_is_generic(self) -> None:
        self.assertEqual(render.DEFAULT_TITLE, "AI Dashboard")

    def test_custom_title_changes_only_the_header(self) -> None:
        now = datetime(2026, 8, 4, 13, 48)
        default_image = render.render_image(_sample_balances(), now)
        custom_image = render.render_image(_sample_balances(), now, title="Team Dashboard")

        self.assertNotEqual(
            default_image.crop((0, 0, render.WIDTH, render.GRID_TOP)).tobytes(),
            custom_image.crop((0, 0, render.WIDTH, render.GRID_TOP)).tobytes(),
        )
        self.assertEqual(
            default_image.crop((0, render.GRID_TOP, render.WIDTH, render.HEIGHT)).tobytes(),
            custom_image.crop((0, render.GRID_TOP, render.WIDTH, render.HEIGHT)).tobytes(),
        )

    def test_usage_row_receives_more_height_than_value_row(self) -> None:
        boxes = render._grid_boxes(_sample_balances())

        self.assertEqual(len(boxes), 4)
        top_height = boxes[0][3] - boxes[0][1]
        bottom_height = boxes[2][3] - boxes[2][1]
        self.assertGreater(top_height, bottom_height)
        self.assertEqual(boxes[0][3] + render.GAP, boxes[2][1])
        self.assertEqual(boxes[-1][3], render.GRID_BOTTOM)

    def test_healthy_dashboard_has_structural_red_accents(self) -> None:
        image = render.render_image(_sample_balances(), datetime(2026, 8, 4, 13, 48))

        self.assertEqual(image.size, (400, 300))
        self.assertEqual(image.getpixel((13, 20)), render.RED)  # 标题左侧锚点
        self.assertEqual(image.getpixel((20, 40)), render.RED)  # 顶栏分隔线
        self.assertEqual(image.getpixel((10, render.GRID_TOP + 1)), render.RED)  # 卡片短线

    def test_value_headlines_share_the_same_visual_top(self) -> None:
        image = render.render_image(_sample_balances(), datetime(2026, 8, 4, 13, 48))
        boxes = render._grid_boxes(_sample_balances())

        def first_headline_ink_y(box: tuple[int, int, int, int]) -> int:
            x0, y0, x1, _ = box
            for y in range(y0 + 25, y0 + 60):
                if any(image.getpixel((x, y)) != render.BG for x in range(x0 + 8, x1 - 8)):
                    return y
            self.fail("主值区域没有渲染内容")

        self.assertEqual(first_headline_ink_y(boxes[2]), first_headline_ink_y(boxes[3]))

    def test_alert_extends_red_accent_across_card(self) -> None:
        image = render.render_image(_sample_balances(alert=True), datetime(2026, 8, 4, 13, 48))
        first_box = render._grid_boxes(_sample_balances(alert=True))[0]

        self.assertEqual(image.getpixel((first_box[2] - 1, first_box[1] + 1)), render.RED)


if __name__ == "__main__":
    unittest.main()
