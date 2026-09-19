import io
import json
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paperdownloader import native_host


class NativeHostTests(unittest.TestCase):
    def test_ensure_service_uses_existing_service(self) -> None:
        settings = SimpleNamespace(host="127.0.0.1", port=8765)
        status = native_host.ServiceStatus(
            backend_url="http://127.0.0.1:8765",
            health={"ok": True},
        )

        with (
            patch("paperdownloader.native_host.get_settings", return_value=settings),
            patch("paperdownloader.native_host.probe_service", return_value=status),
            patch("paperdownloader.native_host.launch_service_subprocess") as launch_mock,
        ):
            result = native_host.ensure_service(startup_timeout=0.1, poll_interval=0.01)

        self.assertTrue(result["ok"])
        self.assertFalse(result["serviceStarted"])
        self.assertEqual(result["backendUrl"], "http://127.0.0.1:8765")
        launch_mock.assert_not_called()

    def test_ensure_service_launches_and_waits(self) -> None:
        settings = SimpleNamespace(host="127.0.0.1", port=65534)
        responses = [
            None,
            native_host.ServiceStatus(
                backend_url="http://127.0.0.1:65534",
                health={"ok": True, "captcha_model_available": True},
            ),
        ]

        with (
            patch("paperdownloader.native_host.get_settings", return_value=settings),
            patch("paperdownloader.native_host.probe_service", side_effect=responses),
            patch("paperdownloader.native_host.launch_service_subprocess") as launch_mock,
        ):
            result = native_host.ensure_service(startup_timeout=0.5, poll_interval=0.01)

        self.assertTrue(result["serviceStarted"])
        self.assertEqual(result["health"]["ok"], True)
        launch_mock.assert_called_once()

    def test_ensure_service_times_out(self) -> None:
        settings = SimpleNamespace(host="127.0.0.1", port=8765)
        with (
            patch("paperdownloader.native_host.get_settings", return_value=settings),
            patch("paperdownloader.native_host.probe_service", return_value=None),
            patch("paperdownloader.native_host.launch_service_subprocess"),
        ):
            with self.assertRaises(native_host.NativeHostError):
                native_host.ensure_service(startup_timeout=0.03, poll_interval=0.01)

    def test_native_message_roundtrip(self) -> None:
        message = {"type": "ensureService"}
        payload = json.dumps(message).encode("utf-8")
        stdin = io.BytesIO(struct.pack("<I", len(payload)) + payload)
        stdout = io.BytesIO()

        with (
            patch.object(native_host.sys, "stdin", SimpleNamespace(buffer=stdin)),
            patch.object(native_host.sys, "stdout", SimpleNamespace(buffer=stdout)),
        ):
            received = native_host.read_native_message()
            native_host.write_native_message(received)

        stdout.seek(0)
        size = struct.unpack("<I", stdout.read(4))[0]
        echoed = json.loads(stdout.read(size).decode("utf-8"))
        self.assertEqual(echoed, message)
