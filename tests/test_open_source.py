import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OpenSourceReleaseContractTests(unittest.TestCase):
    def test_repository_metadata_is_ready_for_public_distribution(self) -> None:
        license_text = (ROOT / "LICENSE").read_text()
        readme = (ROOT / "README.md").read_text()
        scheduler_template = (
            ROOT / "scheduler" / "com.eink.printer.refresh.plist"
        ).read_text()
        vendor_readme = (ROOT / "vendor" / "README.md").read_text()

        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("GPL-3.0", readme)
        self.assertNotIn("尚未附带开源许可证", readme)
        self.assertNotIn("/Users/", scheduler_template)
        self.assertNotIn(".agents/skills", vendor_readme)
        self.assertNotIn("references/protocol.md", vendor_readme)


if __name__ == "__main__":
    unittest.main()
