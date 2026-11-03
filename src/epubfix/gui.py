# -*- coding: utf-8 -*-
"""A small Tkinter GUI for epubfix.

Run with:

    python -m epubfix.gui

or, after ``pip install -e .``:

    epubfix-gui

The GUI is a thin wrapper around :func:`epubfix.pipeline.fix`; it does not
change any of the typesetting rules.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .pipeline import FixOptions, fix
from .report import STAT_LABELS

THEME_LABELS = {"novel": "文学小说风"}
THEME_KEYS = {label: key for key, label in THEME_LABELS.items()}
DEFAULT_MAX_CHARS = 30000
LEVEL_LABELS = {"error": "错误", "warning": "警告", "info": "提示"}


# ---------------------------------------------------------------------------
# Pure helpers (kept separate so they are easy to test)
# ---------------------------------------------------------------------------

def default_output_path(input_path: str | Path) -> Path:
    """Return the default output path next to the input file."""
    path = Path(input_path)
    return path.with_name(f"{path.stem}-精排.epub")


def format_stats(stats: dict[str, int]) -> str:
    if not stats:
        return "改动统计：没有需要改动的项"
    lines = ["改动统计："]
    for key, n in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {STAT_LABELS.get(key, key)}：{n}")
    return "\n".join(lines)


def format_issues(issues: list[dict]) -> str:
    if not issues:
        return "结构校验：通过"
    errors = sum(1 for item in issues if item.get("level") == "error")
    warnings = sum(1 for item in issues if item.get("level") == "warning")
    lines = [f"结构校验：{errors} 个错误，{warnings} 个警告"]
    for item in issues[:20]:
        level = LEVEL_LABELS.get(item.get("level", ""), item.get("level", ""))
        where = item.get("where") or ""
        suffix = f"  ({where})" if where else ""
        lines.append(
            f"  [{level}] {item.get('code', '')}: {item.get('message', '')}{suffix}"
        )
    if len(issues) > 20:
        lines.append(f"  ... 其余 {len(issues) - 20} 条")
    return "\n".join(lines)


def format_idempotent(result: dict | None) -> str:
    if result is None:
        return "幂等检查：未执行"
    changed = sum(int(v) for v in result.values())
    return f"幂等检查：第二次运行产生 {changed} 处改动" + (
        "（通过）" if changed == 0 else "（未通过）"
    )


def format_result(result: dict) -> str:
    lines: list[str] = []
    if result.get("output"):
        lines.append(f"输出：{result['output']}")
    if result.get("elapsed") is not None:
        lines.append(f"耗时：{result['elapsed']:.2f} 秒")
    lines.append(format_idempotent(result.get("idempotent")))
    lines.append(format_issues(result.get("issues") or []))
    lines.append("")
    lines.append(format_stats(result.get("stats") or {}))
    return "\n".join(lines)


def _open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class EpubFixApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"EPUB 精排工具 v{__version__}")
        self.root.geometry("780x660")
        self.root.minsize(680, 580)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.closing = False
        self.last_output: Path | None = None
        self.last_report: Path | None = None

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.theme_var = tk.StringVar(value=THEME_LABELS["novel"])
        self.max_chars_var = tk.StringVar(value=str(DEFAULT_MAX_CHARS))
        self.split_var = tk.BooleanVar(value=True)
        self.verify_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="请选择一本 EPUB")
        self._setting_output = False
        self.auto_output = True

        self._build()
        self.output_var.trace_add("write", self._on_output_changed)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        style = ttk.Style()
        for theme_name in ("vista", "winnative", "clam"):
            try:
                style.theme_use(theme_name)
                break
            except tk.TclError:
                continue

        main = ttk.Frame(self.root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)
        main.rowconfigure(6, weight=1)

        ttk.Label(main, text="输入 EPUB").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(main, textvariable=self.input_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(main, text="选择…", command=self._choose_input).grid(
            row=0, column=2, sticky="ew", pady=4
        )

        ttk.Label(main, text="输出文件").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(main, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=(8, 8), pady=4
        )
        ttk.Button(main, text="另存为…", command=self._choose_output).grid(
            row=1, column=2, sticky="ew", pady=4
        )

        options = ttk.LabelFrame(main, text="处理选项", padding=(10, 8))
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        options.columnconfigure(1, weight=0)

        ttk.Label(options, text="排版主题").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            options,
            textvariable=self.theme_var,
            values=list(THEME_LABELS.values()),
            state="readonly",
            width=16,
        ).grid(row=0, column=1, sticky="w", padx=(8, 24))

        ttk.Label(options, text="拆分阈值").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            options,
            from_=1000,
            to=500000,
            increment=5000,
            textvariable=self.max_chars_var,
            width=10,
        ).grid(row=0, column=3, sticky="w", padx=(8, 4))
        ttk.Label(options, text="字").grid(row=0, column=4, sticky="w")

        ttk.Checkbutton(
            options, text="拆分长文件", variable=self.split_var
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            options, text="完成后检查幂等", variable=self.verify_var
        ).grid(row=1, column=2, columnspan=3, sticky="w", pady=(8, 0))

        self.start_button = ttk.Button(
            main, text="开始精排", command=self._start
        )
        self.start_button.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(12, 6), ipady=4
        )

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 4))

        ttk.Label(
            main, textvariable=self.status_var, foreground="#555555"
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 6))

        result_frame = ttk.LabelFrame(main, text="处理结果", padding=(8, 6))
        result_frame.grid(
            row=6, column=0, columnspan=3, sticky="nsew", pady=(4, 8)
        )
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        self.result_text = tk.Text(
            result_frame,
            height=12,
            wrap="word",
            state="disabled",
            relief="flat",
            background="#fafafa",
            foreground="#222222",
            font=("Microsoft YaHei UI", 10),
            padx=8,
            pady=6,
        )
        self.result_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            result_frame, orient="vertical", command=self.result_text.yview
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.result_text.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(main)
        actions.grid(row=7, column=0, columnspan=3, sticky="ew")
        self.open_dir_button = ttk.Button(
            actions,
            text="打开输出目录",
            command=self._open_output_dir,
            state="disabled",
        )
        self.open_dir_button.pack(side="left")
        self.report_button = ttk.Button(
            actions,
            text="查看报告",
            command=self._open_report,
            state="disabled",
        )
        self.report_button.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="关闭", command=self._on_close).pack(side="right")

    # ------------------------------------------------------------- handlers
    def _on_output_changed(self, *_args) -> None:
        if not self._setting_output:
            self.auto_output = False

    def _set_output(self, path: str | Path, *, auto: bool) -> None:
        self._setting_output = True
        self.output_var.set(str(path))
        self._setting_output = False
        self.auto_output = auto

    def _choose_input(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 EPUB",
            filetypes=[("EPUB 电子书", "*.epub"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.input_var.set(path)
        if self.auto_output or not self.output_var.get().strip():
            self._set_output(default_output_path(path), auto=True)
        self.status_var.set("已选择书籍，可以开始精排")

    def _choose_output(self) -> None:
        current = self.output_var.get().strip()
        initial = Path(current) if current else None
        path = filedialog.asksaveasfilename(
            title="选择输出文件",
            defaultextension=".epub",
            filetypes=[("EPUB 电子书", "*.epub")],
            initialdir=str(initial.parent) if initial else None,
            initialfile=initial.name if initial else None,
        )
        if path:
            self._set_output(path, auto=False)

    def _start(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return

        input_text = self.input_var.get().strip()
        if not input_text:
            messagebox.showwarning("缺少输入", "请先选择一本 EPUB。")
            return
        input_path = Path(input_text).expanduser()
        if not input_path.exists():
            messagebox.showerror("文件不存在", f"找不到输入文件：\n{input_path}")
            return
        if input_path.suffix.lower() != ".epub":
            messagebox.showerror("格式不支持", "输入文件必须是 .epub。")
            return

        output_text = self.output_var.get().strip()
        if not output_text:
            self._set_output(default_output_path(input_path), auto=True)
            output_text = self.output_var.get().strip()
        output_path = Path(output_text).expanduser()
        if output_path.resolve() == input_path.resolve():
            messagebox.showerror("路径冲突", "输出文件不能和输入文件相同。")
            return
        if output_path.suffix.lower() != ".epub":
            messagebox.showerror("扩展名错误", "输出文件请使用 .epub 扩展名。")
            return

        try:
            max_chars = int(self.max_chars_var.get().strip())
        except ValueError:
            messagebox.showerror("参数错误", "拆分阈值必须是整数。")
            return
        if max_chars < 1000:
            messagebox.showerror("参数错误", "拆分阈值不能小于 1000 字。")
            return

        if output_path.exists():
            if not messagebox.askyesno(
                "覆盖输出",
                f"输出文件已存在：\n{output_path}\n\n是否覆盖？",
            ):
                return

        theme = THEME_KEYS.get(self.theme_var.get(), "novel")
        options = FixOptions(
            theme=theme,
            max_chars=max_chars,
            split=bool(self.split_var.get()),
            verify=bool(self.verify_var.get()),
        )
        report_dir = output_path.parent / "reports"

        self.last_output = None
        self.last_report = None
        self.open_dir_button.configure(state="disabled")
        self.report_button.configure(state="disabled")
        self._set_result("")
        self.status_var.set("正在处理，请稍候…")
        self.start_button.configure(state="disabled")
        self.progress.start(12)

        self.worker = threading.Thread(
            target=self._run_fix,
            args=(input_path, output_path, options, report_dir),
            daemon=True,
        )
        self.worker.start()

    def _run_fix(
        self,
        input_path: Path,
        output_path: Path,
        options: FixOptions,
        report_dir: Path,
    ) -> None:
        try:
            result = fix(
                input_path,
                output_path,
                options,
                report_dir=report_dir,
            )
            self.queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", (str(exc), traceback.format_exc())))

    def _poll(self) -> None:
        if self.closing or not self.root.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "done":
                    self._on_done(payload)  # type: ignore[arg-type]
                elif kind == "error":
                    self._on_error(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_done(self, result: dict) -> None:
        self.progress.stop()
        self.progress.configure(value=0)
        self.start_button.configure(state="normal")
        elapsed = result.get("elapsed") or 0.0
        self.status_var.set(f"完成，耗时 {elapsed:.2f} 秒")
        self._set_result(format_result(result))

        if result.get("output"):
            self.last_output = Path(result["output"])
            self.open_dir_button.configure(state="normal")
        if result.get("report_html"):
            self.last_report = Path(result["report_html"])
            self.report_button.configure(state="normal")

    def _on_error(self, payload: tuple[str, str]) -> None:
        message, details = payload
        self.progress.stop()
        self.progress.configure(value=0)
        self.start_button.configure(state="normal")
        self.status_var.set("处理失败")
        self._set_result(f"处理失败：\n{message}\n\n{details}")
        messagebox.showerror("处理失败", message)

    def _set_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _open_output_dir(self) -> None:
        if self.last_output is None or not self.last_output.exists():
            return
        _open_path(self.last_output.parent)

    def _open_report(self) -> None:
        if self.last_report is not None and self.last_report.exists():
            _open_path(self.last_report)

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno(
                "正在处理", "精排尚未完成，确定要退出吗？"
            ):
                return
        self.closing = True
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    EpubFixApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
