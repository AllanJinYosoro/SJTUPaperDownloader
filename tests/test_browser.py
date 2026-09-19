"""Real Chromium, simulated publisher pages: no library login or network needed."""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.async_api import async_playwright

from paperdownloader.config import Settings
from paperdownloader.models import DownloadRequest
from paperdownloader.workflow import ScholarDownloadWorkflow, WorkflowError, is_pdf


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_openurl_sign_in_wording(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
                    <a href="https://research.ebsco.com/c/example/viewer/pdf/article">Sign in through your institution</a>
                '''))
                await page.goto("https://openurl.ebsco.com/linksvc/linking.aspx")
                flow = ScholarDownloadWorkflow(Settings(_env_file=None))
                await flow._authenticate(page, False)
                self.assertIn("/viewer/pdf/article", page.url)
            finally:
                await browser.close()

    async def test_ebsco_pdf_menu_without_link(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
                    <button onclick="document.querySelector('li').hidden=false">Access options for Example paper</button>
                    <ul><li role="menuitem" data-auto="menuitem-PDF" hidden
                      onclick="location.href='/c/example/viewer/pdf/article'">PDF</li></ul>
                '''))
                await page.goto("https://research.ebsco.com/c/example/search/details/article")
                flow = ScholarDownloadWorkflow(Settings(_env_file=None))
                result = await flow._open_ebsco_pdf(page, DownloadRequest(title="Example paper"))
                self.assertIn("/viewer/pdf/article", result.url)
            finally:
                await browser.close()

    async def test_credentials_only_fill_official_https_origin(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.fulfill(content_type="text/html", body='''
                    <input id="input-login-user"><input id="input-login-pass" type="password">
                    <button id="submit-password-button" onclick="location.href='https://research.ebsco.com/complete'">Login</button>
                '''))
                settings = Settings(_env_file=None, JACCOUNT_USERNAME="test-account", JACCOUNT_PASSWORD="test-password")
                flow = ScholarDownloadWorkflow(settings)
                await page.goto("https://jaccount.sjtu.edu.cn.attacker.example/login")
                with self.assertRaisesRegex(WorkflowError, "非官方"):
                    await flow._login_jaccount(page, False)
                self.assertEqual(await page.locator("#input-login-user").input_value(), "")
                await page.goto("https://jaccount.sjtu.edu.cn/login")
                await flow._login_jaccount(page, False)
                self.assertEqual(urlsplit(page.url).hostname, "research.ebsco.com")
                await page.goto("https://jaccount.sjtu.edu.cn/login")
                with patch("playwright.async_api.Locator.fill", side_effect=RuntimeError("test-password")):
                    with self.assertRaises(WorkflowError) as error:
                        await flow._login_jaccount(page, False)
                self.assertNotIn("test-password", str(error.exception))
            finally:
                await browser.close()

    async def test_complete_download_flow(self):
        for dialog, popup, invalid in [(True, True, False), (False, False, False), (True, True, True)]:
            with self.subTest(dialog=dialog, popup=popup, invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                calls = []
                title = "Customer-Oriented Approaches to Identifying Product-Markets"
                target = 'target="_blank"' if popup else ""
                payload = "<html>Login required</html>" if invalid else "%PDF-1.4\ntrailer\n<<>>\n%%EOF\n"
                download_js = "const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([" + json.dumps(payload) + "]));a.download='../paper.pdf';a.click();"
                class FixtureWorkflow(ScholarDownloadWorkflow):
                    async def _run_sources(self, *args):
                        return await self._run(*args)

                    async def _run(self, page, *args):
                        async def route_handler(route):
                            url = urlsplit(route.request.url)
                            calls.append(url.path)
                            if url.path.endswith("/search"):
                                body = ('<prm-brief-result><div class="item-title">Wrong paper</div><a href="/wrong">wrong</a></prm-brief-result>'
                                        '<prm-brief-result><div class="item-title">' + title + '</div><a href="/fulldisplay">Details</a></prm-brief-result>')
                            elif url.path == "/fulldisplay":
                                body = f'<a {target} href="https://sfx-86sjtu.hosted.exlibrisgroup.com.cn/86sjtu">Online full text</a>'
                            elif url.path == "/86sjtu":
                                link = f'{target} href="https://research.ebsco.com/c/example/viewer/pdf/article"'
                                if popup and not invalid:
                                    link = 'href="javascript:void(0)" onclick="setTimeout(() => window.open(\'https://research.ebsco.com/c/example/viewer/pdf/article\'), 5500)"'
                                body = f'<table><tr id="tr_1"><td>EBSCOhost</td><td><a {link}>Full text available via</a></td></tr></table>'
                            else:
                                action = "document.querySelector('[role=dialog]').hidden=false" if dialog else download_js
                                body = ('<button class="tools-menu__tool--download__button">Download</button>'
                                        '<div role="dialog" hidden><button data-auto="bulk-download-modal-download-button">Download</button></div>'
                                        '<script>document.querySelector("button").onclick=()=>{' + action + '};'
                                        'document.querySelector("[data-auto]").onclick=()=>{' + download_js + '};</script>')
                            await route.fulfill(content_type="text/html", body=body)
                        await page.context.route("**/*", route_handler)
                        return await super()._run(page, *args)
                settings = Settings(headless=True, browser_profile_dir=root / "profile",
                                    download_dir=root / "pdfs", task_timeout_ms=60_000)
                flow = FixtureWorkflow(settings)
                if invalid:
                    with self.assertRaisesRegex(WorkflowError, "不是完整 PDF"):
                        await flow.run(title)
                    self.assertEqual(list((root / "pdfs").iterdir()), [])
                else:
                    result = await flow.run(title)
                    self.assertTrue(is_pdf(result.path))
                    self.assertEqual(result.path.parent, root / "pdfs")
                    self.assertEqual(calls.count("/86sjtu"), 1)
                    self.assertEqual(calls.count("/c/example/viewer/pdf/article"), 1)
                    self.assertEqual(result.metadata["matched_title"], title)

    async def test_scholar_button_preserves_title_and_recovers_from_network_error(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content('<div class="gs_r"><h3 class="gs_rt"><span class="gs_ct1">[PDF]</span> A [special] Paper</h3></div>')
                await page.evaluate("""() => {window.chrome={runtime:{sendMessage: async message => {
                    window.sent=message; throw new Error('Service unavailable');
                }}}}""")
                await page.add_script_tag(path="extension/content.js")
                await page.get_by_role("button", name="SJTU PDF").click()
                await page.wait_for_function("document.querySelector('.sjtu-paper-download-status').textContent.includes('Service unavailable')")
                self.assertEqual(await page.evaluate("window.sent.payload.title"), "A [special] Paper")
                self.assertTrue(await page.get_by_role("button", name="SJTU PDF").is_enabled())
                self.assertEqual(await page.get_by_role("button", name="SJTU PDF").count(), 1)
            finally:
                await browser.close()


if __name__ == "__main__":
    unittest.main()
