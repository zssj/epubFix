"""Command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .container import EpubBook
from .pipeline import FixOptions, fix
from .rules.navigation import collect_entries
from .validate import validate_book

LEVEL_LABEL = {"error": "错误", "warning": "警告", "info": "提示"}
STAT_LABELS = {
    "structure.heading_converted": "标题识别 / 转换",
    "structure.doc_title_fixed": "文档标题修正",
    "structure.empty_removed": "空节点清理",
    "structure.inline_unwrapped": "无意义内联标签展开",
    "structure.presentation_stripped": "表现属性清理",
    "structure.svg_repaired": "SVG 属性修复",
    "structure.title_page_merged": "标题页合并",
    "structure.title_page_dropped": "重复标题页移除",
    "structure.legacy_toc_removed": "旧目录页移除",
    "structure.inline_toc_removed": "页内旧目录移除",
    "structure.long_doc_split": "长文件拆分",
    "text.normalized": "文本规范化",
    "text.empty_paragraph_removed": "空段落移除",
    "text.separator_converted": "分隔符转分割线",
    "style.stylesheet": "样式表写入",
    "style.semantics": "语义样式标记",
    "navigation.entries": "目录条目",
    "navigation.links_repointed": "失效链接重定向",
    "__files_changed__": "字节级改动文件",
}


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _issue_field(issue, name: str) -> str:
    if isinstance(issue, dict):
        return issue.get(name, "") or ""
    return getattr(issue, name, "") or ""


def _print_issues(issues) -> None:
    if not issues:
        print("  结构校验：通过")
        return
    for i in issues:
        level = _issue_field(i, "level")
        where = _issue_field(i, "where")
        prefix = f"  [{where}]" if where else ""
        print(
            f"  {LEVEL_LABEL.get(level, level)} {_issue_field(i, 'code')}: "
            f"{_issue_field(i, 'message')}{prefix}"
        )


def _has_error(issues) -> bool:
    return any(_issue_field(i, "level") == "error" for i in issues)


def cmd_inspect(args) -> int:
    book = EpubBook(args.path)
    issues = validate_book(book)
    nav = any("nav" in (i.get("properties") or "").split() for i in book.manifest_items())
    ncx = any(i.get("media-type") == "application/x-dtbncx+xml" for i in book.manifest_items())
    images = [i for i in book.manifest_items() if i.get("media-type", "").startswith("image/")]
    docs = book.content_docs()
    entries = collect_entries(book, "")
    print(f"文件      : {book.path}")
    print(f"标题      : {book.title() or '（缺少）'}")
    print(f"作者      : {book.dc('creator') or '（缺少）'}")
    print(f"语言      : {book.dc('language') or '（缺少）'}")
    print(f"EPUB 版本 : {book.version}")
    print(f"OPF       : {book.opf_path}")
    print(f"清单      : {len(book.manifest_items())} 项（图片 {len(images)}）")
    print(f"spine     : {len(book.spine_ids())} 项")
    print(f"目录      : nav={'有' if nav else '无'}  NCX={'有' if ncx else '无'}  标题条目 {len(entries)}")
    print(f"正文      : {len(docs)} 个 XHTML 文件")
    for doc in docs[:12]:
        print(f"  - {doc.name:<34} {doc.text_length():>7} 字  {doc.title()[:28]}")
    if len(docs) > 12:
        print(f"  ... 其余 {len(docs) - 12} 个文件")
    print("结构校验：")
    _print_issues(issues)
    return 1 if _has_error(issues) else 0


def _options(args) -> FixOptions:
    return FixOptions(
        theme=args.theme,
        max_chars=args.max_chars,
        split=not args.no_split,
        dry_run=args.dry_run,
        verify=not args.no_verify,
    )


def _print_result(result) -> None:
    stats = result.get("stats") or {}
    if stats:
        print("改动统计：")
        for key, n in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {STAT_LABELS.get(key, key):<18} {n}")
    else:
        print("改动统计：没有需要改动的项")
    if result.get("idempotent") is not None:
        changed = sum(result["idempotent"].values())
        print(f"幂等检查：第二次运行产生 {changed} 处改动" + ("（通过）" if changed == 0 else "（未通过）"))
    print("结构校验：")
    _print_issues(result.get("issues") or [])
    if result.get("output"):
        print(f"输出      : {result['output']}")
    else:
        print("输出      : 未写文件（dry-run）")
    print(f"报告      : {result['report_html']}")
    print(f"            {result['report_json']}")
    print(f"耗时      : {result['elapsed']:.2f}s")


def cmd_fix(args) -> int:
    out = Path(args.output) if args.output else Path(args.path).with_name(
        Path(args.path).stem + ".epubfix.epub"
    )
    try:
        result = fix(
            args.path,
            out,
            _options(args),
            report_dir=args.report_dir,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"处理失败: {exc}", file=sys.stderr)
        return 2
    print(f"输入      : {args.path}")
    _print_result(result)
    return 1 if _has_error(result.get("issues") or []) else 0


def cmd_validate(args) -> int:
    book = EpubBook(args.path)
    issues = validate_book(book)
    print(f"文件: {args.path}")
    print(f"标题: {book.title() or '（缺少）'}")
    print(f"spine: {len(book.spine_ids())} 项 / manifest: {len(book.manifest_items())} 项")
    _print_issues(issues)
    return 1 if _has_error(issues) else 0


def cmd_gui(args) -> int:
    from .gui import main as gui_main

    return gui_main()


def cmd_batch(args) -> int:
    src = Path(args.directory)
    outdir = Path(args.output or (src / "out"))
    outdir.mkdir(parents=True, exist_ok=True)
    options = _options(args)
    books = [
        p for p in sorted(src.glob("*.epub"))
        if not p.name.endswith(".epubfix.epub") and p.resolve().parent != outdir.resolve()
    ]
    if not books:
        print(f"没有找到 EPUB: {src}")
        return 1
    ok = fail = 0
    for path in books:
        out = outdir / path.name
        print(f"\n=== {path.name} ===")
        try:
            result = fix(path, out, options, report_dir=outdir)
        except Exception as exc:  # noqa: BLE001
            print(f"失败: {exc}", file=sys.stderr)
            fail += 1
            continue
        stats = result.get("stats") or {}
        errors = sum(1 for i in result.get("issues") or [] if i["level"] == "error")
        print(f"输出: {out}")
        print(f"改动: {sum(stats.values())} 处 / 错误: {errors}")
        if errors:
            fail += 1
        else:
            ok += 1
    print(f"\n完成：成功 {ok}，失败 {fail}")
    return 1 if fail else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="epubfix",
        description="EPUB 精排工具：结构修复 + 中文排版重建",
    )
    parser.add_argument("--version", action="version", version=f"epubfix {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="体检一本 EPUB，不改文件")
    p.add_argument("path")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("fix", help="精排一本 EPUB")
    p.add_argument("path")
    p.add_argument("-o", "--output")
    p.add_argument("--theme", default="novel", choices=["novel"])
    p.add_argument("--max-chars", type=int, default=30000, help="单个正文文件超过此字数则拆分")
    p.add_argument("--no-split", action="store_true", help="不拆分长文件")
    p.add_argument("--dry-run", action="store_true", help="只出报告，不写新书")
    p.add_argument("--no-verify", action="store_true", help="跳过幂等检查")
    p.add_argument("--report-dir")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("validate", help="校验 EPUB 结构")
    p.add_argument("path")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("gui", help="打开图形界面")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("batch", help="批量处理一个目录下的 EPUB")
    p.add_argument("directory")
    p.add_argument("-o", "--output")
    p.add_argument("--theme", default="novel", choices=["novel"])
    p.add_argument("--max-chars", type=int, default=30000)
    p.add_argument("--no-split", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--report-dir")
    p.set_defaults(func=cmd_batch)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
