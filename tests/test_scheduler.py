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


if __name__ == "__main__":
    unittest.main()
