import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paperdownloader.config import Settings
from paperdownloader.models import DownloadRequest


class ConfigTests(unittest.TestCase):
    def test_current_and_legacy_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {}, clear=True):
            env = Path(tmp) / ".env"
            for key in ("JACCOUNT_PASSWORD", "Jaccount_PWD"):
                env.write_text(f"JACCOUNT_USERNAME=test-user\n{key}=test-password\n")
                settings = Settings(_env_file=env)
                self.assertEqual(settings.jaccount_username, "test-user")
                self.assertEqual(settings.jaccount_password, "test-password")

    def test_optional_doi_validation(self):
        self.assertEqual(DownloadRequest(title="Test paper").doi, "")
        self.assertEqual(DownloadRequest(title="Test paper", doi="https://doi.org/10.1234/ABC").doi, "10.1234/abc")
        with self.assertRaises(ValueError):
            DownloadRequest(title="Test paper", doi="https://example.com/paper")
