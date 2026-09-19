import asyncio
import json
import tempfile
import unittest
import importlib.util
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from paperdownloader.batch import clean_doi, read_csl, run_batch
from paperdownloader.config import Settings
from paperdownloader.models import DownloadRequest, WorkflowResult
from paperdownloader.textmatch import normalize_title
from paperdownloader.workflow import WorkflowError, is_pdf, profile_lock

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class CoreTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec("onnxruntime"), "optional captcha dependencies not installed")
    def test_captcha_binary_input_and_repeated_letters(self):
        import numpy as np
        from PIL import Image
        from paperdownloader.captcha import solve
        captured = []
        class FakeSession:
            def get_inputs(self):
                return [type("Input", (), {"name": "image", "shape": [1, 1, 2, 2]})()]
            def run(self, _, values):
                captured.append(values["image"])
                outputs = []
                for index in (0, 0, 1, 2, 26):
                    head = np.zeros((1, 27), dtype=np.float32)
                    head[0, index] = 1
                    outputs.append(head)
                return outputs
        image = Image.fromarray(np.array([[0, 155], [156, 255]], dtype=np.uint8))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        with patch("paperdownloader.captcha.session", return_value=FakeSession()):
            self.assertEqual(solve(buffer.getvalue(), Path("unused.onnx")), "aabc")
        self.assertEqual(captured[0].tolist(), [[[[0, 0], [1, 1]]]])

    def test_validation(self):
        self.assertEqual(clean_doi("https://doi.org/10.1234%2FABC"), "10.1234/abc")
        self.assertEqual(normalize_title("交通大学：研究"), "交通大学 研究")
        with self.assertRaises(ValueError):
            DownloadRequest(title="   ")
        with self.assertRaises(ValueError):
            clean_doi("not-a-doi")

    def test_file_and_profile_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "paper.pdf"
            path.write_bytes(b"<html>login</html>")
            self.assertFalse(is_pdf(path))
            path.write_bytes(b"%PDF-1.4\nincomplete")
            self.assertFalse(is_pdf(path))
            path.write_bytes(PDF)
            self.assertTrue(is_pdf(path))
            with profile_lock(root):
                with self.assertRaises(WorkflowError):
                    with profile_lock(root):
                        pass
            with profile_lock(root):
                pass

    async def test_batch_resume_failure_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.json"
            source.write_text(json.dumps([
                {"id": "http://zotero.org/users/1/items/ABCD1234", "type": "article-journal",
                 "title": "Paper One", "DOI": "10.1234/one"},
                {"id": "citation-key", "title": "Paper Two"}]), encoding="utf-8")
            output = root / "output"
            calls = []
            class Downloader:
                fail = True
                async def run(self, title, doi=""):
                    calls.append(title)
                    if title == "Paper Two" and self.fail:
                        raise RuntimeError("simulated publisher failure")
                    path = output / (("a" if title == "Paper One" else "b") * 32 + ".pdf")
                    path.write_bytes(PDF)
                    return WorkflowResult(path=path)
            fake = Downloader()
            target = await run_batch(source, output, Settings(), lambda _: None, downloader=fake)
            report = json.loads(target.read_text())
            self.assertEqual([r["status"] for r in report["items"]], ["success", "error"])
            fake.fail = False
            calls.clear()
            await run_batch(source, output, Settings(), lambda _: None, downloader=fake)
            self.assertEqual(calls, ["Paper Two"])
            (output / ("a" * 32 + ".pdf")).write_bytes(PDF + b"changed")
            calls.clear()
            await run_batch(source, output, Settings(), lambda _: None, downloader=fake)
            self.assertEqual(calls, ["Paper One"])
            before = target.read_bytes()
            source.write_text('[{"title":"Other Paper"}]')
            with self.assertRaises(ValueError):
                await run_batch(source, output, Settings(), lambda _: None, downloader=fake)
            self.assertEqual(target.read_bytes(), before)

    def test_invalid_csl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            for text in ('{}', '[]', '[{"title":null}]', '[{"title":"Paper", "DOI":4}]'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_csl(path)

    async def test_service_serializes_and_recovers_after_failure(self):
        from paperdownloader import service
        service.queue_lock = asyncio.Lock()
        active = 0
        maximum = 0
        class Fake:
            def __init__(self, *args): pass
            async def run(self, title, **kwargs):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1
                if title == "bad": raise RuntimeError("failed")
                return WorkflowResult(path=Path("ok.pdf"))
        requests = [DownloadRequest(title=title) for title in ("bad", "good")]
        tasks = [await service.store.create(r) for r in requests]
        with patch.object(service, "ScholarDownloadWorkflow", Fake):
            await asyncio.gather(*(service.run_task(t.task_id, r) for t, r in zip(tasks, requests)))
        self.assertEqual(maximum, 1)
        self.assertEqual((await service.store.get(tasks[0].task_id)).status, "error")
        self.assertEqual((await service.store.get(tasks[1].task_id)).status, "success")

    def test_api_auth_and_origin(self):
        from paperdownloader import service
        with patch.object(service, "api_token", return_value="test-secret"), TestClient(service.app) as client:
            self.assertEqual(client.get("/health").status_code, 401)
            self.assertEqual(client.get("/health", headers={"Authorization": "Bearer test-secret"}).status_code, 200)
            response = client.options("/download", headers={
                "Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"})
            self.assertEqual(response.status_code, 400)
            response = client.get("/health", headers={"Host": "attacker.example"})
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
