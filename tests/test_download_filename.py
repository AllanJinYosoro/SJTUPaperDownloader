import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from paperdownloader.captcha import JAccountCaptchaSolver
from paperdownloader.config import Settings
from paperdownloader.workflow import ScholarDownloadWorkflow, WorkflowError


class DownloadFilenameTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_names_are_valid_bounded_and_preserve_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = Settings(_env_file=None, download_dir=root)
            workflow = ScholarDownloadWorkflow(settings, JAccountCaptchaSolver(settings))
            download = SimpleNamespace(
                suggested_filename="EBSCO-FullText.pdf",
                save_as=AsyncMock(side_effect=lambda path: Path(path).write_bytes(b"%PDF-test")),
            )
            for title, expected in [
                ("A Model of Shoppertainment Live Streaming", "A Model of Shoppertainment Live Streaming.pdf"),
                (' A:<B>/"C"\\D|E?F*G\x00. ', "ABCDEFG.pdf"),
                ("... ", "paper.pdf"),
                ("CON", "_CON.pdf"),
                ("LPT¹", "_LPT¹.pdf"),
                ("NUL.txt", "_NUL.txt.pdf"),
            ]:
                with self.subTest(title=title):
                    path = await workflow._resolve_download_path(download, title)
                    self.assertEqual(path.name, expected)
                    self.assertEqual(path.parent, root)
                    self.assertEqual(path.read_bytes(), b"%PDF-test")

            path = await workflow._resolve_download_path(b"%PDF-direct", "Direct")
            self.assertEqual(path.read_bytes(), b"%PDF-direct")

            (root / "Same title.pdf").write_bytes(b"keep existing")
            path = await workflow._resolve_download_path(download, "Same title")
            self.assertEqual(path.name, "Same title-1.pdf")
            self.assertEqual((root / "Same title.pdf").read_bytes(), b"keep existing")
            for target_dir in [root, root / ("folder" * 15) / ("subdir" * 12)]:
                target_dir.mkdir(parents=True, exist_ok=True)
                settings.download_dir = target_dir
                for _ in range(2):
                    path = await workflow._resolve_download_path(download, "论文😀" * 300)
                    self.assertEqual(path.parent, target_dir)
                    self.assertTrue(path.name.endswith(".pdf"))
                    self.assertLessEqual(len(str(path).encode("utf-16-le")) // 2, 259)
                    self.assertLessEqual(len(path.name.encode("utf-16-le")) // 2, 208)
                    self.assertNotIn("�", path.name)
                    self.assertEqual(path.read_bytes(), b"%PDF-test")
            settings.download_dir = root / ("x" * 250)
            with self.assertRaisesRegex(WorkflowError, "directory is too long"):
                await workflow._resolve_download_path(download, "Title")


if __name__ == "__main__":
    unittest.main()
