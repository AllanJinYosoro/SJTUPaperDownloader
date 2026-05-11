import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright

from paperdownloader.captcha import JAccountCaptchaSolver
from paperdownloader.config import get_settings
from paperdownloader.workflow import ScholarDownloadWorkflow


TITLE = "Customer-Oriented Approaches to Identifying Product-Markets"


async def main() -> None:
    settings = get_settings()
    workflow = ScholarDownloadWorkflow(settings, JAccountCaptchaSolver(settings))
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            ".debug-profile",
            headless=True,
            accept_downloads=True,
            downloads_path=str(settings.download_dir),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(60_000)
        await workflow._open_sjtu_search(page, TITLE)
        await workflow._validate_primo_first_result(page, TITLE)
        await workflow._open_online_full_text(page)
        page = await workflow._open_ebsco_source(page)
        await workflow._handle_ebsco_auth(page)
        await page.wait_for_timeout(15_000)
        print("URL", page.url)
        rows = await page.evaluate(
            """() => [...document.querySelectorAll('button, a, [role=button]')]
                .map((el, i) => {
                    const r = el.getBoundingClientRect();
                    return {
                        i,
                        tag: el.tagName,
                        text: (el.textContent || '').trim(),
                        aria: el.getAttribute('aria-label') || '',
                        title: el.getAttribute('title') || '',
                        dataAuto: el.getAttribute('data-auto') || '',
                        cls: String(el.className || ''),
                        rect: { x: r.x, y: r.y, w: r.width, h: r.height },
                        visible: r.width > 0 && r.height > 0 &&
                            getComputedStyle(el).visibility !== 'hidden' &&
                            getComputedStyle(el).display !== 'none'
                    };
                })
                .filter(x => /download|下载|tool-button|bulk-download/i.test(
                    x.text + x.aria + x.title + x.dataAuto + x.cls
                ))
                .slice(0, 100)"""
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        target = await page.evaluate(
            """() => {
                const el = document.querySelector(
                    'button.tools-menu__tool--download__button, ' +
                    'button[data-auto="tool-button"][aria-label="下载"], ' +
                    '.tools-menu__tool--download button'
                );
                if (!el) {
                    return { ok: false };
                }
                const r = el.getBoundingClientRect();
                return {
                    ok: true,
                    text: el.textContent,
                    aria: el.getAttribute('aria-label'),
                    cls: String(el.className),
                    rect: { x: r.x, y: r.y, w: r.width, h: r.height }
                };
            }"""
        )
        print("TARGET", json.dumps(target, ensure_ascii=False))
        await page.locator(
            'button.tools-menu__tool--download__button, '
            '.tools-menu__tool--download button'
        ).first.click()
        await page.wait_for_timeout(3_000)
        dialog = await page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll('[role="dialog"], .eb-modal, [class*="modal" i], body')];
                return roots.map((root, rootIndex) => ({
                    rootIndex,
                    tag: root.tagName,
                    role: root.getAttribute('role') || '',
                    cls: String(root.className || '').slice(0, 160),
                    text: (root.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 500),
                    buttons: [...root.querySelectorAll('button, a, [role="button"]')]
                        .map((el, i) => {
                            const r = el.getBoundingClientRect();
                            return {
                                i,
                                tag: el.tagName,
                                text: (el.textContent || '').trim(),
                                aria: el.getAttribute('aria-label') || '',
                                title: el.getAttribute('title') || '',
                                dataAuto: el.getAttribute('data-auto') || '',
                                cls: String(el.className || '').slice(0, 160),
                                rect: { x: r.x, y: r.y, w: r.width, h: r.height },
                                visible: r.width > 0 && r.height > 0 &&
                                    getComputedStyle(el).visibility !== 'hidden' &&
                                    getComputedStyle(el).display !== 'none'
                            };
                        })
                        .filter(item => /download|下载|cancel|取消|bulk/i.test(
                            item.text + item.aria + item.title + item.dataAuto + item.cls
                        ))
                })).filter(item => /下载|Download|PDF|选择格式|bulk/i.test(
                    item.text + JSON.stringify(item.buttons)
                ));
            }"""
        )
        print("DIALOG", json.dumps(dialog, ensure_ascii=False, indent=2))
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
