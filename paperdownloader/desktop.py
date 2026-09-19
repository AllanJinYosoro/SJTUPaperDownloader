import asyncio
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .batch import run_batch
from .config import get_settings


def main():
    root = tk.Tk()
    root.title("交大论文批量下载")
    root.geometry("800x540")
    source = tk.StringVar()
    output = tk.StringVar(value=str(Path("downloads/batch").resolve()))
    headless = tk.BooleanVar(value=False)
    messages = queue.Queue()
    stop = threading.Event()
    running = False
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    frame.rowconfigure(5, weight=1)

    def choose_source():
        selected = filedialog.askopenfilename(filetypes=[("Zotero CSL JSON", "*.json")])
        if selected:
            source.set(selected)

    def choose_output():
        selected = filedialog.askdirectory()
        if selected:
            output.set(selected)

    for row, label, value, command in [(0, "CSL JSON", source, choose_source),
                                       (1, "输出目录", output, choose_output)]:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=value).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="选择…", command=command).grid(row=row, column=2)
    ttk.Checkbutton(frame, text="无头运行（仅在已登录后使用）", variable=headless).grid(
        row=2, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, text="首次下载请在弹出的浏览器完成 jAccount 登录。停止会等待当前论文结束。",
              wraplength=720).grid(row=3, column=0, columnspan=3, sticky="w", pady=10)
    controls = ttk.Frame(frame)
    controls.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
    log = ScrolledText(frame, state="disabled", wrap="word")
    log.grid(row=5, column=0, columnspan=3, sticky="nsew")

    def start():
        nonlocal running
        if not Path(source.get()).is_file() or not output.get().strip():
            messagebox.showerror("输入不完整", "请选择 CSL JSON 文件和输出目录")
            return
        settings = get_settings().model_copy(update={"headless": headless.get()})
        input_path, output_path = Path(source.get()), Path(output.get())
        stop.clear()
        running = True
        start_button.config(state="disabled")
        stop_button.config(state="normal")

        def work():
            try:
                path = asyncio.run(run_batch(input_path, output_path, settings,
                                             lambda s: messages.put(("log", s)), stop))
                records = json.loads(path.read_text(encoding="utf-8"))["items"]
                count = sum(item["status"] == "success" for item in records)
                messages.put(("log", f"已完成 {count}/{len(records)} 篇。请在 Zotero 工具菜单导入附件清单。"))
            except Exception as exc:
                messages.put(("log", f"错误：{exc}"))
            finally:
                messages.put(("done", ""))
        threading.Thread(target=work, daemon=True).start()

    start_button = ttk.Button(controls, text="开始 / 继续下载", command=start)
    start_button.pack(side="left", padx=(0, 8))
    stop_button = ttk.Button(controls, text="当前篇结束后停止", command=stop.set, state="disabled")
    stop_button.pack(side="left")

    def poll():
        nonlocal running
        while True:
            try:
                kind, text = messages.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                running = False
                start_button.config(state="normal")
                stop_button.config(state="disabled")
            else:
                log.config(state="normal")
                log.insert("end", text + "\n")
                log.see("end")
                log.config(state="disabled")
        root.after(100, poll)

    def close():
        if running:
            stop.set()
            messagebox.showinfo("正在停止", "当前论文结束后可以关闭窗口。")
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    poll()
    root.mainloop()
