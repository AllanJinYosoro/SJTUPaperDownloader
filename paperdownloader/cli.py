import argparse
import asyncio
import json
from pathlib import Path

from .config import get_settings


def main():
    parser = argparse.ArgumentParser(description="交大图书馆 PDF 下载")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="启动 Chrome 插件使用的本地服务")
    sub.add_parser("desktop", help="打开 Windows 批量下载窗口")
    one = sub.add_parser("download", help="下载一篇论文")
    one.add_argument("title")
    one.add_argument("--doi", default="")
    one.add_argument("--headless", action="store_true", default=None)
    batch = sub.add_parser("batch", help="下载 CSL JSON 中的论文")
    batch.add_argument("source", type=Path)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--headless", action="store_true", default=None)
    args = parser.parse_args()
    settings = get_settings()
    if getattr(args, "headless", None):
        settings = settings.model_copy(update={"headless": True})
    try:
        if args.command in (None, "serve"):
            import uvicorn
            from .service import api_token
            print(f"服务：http://127.0.0.1:{settings.port}\n插件配对码：{api_token()}", flush=True)
            uvicorn.run("paperdownloader.service:app", host="127.0.0.1", port=settings.port)
        elif args.command == "desktop":
            from .desktop import main as desktop
            desktop()
        elif args.command == "batch":
            from .batch import run_batch
            path = asyncio.run(run_batch(args.source, args.output, settings))
            report = json.loads(path.read_text(encoding="utf-8"))
            if any(item["status"] != "success" for item in report["items"]):
                raise SystemExit(1)
        else:
            from .workflow import ScholarDownloadWorkflow

            async def progress(step):
                print(step, flush=True)
            result = asyncio.run(ScholarDownloadWorkflow(settings, progress).run(
                args.title, doi=args.doi))
            print(result.model_dump_json(indent=2))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        parser.exit(1, f"错误：{exc}\n")


if __name__ == "__main__":
    main()
