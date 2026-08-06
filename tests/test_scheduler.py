import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scheduler" / "install.sh"
PLIST_TEMPLATE = ROOT / "scheduler" / "com.eink.printer.refresh.plist"


class SchedulerInstallerTests(unittest.TestCase):
    def test_no_load_install_generates_paths_for_current_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_home:
            env = os.environ.copy()
            env["HOME"] = temp_home
            fake_bin = Path(temp_home) / "bin"
            fake_bin.mkdir()
            fake_launchctl = fake_bin / "launchctl"
            fake_launchctl.write_text("#!/bin/sh\nexit 99\n")
            fake_launchctl.chmod(0o755)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT), "--no-load"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            installed = (
                Path(temp_home)
                / "Library"
                / "LaunchAgents"
                / "com.eink.printer.refresh.plist"
            )
            with installed.open("rb") as handle:
                plist = plistlib.load(handle)

        self.assertEqual(
            plist["ProgramArguments"],
            [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "refresh.py")],
        )
        self.assertEqual(plist["WorkingDirectory"], str(ROOT))
        self.assertEqual(plist["StandardOutPath"], str(ROOT / "logs" / "launchd.log"))
        self.assertNotIn("/Users/", PLIST_TEMPLATE.read_text())

    def test_calendar_interval_is_workday_window_only(self) -> None:
        """StartCalendarInterval 必须精确等于工作日 9:00–19:00 每半小时的组合。"""
        with PLIST_TEMPLATE.open("rb") as handle:
            plist = plistlib.load(handle)

        intervals = plist["StartCalendarInterval"]
        self.assertTrue(intervals, "StartCalendarInterval 不应为空")
        for entry in intervals:
            self.assertEqual(
                set(entry),
                {"Weekday", "Hour", "Minute"},
                f"每个调度条目只应含 Weekday/Hour/Minute: {entry}",
            )

        actual = {(e["Weekday"], e["Hour"], e["Minute"]) for e in intervals}
        expected = {
            (wd, hour, minute)
            for wd in (1, 2, 3, 4, 5)  # 周一至周五（0/7 为周日）
            for hour in range(9, 20)  # 9:00–19:00，含 19:00
            for minute in (0, 30)
        }
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
