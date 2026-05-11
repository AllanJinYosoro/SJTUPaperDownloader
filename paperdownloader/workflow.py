import asyncio
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import (
    BrowserContext,
    Download,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .captcha import CaptchaSolverError, JAccountCaptchaSolver
from .config import Settings
from .models import WorkflowResult
from .textmatch import title_similarity


class WorkflowError(RuntimeError):
    pass


class ScholarDownloadWorkflow:
    def __init__(self, settings: Settings, captcha_solver: JAccountCaptchaSolver) -> None:
        self.settings = settings
        self.captcha_solver = captcha_solver

    async def run(self, title: str, *, headless: bool | None = None) -> WorkflowResult:
        profile_dir = Path(self.settings.browser_profile_dir)
        download_dir = Path(self.settings.download_dir).expanduser()
        profile_dir.mkdir(parents=True, exist_ok=True)
        download_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.settings.headless if headless is None else headless,
                accept_downloads=True,
                downloads_path=str(download_dir),
                slow_mo=self.settings.slow_mo_ms,
            )
            context.set_default_timeout(self.settings.navigation_timeout_ms)
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                return await asyncio.wait_for(
                    self._run_in_context(context, page, title),
                    timeout=self.settings.task_timeout_ms / 1000,
                )
            finally:
                await context.close()

    async def _run_in_context(
        self,
        context: BrowserContext,
        page: Page,
        title: str,
    ) -> WorkflowResult:
        await self._open_sjtu_search(page, title)
        await self._validate_primo_first_result(page, title)
        await self._open_online_full_text(page)
        page = await self._open_ebsco_source(page)
        await self._handle_ebsco_auth(page)
        download = await self._download_pdf(page)
        path = await self._resolve_download_path(download)
        return WorkflowResult(
            path=path,
            metadata={
                "final_url": page.url,
                "suggested_filename": download.suggested_filename,
            },
        )

    async def _open_sjtu_search(self, page: Page, title: str) -> None:
        direct = (
            "https://86sjt-primo.hosted.exlibrisgroup.com.cn/primo-explore/search"
            f"?query=any,contains,{quote(title)}"
            "&tab=paper_tab&search_scope=paper_foreign&vid=fer&offset=0"
        )
        await page.goto(direct, wait_until="domcontentloaded")

    async def _validate_primo_first_result(self, page: Page, title: str) -> None:
        await page.wait_for_load_state("networkidle")
        result_title = await self._extract_first_result_title(page)
        if not result_title:
            raise WorkflowError("SJTU Primo returned no searchable result title.")
        score = title_similarity(title, result_title)
        if score < self.settings.title_match_threshold:
            raise WorkflowError(
                f"First result title does not match target. Expected '{title}', "
                f"got '{result_title}' (score={score:.2f})."
            )

    async def _extract_first_result_title(self, page: Page) -> str | None:
        selectors = [
            "prm-brief-result .item-title",
            ".item-title",
            "h3",
            "a[title]",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                text = (await locator.inner_text(timeout=4_000)).strip()
            except PlaywrightTimeoutError:
                continue
            if text:
                return text
        return await page.evaluate(
            """() => {
                const candidates = [...document.querySelectorAll('a, h3, .item-title')];
                const el = candidates.find(node => node.textContent.trim().length > 8);
                return el ? el.textContent.trim() : null;
            }"""
        )

    async def _open_online_full_text(self, page: Page) -> None:
        if "/search?" in page.url:
            full_display_url = await page.evaluate(
                """() => {
                    const result = document.querySelector('prm-brief-result');
                    const links = result ? [...result.querySelectorAll('a[href*="fulldisplay"]')] : [];
                    const titleLink = links.find(a => (a.textContent || '').trim().length > 5);
                    return titleLink ? titleLink.href : (links[0] ? links[0].href : null);
                }"""
            )
            if not full_display_url:
                raise WorkflowError("Could not find the first Primo full-display link.")
            await page.goto(full_display_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle")
            try:
                await page.locator(
                    'a[href*="sfx-86sjtu.hosted.exlibrisgroup.com.cn"]'
                ).first.wait_for(timeout=20_000)
            except PlaywrightTimeoutError:
                pass

        sfx_url = await page.evaluate(
            """() => {
                const links = [...document.querySelectorAll('a[href*="sfx-86sjtu.hosted.exlibrisgroup.com.cn"]')];
                const fullText = links.find(a => /在线资源|更多选项|full/i.test(a.textContent || a.getAttribute('aria-label') || ''));
                return fullText ? fullText.href : (links[0] ? links[0].href : null);
            }"""
        )
        if sfx_url:
            await page.goto(sfx_url, wait_until="domcontentloaded")
            return

        if await self._try_click_text(page, ["在线全文", "Online Access", "Full text available"]):
            await page.wait_for_load_state("domcontentloaded")
            return
        raise WorkflowError("Could not find the Primo full-text service link.")

    async def _open_ebsco_source(self, page: Page) -> Page:
        await page.wait_for_load_state("networkidle")
        row_id = await page.evaluate(
            """() => {
                const row = [...document.querySelectorAll('tr[id^="tr_"]')]
                    .find(tr => /EBSCOhost/i.test(tr.textContent || ''));
                return row ? row.id : null;
            }"""
        )
        if not row_id:
            raise WorkflowError("No EBSCOhost full-text source was available.")
        link = page.locator(f"tr#{row_id} a").filter(has_text="Full text available via").first

        try:
            async with page.context.expect_page(timeout=15_000) as popup_info:
                await link.click(timeout=10_000)
            ebsco_page = await popup_info.value
            await ebsco_page.wait_for_load_state("domcontentloaded")
            return ebsco_page
        except PlaywrightTimeoutError:
            await link.click(timeout=10_000)
            await page.wait_for_load_state("domcontentloaded")
            return page

    async def _handle_ebsco_auth(self, page: Page) -> None:
        for _ in range(8):
            if "research.ebsco.com" in page.url and "/viewer/pdf/" in page.url:
                return
            await self._maybe_select_institution(page)
            await self._maybe_login_jaccount(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except PlaywrightTimeoutError:
                pass
            await page.wait_for_timeout(1_000)

    async def _maybe_select_institution(self, page: Page) -> None:
        await self._dismiss_cookie_banners(page)
        if "research.ebsco.com" in page.url and "/viewer/pdf/" in page.url:
            return
        if await self._try_click_text(page, ["通过您的机构访问", "Access through your institution"]):
            await page.wait_for_load_state("domcontentloaded")
        if not await self._page_contains(page, ["Search by name", "institution", "机构"]):
            return
        box = await self._optional_first_visible(
            page.locator(
                '#fmo_input_type_field_id, input[aria-label*="organization" i], '
                'input[aria-label*="institution" i], input[type="search"], input[type="text"]'
            )
        )
        if box is None:
            return
        if await self._search_and_select_institution(page, box, "上海交通大学"):
            return
        if await self._search_and_select_institution(page, box, "Shanghai Jiao Tong University"):
            return

    async def _search_and_select_institution(
        self,
        page: Page,
        box: Locator,
        query: str,
    ) -> bool:
        await box.fill(query)
        await page.wait_for_timeout(800)
        search = page.locator('button[aria-label="Search"], button[aria-label*="Search" i]').first
        try:
            await search.click(timeout=5_000)
        except Exception:
            await box.press("Enter")
        await page.wait_for_timeout(4_000)

        for text in ["上海交通大学", "SHANGHAI JIAOTONG UNIV", "Shanghai Jiao Tong University"]:
            try:
                await page.get_by_text(text, exact=True).click(timeout=5_000)
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(4_000)
                return True
            except Exception:
                continue
        return False

    async def _maybe_login_jaccount(self, page: Page) -> None:
        if not await self._page_contains(page, ["jAccount", "JAccount", "验证码", "captcha"]):
            return
        if not self.settings.jaccount_username or not self.settings.jaccount_password:
            raise WorkflowError("JAccount credentials are missing in .env.")

        username = await self._optional_first_visible(
            page.locator(
                'input[name*="user" i], input[id*="user" i], '
                'input[name*="account" i], input[type="text"]'
            )
        )
        password = await self._optional_first_visible(page.locator('input[type="password"]'))
        if username is not None:
            await username.fill(self.settings.jaccount_username)
        if password is not None:
            await password.fill(self.settings.jaccount_password)

        for _ in range(self.settings.captcha_max_retries):
            captcha_input = await self._optional_first_visible(
                page.locator(
                    'input[name*="captcha" i], input[id*="captcha" i], '
                    'input[placeholder*="验证码"], input[type="text"]'
                )
            )
            captcha_image = await self._optional_first_visible(
                page.locator('img[src*="captcha" i], img[id*="captcha" i], img[alt*="验证码"]')
            )
            if captcha_input is not None and captcha_image is not None:
                try:
                    prediction = self.captcha_solver.solve(await captcha_image.screenshot())
                    await captcha_input.fill(prediction)
                except CaptchaSolverError as exc:
                    raise WorkflowError(str(exc)) from exc
            if await self._try_click_text(page, ["登录", "Login", "Sign in"]):
                await page.wait_for_timeout(2_000)
                if not await self._page_contains(page, ["验证码错误", "captcha incorrect"]):
                    return
            elif password is not None:
                await password.press("Enter")
                await page.wait_for_timeout(2_000)
                return
            if captcha_image is not None:
                await captcha_image.click()
                await page.wait_for_timeout(500)
        raise WorkflowError("JAccount login failed after captcha retries.")

    async def _download_pdf(self, page: Page) -> Download:
        await self._dismiss_cookie_banners(page)
        for _ in range(20):
            if "research.ebsco.com" in page.url:
                break
            await page.wait_for_timeout(1_000)

        toolbar_download = page.locator('button[aria-label="Download"]').first
        await toolbar_download.wait_for(timeout=30_000)
        await toolbar_download.click()

        modal_download = page.locator(
            'button[title="Download"], '
            'button.nuc-bulk-download-modal-footer__button:has-text("Download"), '
            'button:has-text("下载")'
        ).last
        await modal_download.wait_for(timeout=15_000)
        async with page.expect_download(timeout=45_000) as download_info:
            await modal_download.click()
        return await download_info.value

    async def _dismiss_cookie_banners(self, page: Page) -> None:
        for text in ["Accept All", "Reject All", "接受全部", "全部接受"]:
            try:
                await page.get_by_text(text, exact=False).first.click(timeout=2_000)
                await page.wait_for_timeout(500)
                return
            except Exception:
                continue

    async def _resolve_download_path(self, download: Download) -> Path | None:
        target = Path(self.settings.download_dir).expanduser() / download.suggested_filename
        target = self._deduplicate_path(target)
        await download.save_as(str(target))
        return target

    def _deduplicate_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for index in range(1, 1000):
            candidate = path.with_name(f"{stem}-{index}{suffix}")
            if not candidate.exists():
                return candidate
        raise WorkflowError(f"Could not choose a unique download path for {path}.")

    async def _try_click_text(self, page: Page, texts: list[str]) -> bool:
        for text in texts:
            locator = page.get_by_text(text, exact=False).first
            try:
                await locator.click(timeout=3_000)
                return True
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
        return False

    async def _page_contains(self, page: Page, texts: list[str]) -> bool:
        body = await page.locator("body").inner_text(timeout=5_000)
        lowered = body.lower()
        return any(text.lower() in lowered for text in texts)

    async def _first_visible(self, locator: Locator) -> Locator:
        found = await self._optional_first_visible(locator)
        if found is None:
            raise WorkflowError("No visible matching element found.")
        return found

    async def _optional_first_visible(self, locator: Locator) -> Locator | None:
        count = await locator.count()
        for index in range(min(count, 12)):
            item = locator.nth(index)
            try:
                if await item.is_visible(timeout=1_000):
                    return item
            except Exception:
                continue
        return None
