import asyncio
import hashlib
import html
import json
import re
from pathlib import Path

from .config import Settings
from .models import DownloadRequest
from .textmatch import clean_doi
from .workflow import ScholarDownloadWorkflow, is_pdf, profile_lock


def read_csl(path: Path) -> tuple[str, list[dict]]:
    raw = path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    records = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(records, list) or not records:
        raise ValueError("请选择 Zotero 导出的 CSL JSON（非空条目数组）")
    items = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict) or not isinstance(record.get("title"), str):
            raise ValueError(f"第 {index} 条缺少标题")
        title = html.unescape(re.sub(r"<[^>]+>", "", record["title"]))
        doi = record.get("DOI", "")
        if not isinstance(doi, str):
            raise ValueError(f"第 {index} 条 DOI 不是字符串")
        request = DownloadRequest(title=title, doi=doi)
        items.append({"source": record, "title": request.title, "doi": request.doi,
                      "status": "pending"})
    return source_hash, items


def write_manifest(path: Path, manifest: dict):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def file_hash(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def valid_cached(root: Path, item: dict) -> bool:
    name = item.get("pdf", "")
    if not isinstance(name, str) or not re.fullmatch(r"[a-f0-9]{32}\.pdf", name):
        return False
    path = root / name
    return (item.get("status") == "success" and is_pdf(path)
            and file_hash(path) == item.get("sha256"))


async def run_batch(source: Path, output: Path, settings: Settings, log=print,
                    stop=None, downloader=None) -> Path:
    source_hash, records = read_csl(source)
    output = output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / "sjtu-attachments.json"
    with profile_lock(output):
        manifest = {"format": "sjtu-attachments", "version": 1,
                    "source_sha256": source_hash, "items": records}
        if target.exists():
            saved = json.loads(target.read_text(encoding="utf-8"))
            if (saved.get("format") != manifest["format"] or saved.get("version") != 1
                    or saved.get("source_sha256") != source_hash):
                raise ValueError("输出目录已有其他批次，请选择新目录；原文件没有被覆盖。")
            if not isinstance(saved.get("items"), list) or len(saved["items"]) != len(records):
                raise ValueError("已有批次清单损坏")
            for original, cached in zip(records, saved["items"]):
                if not isinstance(cached, dict) or cached.get("source") != original["source"]:
                    raise ValueError("已有批次条目与输入不一致")
                for field in ("pdf", "sha256", "status", "error", "metadata"):
                    if field in cached:
                        original[field] = cached[field]
        write_manifest(target, manifest)

        async def progress(message):
            log(message)

        workflow = downloader or ScholarDownloadWorkflow(
            settings.model_copy(update={"download_dir": output}), progress)
        for index, item in enumerate(records, 1):
            if stop and stop.is_set():
                log("已停止；重新选择同一输入和输出目录可继续。")
                break
            if valid_cached(output, item):
                log(f"[{index}/{len(records)}] 已存在：{item['title']}")
                continue
            log(f"[{index}/{len(records)}] {item['title']}")
            try:
                result = await workflow.run(item["title"], doi=item["doi"])
                if result.path.parent.resolve() != output or not is_pdf(result.path):
                    raise ValueError("下载器未返回批次目录中的有效 PDF")
                item.update(status="success", pdf=result.path.name,
                            sha256=file_hash(result.path), metadata=result.metadata)
                item.pop("error", None)
            except Exception as exc:
                item.update(status="error", error=str(exc))
                item.pop("pdf", None)
                item.pop("sha256", None)
                item.pop("metadata", None)
                log(f"失败：{exc}")
            write_manifest(target, manifest)
            if index < len(records) and not downloader:
                await asyncio.sleep(2)
        log(f"附件清单：{target}")
        return target
