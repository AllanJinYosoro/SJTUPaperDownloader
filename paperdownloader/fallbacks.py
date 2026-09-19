"""Two ordered fallbacks, using normal public pages (no challenge bypass)."""
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .models import WorkflowResult
from .textmatch import clean_doi, title_similarity
from .workflow import SourceUnavailable, is_pdf


def public_url(url, hosts):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise SourceUnavailable("PDF 链接格式无效") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or port not in (None, 443)
            or not any(parsed.hostname == host or (parsed.hostname or "").endswith("." + host) for host in hosts)):
        raise SourceUnavailable("PDF 链接指向未支持的主机，已拒绝访问")
    return url


async def save_pdf(page, url, output, hosts, metadata):
    # Check every redirect too: a page-provided link must not reach local services.
    for _ in range(6):
        public_url(url, hosts)
        response = await page.context.request.get(url, max_redirects=0)
        try:
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get("location", ""))
                continue
            if not response.ok:
                raise SourceUnavailable(f"PDF 请求返回 HTTP {response.status}（可能需要人工验证）")
            length = response.headers.get("content-length", "0")
            if not length.isdigit():
                raise SourceUnavailable("PDF 长度响应头无效")
            if int(length) > 100 * 1024 * 1024:
                raise SourceUnavailable("PDF 超过当前 100 MB 上限")
            data = await response.body()
            if len(data) > 100 * 1024 * 1024 or not data.startswith(b"%PDF-"):
                raise SourceUnavailable("来源未返回 PDF，可能是验证页或无权限")
            path = output / f"{uuid4().hex}.pdf"
            temporary = path.with_suffix(".part")
            try:
                temporary.write_bytes(data)
                if not is_pdf(temporary):
                    raise SourceUnavailable("PDF 下载不完整")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            # Signed download URLs are transient secrets; never persist their query.
            parsed = urlsplit(url)
            metadata["final_url"] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            return WorkflowResult(path=path, metadata=metadata)
        finally:
            await response.dispose()
    raise SourceUnavailable("PDF 重定向次数过多")


async def resolve_doi(page, request, settings):
    if request.doi:
        return request.doi
    response = await page.context.request.get("https://api.crossref.org/works", params={
        "query.title": request.title, "rows": 5, "select": "DOI,title"})
    try:
        if not response.ok:
            raise SourceUnavailable("缺少 DOI，且 Crossref 标题查询不可用")
        try:
            data = await response.json()
        except ValueError:
            raise SourceUnavailable("Crossref 未返回有效的检索数据") from None
        matches = {clean_doi(item["DOI"]) for item in data.get("message", {}).get("items", [])
                   if item.get("DOI") and any(title_similarity(request.title, title) >= settings.title_match_threshold
                                              for title in item.get("title", []))}
    finally:
        await response.dispose()
    if len(matches) != 1:
        raise SourceUnavailable("缺少 DOI，标题查询不能唯一确定 DOI")
    return matches.pop()


async def wait_public_page(page, selector, settings, report):
    """Give normal rendering a chance; visible users may complete site challenges."""
    try:
        await page.locator(selector).first.wait_for(state="attached", timeout=8000)
    except PlaywrightTimeoutError:
        body = (await page.locator("body").inner_text()).lower()
        challenge = bool(await page.locator("altcha-widget, .g-recaptcha, .cf-turnstile").count()) or any(
            word in body for word in ("just a moment", "verify you are human", "are you a robot", "验证码", "验证", "captcha", "access denied", "content blocked"))
        if challenge and not settings.headless:
            await report("该来源需要人工验证，请在浏览器完成；不会自动绕过")
            await page.locator(selector).first.wait_for(state="attached", timeout=120_000)
        elif challenge:
            raise SourceUnavailable("来源要求人工验证；可在可见模式重试") from None
        else:
            raise SourceUnavailable("无匹配结果、无 PDF 或页面结构已改变") from None


async def download_scihub(page, request, output, settings, report):
    doi = await resolve_doi(page, request, settings)
    await report("Sci-Hub：按 DOI 查询")
    await page.goto("https://sci-hub.sg/" + quote(doi, safe="/"), wait_until="domcontentloaded")
    selector = '#pdf[src], embed[type="application/pdf"][src]'
    await wait_public_page(page, selector, settings, report)
    # Only follow the requested site's result, not an advertising/search redirect.
    public_url(page.url, ("sci-hub.sg",))
    body = await page.locator("body").inner_text()
    if doi.lower() not in unquote(page.url).lower() and doi.lower() not in body.lower():
        raise SourceUnavailable("Sci-Hub 结果不能核对目标 DOI")
    pdf = page.locator(selector).first
    url = urljoin(page.url, await pdf.get_attribute("src") or await pdf.get_attribute("href") or "")
    return await save_pdf(page, url, output, ("sci-hub.sg", "sci.bban.top"), {
        "source": "Sci-Hub", "resolved_doi": doi, "version": "unverified", "matched_title": request.title})


async def download_ssrn(page, request, output, settings, report):
    await report("SSRN：按标题查询")
    await page.goto("https://papers.ssrn.com/searchresults.cfm?term=" + quote('"' + request.title + '"'),
                    wait_until="domcontentloaded")
    selector = 'a[href*="papers.cfm?abstract_id="]'
    await wait_public_page(page, selector, settings, report)
    entries = await page.locator(selector).evaluate_all("nodes => nodes.map(n=>({title:n.textContent.trim(),href:n.href}))")
    matches = {entry["href"]: entry for entry in entries
               if title_similarity(request.title, entry["title"]) >= settings.title_match_threshold}
    if len(matches) != 1:
        raise SourceUnavailable("SSRN 未找到唯一的高度匹配标题")
    match = next(iter(matches.values()))
    public_url(match["href"], ("papers.ssrn.com",))
    await page.goto(match["href"], wait_until="domcontentloaded")
    await wait_public_page(page, 'meta[name="citation_title"]', settings, report)
    title = await page.locator('meta[name="citation_title"]').get_attribute("content") or ""
    if title_similarity(request.title, title) < settings.title_match_threshold:
        raise SourceUnavailable("SSRN 详情标题与目标不一致")
    pdf = page.locator('meta[name="citation_pdf_url"], a[href*="Delivery.cfm"], a[href*="delivery.cfm"]').first
    if not await pdf.count():
        raise SourceUnavailable("SSRN 条目未提供公开 PDF 链接")
    url = urljoin(page.url, await pdf.get_attribute("content") or await pdf.get_attribute("href") or "")
    return await save_pdf(page, url, output, ("ssrn.com",), {
        "source": "SSRN", "matched_title": title, "landing_url": match["href"],
        "version": "SSRN manuscript; may differ from published version"})
