import asyncio
import os
import re
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from .config import Settings
from .models import DownloadRequest, WorkflowResult
from .textmatch import normalize_title, title_similarity

PRIMO = "https://86sjt-primo.hosted.exlibrisgroup.com.cn/primo-explore/search"
SFX_HOST = "sfx-86sjtu.hosted.exlibrisgroup.com.cn"


class WorkflowError(RuntimeError):
    pass


class SourceUnavailable(WorkflowError):
    pass


@contextmanager
def profile_lock(directory: Path):
    """OS lock released on process exit, including crashes (Windows and Linux)."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "downloader.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WorkflowError("浏览器正被另一个下载进程使用，请等待它完成。") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                return False
            handle.seek(max(0, path.stat().st_size - 2048))
            return b"%%EOF" in handle.read()
    except OSError:
        return False


async def click_new_page(page: Page, locator) -> Page:
    """Click once, whether the link navigates in-place or opens a popup."""
    before = page.url
    popup = asyncio.create_task(page.wait_for_event("popup", timeout=45_000))
    navigation = asyncio.create_task(page.wait_for_url(
        lambda url: url != before, wait_until="domcontentloaded", timeout=45_000))
    try:
        await asyncio.sleep(0)
        await locator.click()
        done, _ = await asyncio.wait([popup, navigation], return_when=asyncio.FIRST_COMPLETED)
        if popup in done:
            result = popup.result()
        else:
            navigation.result()
            result = page
        await result.wait_for_load_state("domcontentloaded")
        return result
    finally:
        for task in (popup, navigation):
            if not task.done():
                task.cancel()
        await asyncio.gather(popup, navigation, return_exceptions=True)


class ScholarDownloadWorkflow:
    def __init__(self, settings: Settings, progress: Callable[[str], Awaitable[None]] | None = None):
        self.settings = settings
        self.progress = progress
        self.step = "starting"

    async def report(self, step: str):
        self.step = step
        if self.progress:
            await self.progress(step)

    async def run(self, title: str, *, doi: str = "", headless: bool | None = None) -> WorkflowResult:
        request = DownloadRequest(title=title, doi=doi)
        visible = not (self.settings.headless if headless is None else headless)
        profile = self.settings.browser_profile_dir.expanduser().resolve()
        output = self.settings.download_dir.expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        with profile_lock(profile):
            async with async_playwright() as pw:
                context = await pw.chromium.launch_persistent_context(
                    str(profile), headless=not visible, accept_downloads=True,
                )
                context.set_default_timeout(self.settings.navigation_timeout_ms)
                state_path = profile / "auth-state.json"
                if state_path.is_file():
                    try:
                        saved = json.loads(state_path.read_text(encoding="utf-8"))
                        await context.add_cookies(saved["cookies"])
                    except (ValueError, KeyError):
                        pass
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    return await self._run_sources(page, request, visible, output)
                except TimeoutError as exc:
                    raise WorkflowError(f"超时（{self.step}）。若正在登录，请以可见模式重试。") from exc
                finally:
                    try:
                        state = await context.storage_state()
                        temporary = state_path.with_suffix(".tmp")
                        with temporary.open("w", encoding="utf-8") as file:
                            temporary.chmod(0o600)
                            json.dump(state, file)
                        temporary.replace(state_path)
                    finally:
                        await context.close()

    async def _run_sources(self, page, request, visible, output):
        from .fallbacks import download_scihub, download_ssrn
        attempts = []
        for name, handler in (("SJTU", self._run), ("Sci-Hub", download_scihub), ("SSRN", download_ssrn)):
            await self.report(f"检索来源：{name}")
            context = None
            try:
                # Each source gets its own deadline; a stuck library must not
                # consume the time available to both fallback sources.
                async with asyncio.timeout(self.settings.task_timeout_ms / 1000):
                    if name == "SJTU":
                        result = await handler(page, request, visible, output)
                    else:
                        # Never share university cookies or saved credentials with fallbacks.
                        context = await page.context.browser.new_context(accept_downloads=True)
                        context.set_default_timeout(self.settings.navigation_timeout_ms)
                        external = await context.new_page()
                        result = await handler(external, request, output,
                                               self.settings.model_copy(update={"headless": not visible}), self.report)
                    result.metadata.update(provider=name, attempts=attempts + [{"source": name, "status": "success"}])
                    if request.doi:
                        result.metadata.setdefault("resolved_doi", request.doi)
                    return result
            except (WorkflowError, PlaywrightError, TimeoutError) as exc:
                reason = str(exc) if isinstance(exc, WorkflowError) else (
                    "来源超时" if isinstance(exc, (TimeoutError, PlaywrightTimeoutError)) else "浏览器访问失败")
                attempts.append({"source": name, "status": "unavailable", "reason": reason})
                await self.report(f"{name} 未能下载：{reason}")
            finally:
                if context:
                    await context.close()
        raise WorkflowError("所有来源均未能下载：" + "; ".join(f"{a['source']}: {a['reason']}" for a in attempts))

    async def _run(self, page: Page, request: DownloadRequest, visible: bool, output: Path):
        await self.report("检索交大图书馆")
        # ponytail: inspect first 10 results; add pagination if real misses require it.
        query = request.doi or request.title
        await page.goto(PRIMO + f"?query=any,contains,{quote(query, safe='')}"
                        "&tab=paper_tab&search_scope=paper_foreign&vid=fer&offset=0",
                        wait_until="domcontentloaded")
        rows = page.locator("prm-brief-result:visible")
        previous, stable = [], 0
        deadline = asyncio.get_running_loop().time() + self.settings.navigation_timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            records = await rows.evaluate_all("""nodes => nodes.map(node => ({
                title: node.querySelector('.item-title')?.textContent.trim(),
                href: node.querySelector('a[href*="fulldisplay"]')?.href
            })).filter(row => row.title && row.href)""")
            # Angular hydrates each result asynchronously. Read title + link together,
            # after the result set settles; don't mix two versions of the DOM.
            stable = stable + 1 if records and records == previous else 0
            previous = records
            if stable >= 2:
                break
            await asyncio.sleep(0.5)
        if not previous:
            raise WorkflowError("图书馆未返回有效检索结果，或检索服务未能加载。")
        records = list({record["href"]: record for record in previous}.values())[:10]
        candidates = [record["title"] for record in records]
        scores = [title_similarity(request.title, t) for t in candidates[:10]]
        index = max(range(len(scores)), key=scores.__getitem__)
        if scores[index] < self.settings.title_match_threshold:
            raise WorkflowError(f"未找到足够匹配的标题：{candidates[index]} ({scores[index]:.2f})")
        if sum(s >= self.settings.title_match_threshold for s in scores) > 1:
            matches = [t for t, s in zip(candidates, scores) if s >= self.settings.title_match_threshold]
            raise WorkflowError(f"有多个相近检索结果，请在图书馆确认版本：{matches}")
        await page.goto(records[index]["href"], wait_until="domcontentloaded")
        sfx = page.locator(f'a[href*="{SFX_HOST}"]').first
        await sfx.wait_for()
        sfx_url = await sfx.get_attribute("href") or ""
        identifiers = parse_qs(urlsplit(sfx_url).query).get("rft_id", [])
        dois = [value[9:].lower() for value in identifiers if value.lower().startswith("info:doi/")]
        if request.doi and dois and request.doi not in dois:
            raise WorkflowError(f"图书馆详情 DOI 与目标不一致：{dois}")
        if not request.doi and len(dois) == 1:
            request.doi = dois[0]
        page = await click_new_page(page, sfx)
        await self.report("选择 EBSCO 全文来源")
        rows = page.locator('tr[id^="tr_"]').filter(has_text=re.compile("EBSCOhost", re.I))
        try:
            await rows.first.wait_for(timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise WorkflowError("该文献未提供 EBSCOhost 全文来源；当前版本只支持此下载通道。") from exc
        source_page, source_url = page, page.url
        names = await rows.all_inner_texts()
        order = sorted(range(len(names)), key=lambda i: "Business Source Complete" not in names[i])
        errors = []
        for source_index in order:
            name = next((line.strip() for line in names[source_index].splitlines() if "EBSCOhost" in line), "EBSCOhost")
            await self.report(f"尝试来源：{name}")
            source = rows.nth(source_index).locator("a").filter(has_text=re.compile("Full text available via", re.I)).first
            article = await click_new_page(source_page, source)
            try:
                await self._authenticate(article, visible)
                article = await self._open_ebsco_pdf(article, request)
                result = await self._download_pdf(article, output)
                result.metadata.update(matched_title=candidates[index], title_score=scores[index], source=name)
                return result
            except SourceUnavailable as exc:
                errors.append(f"{name}: {exc}")
                await self.report(str(exc))
                if article is source_page:
                    await source_page.goto(source_url, wait_until="domcontentloaded")
                else:
                    await article.close()
        raise WorkflowError("所有 EBSCO 来源均不可用：" + "; ".join(errors))

    async def _open_ebsco_pdf(self, page: Page, request: DownloadRequest) -> Page:
        if "/viewer/pdf/" in page.url:
            return page
        await self.report("在 EBSCO 中校验目标论文")
        accept = page.get_by_role("button", name="Accept All", exact=True).first
        if await accept.is_visible():
            await accept.click()
        if "/search/results" in page.url:
            box = page.locator("#search-input")
            await box.wait_for()
            queries = ([f'"{request.doi}"'] if request.doi else []) + [f'"{normalize_title(request.title)}"']
            matched = None
            for query in queries:
                await box.fill(query)
                async with page.expect_response(
                        lambda response: urlsplit(response.url).path == "/api/search/v1/search") as response:
                    await box.press("Enter")
                result = await response.value
                await result.finished()
                if not result.ok:
                    raise SourceUnavailable(f"EBSCO 检索返回 HTTP {result.status}")
                await page.wait_for_function("""() =>
                    document.querySelector('[data-auto="result-item-title__link"]') ||
                    /No results for|未找到|没有找到/.test(document.querySelector('main')?.innerText || '')""")
                links = page.locator('[data-auto="result-item-title__link"]')
                entries = await links.evaluate_all("nodes => nodes.map(n => ({title:n.textContent.trim(),href:n.href}))")
                matches = [entry for entry in entries if title_similarity(request.title, entry["title"]) >= self.settings.title_match_threshold]
                if len(matches) == 1:
                    matched = matches[0]
                    break
                if len(matches) > 1:
                    raise SourceUnavailable("EBSCO 返回多个相近条目，不能唯一定位")
            if not matched:
                raise SourceUnavailable("该数据库未找到匹配的论文")
            await page.goto(matched["href"], wait_until="domcontentloaded")
        access = page.get_by_role("button", name=re.compile(r"Access options|访问选项", re.I)).first
        await access.wait_for()
        await access.click()
        pdf = page.locator('a[href*="/viewer/pdf/"], [role="menuitem"][data-auto="menuitem-PDF"]').first
        try:
            await pdf.wait_for(timeout=8000)
        except PlaywrightTimeoutError as exc:
            raise SourceUnavailable("该条目未提供可下载的 PDF 全文") from exc
        return await click_new_page(page, pdf)

    async def _download_pdf(self, page: Page, output: Path) -> WorkflowResult:
        await self.report("下载 PDF")
        # Subscribe before toolbar click: some versions download without a dialog.
        future = asyncio.get_running_loop().create_future()

        def on_download(download):
            if not future.done():
                future.set_result(download)

        page.on("download", on_download)
        try:
            toolbar = page.locator(
                'button.tools-menu__tool--download__button, '
                '.tools-menu__tool--download button, button:has(svg[data-icon="download"])'
            ).first
            await toolbar.click()
            final = page.locator(
                '[data-auto="bulk-download-modal-download-button"], '
                '[role="dialog"] button[title="Download"], '
                '[role="dialog"] button[title="下载"], '
                '[role="dialog"] button:has-text("Download"), '
                '[role="dialog"] button:has-text("下载")'
            ).last
            for _ in range(60):
                if future.done():
                    break
                if await final.is_visible():
                    await final.click()
                    break
                await asyncio.sleep(0.5)
            download = await asyncio.wait_for(future, timeout=60)
            path = output / f"{uuid4().hex}.pdf"
            temp = path.with_suffix(".part")
            try:
                await download.save_as(temp)
                if not is_pdf(temp):
                    raise WorkflowError("下载内容不是完整 PDF（可能为登录页或错误页面）")
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
            return WorkflowResult(path=path, metadata={
                "final_url": page.url, "suggested_filename": download.suggested_filename,
            })
        finally:
            page.remove_listener("download", on_download)
            if not future.done():
                future.cancel()

    async def _authenticate(self, page: Page, visible: bool):
        await self.report("等待机构认证；如出现 jAccount，请在浏览器完成登录")
        institution_chosen = False
        login_attempted = False
        last_host = None
        while True:
            host = urlsplit(page.url).hostname or ""
            if host and host != last_host:
                await self.report(f"机构认证：{host}（如出现登录页，请在浏览器完成登录）")
                last_host = host
            if host == "research.ebsco.com" and any(
                    part in page.url for part in ("/viewer/pdf/", "/search/results", "/search/details/")):
                return
            if host == "jaccount.sjtu.edu.cn":
                if not login_attempted:
                    await self._login_jaccount(page, visible)
                    login_attempted = True
                if not visible:
                    if urlsplit(page.url).hostname == host:
                        raise WorkflowError("jAccount 尚未登录，请配置账号和验证码组件或使用可见浏览器。")
                await asyncio.sleep(1)
                continue
            for label in ("Accept All", "Reject All", "接受全部", "全部接受"):
                cookie = page.get_by_role("button", name=label, exact=True).first
                if await cookie.is_visible():
                    await cookie.click()
                    break
            access = page.get_by_text(re.compile("通过您的机构访问|通过.*机构登录|(?:Access|Sign in) through your institution", re.I)).first
            if await access.is_visible():
                await access.click()
            box = page.locator('#fmo_input_type_field_id, input[aria-label*="institution" i], '
                               'input[aria-label*="organization" i]').first
            if not institution_chosen and await box.is_visible():
                await self.report("在 EBSCO 搜索上海交通大学")
                await box.fill("Shanghai Jiao Tong University")
                search = page.get_by_role("button", name="Search", exact=True).first
                if await search.is_visible():
                    await search.click()
                else:
                    await box.press("Enter")
                choice = page.get_by_text(re.compile(
                    r"^(上海交通大学|SHANGHAI JIAOTONG UNIV|Shanghai Jiao Tong University)$", re.I)).first
                await choice.click()
                await self.report("已选择上海交通大学，等待认证跳转")
                institution_chosen = True
            pdf_link = page.locator('a[href*="/viewer/pdf/"]').first
            if await pdf_link.is_visible():
                href = await pdf_link.get_attribute("href")
                await page.goto(urljoin(page.url, href), wait_until="domcontentloaded")
            await asyncio.sleep(1)

    async def _login_jaccount(self, page: Page, visible: bool):
        parsed = urlsplit(page.url)
        if parsed.scheme != "https" or parsed.hostname != "jaccount.sjtu.edu.cn":
            raise WorkflowError("拒绝向非官方 jAccount 页面填写账号密码")
        username = self.settings.jaccount_username
        password = self.settings.jaccount_password
        if not username or not password or not username.get_secret_value() or not password.get_secret_value():
            if not visible:
                raise WorkflowError("请在 .env 填写 JACCOUNT_USERNAME / JACCOUNT_PASSWORD，或使用可见浏览器登录")
            return
        account = page.locator('#input-login-user, input[name="user"]').first
        if not await account.is_visible():
            switch = page.get_by_text(re.compile(r"^(Login jAccount|账号登录|密码登录|jAccount登录)$", re.I)).first
            if await switch.is_visible():
                await switch.click()
        await account.wait_for(state="visible")
        # Never include Playwright fill exceptions: its call log can contain the value.
        try:
            await account.fill(username.get_secret_value())
            await page.locator('#input-login-pass, input[name="pass"]').first.fill(password.get_secret_value())
        except Exception:
            raise WorkflowError("无法填写 jAccount 表单；请在可见浏览器中完成登录") from None
        captcha = page.locator('#input-login-captcha').first
        for attempt in range(3):
            if await captcha.is_visible():
                model = self.settings.captcha_model_path.expanduser()
                if not model.is_file():
                    if not visible:
                        raise WorkflowError("已配置账号，但缺少验证码模型；运行 windows/setup-auto-login.cmd 或使用可见浏览器")
                    await self.report("账号密码已填写，请在浏览器填写验证码并登录")
                    return
                try:
                    from .captcha import solve
                    image = await page.locator('#captcha-img').screenshot()
                    prediction = await asyncio.to_thread(solve, image, model)
                    await captcha.fill(prediction)
                except Exception:
                    if not visible:
                        raise WorkflowError("验证码组件不可用，请运行 setup-auto-login.cmd 或使用可见浏览器") from None
                    await self.report("验证码识别失败，请在浏览器手动完成登录")
                    return
            await self.report(f"提交 jAccount 登录（{attempt + 1}/3）")
            await page.locator('#submit-password-button').click()
            try:
                await page.wait_for_url(lambda url: urlsplit(url).hostname != "jaccount.sjtu.edu.cn", timeout=20_000)
                return
            except PlaywrightTimeoutError:
                body = await page.locator("body").inner_text()
                if re.search(r"验证码.*(错误|不正确)|captcha.*(incorrect|invalid|wrong)", body, re.I):
                    # Only retry an explicitly incorrect CAPTCHA; never loop bad passwords.
                    await page.locator('#captcha-img').click()
                    await asyncio.sleep(0.5)
                    continue
                if not visible:
                    raise WorkflowError("jAccount 未完成登录：请检查账号密码，或在可见浏览器完成二次认证") from None
                await self.report("登录需要人工确认，请在浏览器处理错误或二次认证")
                return
        raise WorkflowError("验证码连续识别失败，请使用可见浏览器手动登录")
