import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright

from paperdownloader.config import Settings
from paperdownloader.fallbacks import download_scihub, download_ssrn, public_url, save_pdf
from paperdownloader.models import DownloadRequest, WorkflowResult
from paperdownloader.workflow import ScholarDownloadWorkflow, SourceUnavailable, is_pdf


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_order_short_circuit_and_timeout(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.context.add_cookies([{"name": "secret", "value": "test", "url": "https://jaccount.sjtu.edu.cn"}])
                request = DownloadRequest(title="Example paper", doi="10.1234/example")
                result = WorkflowResult(path=Path("example.pdf"))
                flow = ScholarDownloadWorkflow(Settings(_env_file=None))
                for success in ("SJTU", "Sci-Hub", "SSRN"):
                    calls = []

                    def handler(name):
                        async def run(external, *args):
                            calls.append(name)
                            if name != "SJTU":
                                self.assertEqual(await external.context.cookies(), [])
                            if name == success:
                                return result.model_copy(deep=True)
                            if name == "SJTU":
                                raise TimeoutError()
                            raise SourceUnavailable("not found")
                        return run

                    with patch.object(flow, "_run", side_effect=handler("SJTU")), \
                         patch("paperdownloader.fallbacks.download_scihub", side_effect=handler("Sci-Hub")), \
                         patch("paperdownloader.fallbacks.download_ssrn", side_effect=handler("SSRN")):
                        actual = await flow._run_sources(page, request, False, Path("."))
                    self.assertEqual(calls, ["SJTU", "Sci-Hub", "SSRN"][:["SJTU", "Sci-Hub", "SSRN"].index(success) + 1])
                    self.assertEqual(actual.metadata["provider"], success)
                    self.assertEqual(len(actual.metadata["attempts"]), len(calls))
            finally:
                await browser.close()

    async def test_external_pages_and_pdf_validation(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context()
                # APIRequestContext does not use browser routes; stub its HTTP responses.
                response = AsyncMock()
                response.status = 200
                response.ok = True
                response.headers = {}
                response.body.return_value = b"%PDF-1.4\n%%EOF\n"
                page = await context.new_page()
                title = "Example Paper Title"
                request = DownloadRequest(title=title, doi="10.1234/example")

                async def route(route):
                    url = route.request.url
                    if "sci-hub.sg" in url:
                        body = '<embed id="pdf" src="https://sci-hub.sg/paper.pdf">'
                    elif "searchresults.cfm" in url:
                        body = f'<a href="https://papers.ssrn.com/sol3/papers.cfm?abstract_id=123">{title}</a>'
                    else:
                        body = f'<meta name="citation_title" content="{title}"><meta name="citation_pdf_url" content="https://download.ssrn.com/paper.pdf">'
                    await route.fulfill(content_type="text/html", body=body)

                await page.route("**/*", route)
                settings = Settings(_env_file=None, headless=True)
                with tempfile.TemporaryDirectory() as tmp, patch("playwright.async_api.APIRequestContext.get", return_value=response):
                    output = Path(tmp)
                    for download in (download_scihub, download_ssrn):
                        result = await download(page, request, output, settings, AsyncMock())
                        self.assertTrue(is_pdf(result.path))
                    response.body.return_value = b"<html>Login required</html>"
                    with self.assertRaisesRegex(SourceUnavailable, "未返回 PDF"):
                        await save_pdf(page, "https://download.ssrn.com/error", output, ("ssrn.com",), {})
                    response.status = 302
                    response.headers = {"location": "http://127.0.0.1:8765/private"}
                    with self.assertRaisesRegex(SourceUnavailable, "未支持的主机"):
                        await save_pdf(page, "https://download.ssrn.com/redirect", output, ("ssrn.com",), {})
                    self.assertEqual(len(list(output.glob("*.pdf"))), 2)
            finally:
                await browser.close()

    def test_reject_untrusted_pdf_hosts(self):
        for url in ("http://ssrn.com/a", "https://ssrn.com.evil.test/a", "https://user@ssrn.com/a", "https://127.0.0.1/a"):
            with self.assertRaises(SourceUnavailable):
                public_url(url, ("ssrn.com",))


if __name__ == "__main__":
    unittest.main()
