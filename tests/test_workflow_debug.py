import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

from paperdownloader.captcha import JAccountCaptchaSolver
from paperdownloader.config import Settings
from paperdownloader.workflow import ScholarDownloadWorkflow, WorkflowError


class WorkflowDebugTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_redirect_without_body_is_not_a_failure(self):
        settings = Settings(_env_file=None)
        workflow = ScholarDownloadWorkflow(settings, JAccountCaptchaSolver(settings))
        redirect_page = Mock()
        redirect_page.locator.return_value.inner_text = AsyncMock(
            side_effect=PlaywrightTimeoutError("Document is navigating"),
        )
        self.assertFalse(await workflow._page_contains(redirect_page, ["jAccount"]))

    async def test_timeout_diagnostics_and_real_page_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                _env_file=None, browser_profile_dir=root / "profile",
                download_dir=root / "downloads", task_timeout_ms=500,
            )
            progress = AsyncMock()
            workflow = ScholarDownloadWorkflow(
                settings, JAccountCaptchaSolver(settings),
                progress=progress, debug_dir=root / "diagnostics",
            )

            async def open_page(page, title):
                await page.set_content('<h1>Test page</h1><input value="private">')

            async def stall(page, title):
                await asyncio.sleep(10)

            workflow._open_sjtu_search = open_page
            workflow._validate_primo_first_result = stall
            with self.assertRaisesRegex(WorkflowError, "matching paper title: TimeoutError"):
                await workflow.run("Test paper", headless=True)
            log = (root / "diagnostics" / "workflow.log").read_text(encoding="utf-8")
            self.assertIn("matching paper title", log)
            self.assertIn("TimeoutError", log)
            self.assertTrue((root / "diagnostics" / "failure.png").is_file())
            progress.assert_any_await("matching paper title")

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_content(
                    '<button onclick="this.textContent=&quot;Institution search opened&quot;">'
                    'Sign in through your institution</button>'
                    '<h3><a data-clk-atid="paper">A Model of Shoppertainment Live Streaming</a>'
                    '<span>CCF None<pre>Not Found</pre></span></h3>'
                )
                workflow._dismiss_cookie_banners = AsyncMock()
                await workflow._maybe_select_institution(page)
                self.assertIn("Institution search opened", await page.locator("body").inner_text())
                await page.set_content(
                    '<input id="fmo_input_type_field_id">'
                    '<ul><li role="option" onclick="document.body.dataset.selected=\'medical\'">'
                    '上海交通大学医学院 NO.280 CHONGQING SOUTH ROAD</li>'
                    '<li role="option" onclick="document.body.dataset.selected=\'sjtu\'">'
                    '上海交通大学 LIBRARY, 800,DONGCHUAN RD, SHANGHAI, CHINA</li></ul>'
                    '<h3><a data-clk-atid="paper">A Model of Shoppertainment Live Streaming</a>'
                    '<span>CCF None<pre>Not Found</pre></span></h3>'
                )
                selected = await workflow._search_and_select_institution(
                    page, page.locator("input"), "上海交通大学",
                )
                self.assertTrue(selected)
                self.assertEqual(await page.locator("body").get_attribute("data-selected"), "sjtu")
                source = (Path(__file__).resolve().parents[1] / "extension" / "content.js").read_text(encoding="utf-8")
                function = "function extractTitle" + source.split("function extractTitle", 1)[1].split("async function startDownload", 1)[0]
                title = await page.evaluate("() => {" + function + "; return extractTitle(document.querySelector('h3')); }")
                self.assertEqual(title, "A Model of Shoppertainment Live Streaming")
                await browser.close()


if __name__ == "__main__":
    unittest.main()
