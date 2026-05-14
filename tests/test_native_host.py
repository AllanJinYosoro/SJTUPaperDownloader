import asyncio
import unittest
from unittest.mock import patch

from paperdownloader.config import Settings
from paperdownloader.native_host import NativeHost


class NativeHostTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.host = NativeHost(settings=Settings(_env_file=None))

    async def test_update_config_affects_health_snapshot(self) -> None:
        response = await self.host.handle_message(
            {
                "id": "1",
                "type": "updateConfig",
                "payload": {
                    "headless": False,
                    "downloadDir": "/tmp/papers",
                    "captchaModelPath": "/tmp/model.onnx",
                },
            }
        )
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["downloadDir"], "/tmp/papers")
        self.assertEqual(response["data"]["captchaModelPath"], "/tmp/model.onnx")

        health = await self.host.handle_message({"id": "2", "type": "health", "payload": {}})
        self.assertTrue(health["ok"])
        self.assertFalse(health["data"]["config"]["headless"])
        self.assertEqual(health["data"]["config"]["downloadDir"], "/tmp/papers")

    async def test_start_download_creates_task_without_running_browser(self) -> None:
        created_coroutines = []

        def capture_task(coroutine):
            created_coroutines.append(coroutine)
            return None

        with patch("paperdownloader.native_host.asyncio.create_task", side_effect=capture_task):
            response = await self.host.handle_message(
                {
                    "id": "3",
                    "type": "startDownload",
                    "payload": {"title": "A Valid Paper Title", "scholarUrl": "https://scholar.google.com"},
                }
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["status"], "queued")
        task_id = response["data"]["task_id"]
        self.assertTrue(task_id)

        task = await self.host.handle_message(
            {"id": "4", "type": "getTask", "payload": {"taskId": task_id}}
        )
        self.assertTrue(task["ok"])
        self.assertEqual(task["data"]["title"], "A Valid Paper Title")

        for coroutine in created_coroutines:
            coroutine.close()


if __name__ == "__main__":
    unittest.main()
