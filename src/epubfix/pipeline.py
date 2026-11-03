"""Pipeline orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .container import EpubBook
from .report import write_reports
from .rules.navigation import rebuild_navigation
from .rules.package import upgrade_package
from .rules.structure import (
    merge_title_pages,
    normalize_doc_titles,
    normalize_headings,
    normalize_html_lang,
    remove_empty_nodes,
    remove_inline_toc,
    remove_legacy_toc,
    repair_svg_attributes,
    split_long_docs,
    strip_presentation,
    unwrap_inline_junk,
)
from .rules.style import install_styles
from .rules.text import normalize_text
from .validate import validate_book


@dataclass
class FixOptions:
    theme: str = "novel"
    max_chars: int = 30000
    split: bool = True
    dry_run: bool = False
    verify: bool = True


def run_pipeline(book: EpubBook, options: FixOptions) -> None:
    upgrade_package(book)
    normalize_headings(book)
    remove_empty_nodes(book)
    unwrap_inline_junk(book)
    repair_svg_attributes(book)
    strip_presentation(book)
    merge_title_pages(book)
    remove_legacy_toc(book)
    remove_inline_toc(book)
    normalize_doc_titles(book)
    if options.split:
        split_long_docs(book, options.max_chars)
    normalize_text(book)
    install_styles(book, options.theme)
    rebuild_navigation(book)
    normalize_html_lang(book)
    book.prune_guide()


def _verify_idempotent(path: Path, options: FixOptions) -> dict[str, int]:
    book = EpubBook(path)
    before = dict(book.files)
    run_pipeline(book, options)
    book.flush()
    changed = sum(
        1
        for name in set(before) | set(book.files)
        if before.get(name) != book.files.get(name)
    )
    result = dict(book.stats.counts)
    if changed:
        result["__files_changed__"] = changed
    return result


def fix(
    input_path: str | Path,
    output_path: str | Path | None = None,
    options: FixOptions | None = None,
    *,
    report_dir: str | Path | None = None,
) -> dict:
    options = options or FixOptions()
    input_path = Path(input_path)
    started = time.perf_counter()

    book = EpubBook(input_path)
    if book.is_encrypted():
        raise RuntimeError("检测到 DRM / 加密内容，epubfix 不做处理")

    run_pipeline(book, options)
    stats = dict(book.stats.counts)
    samples = list(book.stats.samples)

    if options.dry_run:
        issues = validate_book(book)
        base = Path(report_dir) / input_path.stem if report_dir else input_path
        html_path, json_path = write_reports(
            book,
            issues,
            base,
            stats=stats,
            samples=samples,
            options=options,
            elapsed=time.perf_counter() - started,
            input_path=str(input_path),
            output_path=None,
            dry_run=True,
        )
        return {
            "output": None,
            "stats": stats,
            "issues": [i.as_dict() for i in issues],
            "report_html": str(html_path),
            "report_json": str(json_path),
            "elapsed": time.perf_counter() - started,
        }

    if output_path is None:
        output_path = input_path.with_name(input_path.stem + ".epubfix.epub")
    output_path = Path(output_path)
    if output_path.resolve() == input_path.resolve():
        raise ValueError("输出路径不能与输入相同，请用 -o 指定新文件")
    book.save(output_path)

    saved = EpubBook(output_path)
    issues = validate_book(saved)
    idempotent = _verify_idempotent(output_path, options) if options.verify else None

    base = Path(report_dir) / output_path.stem if report_dir else output_path
    html_path, json_path = write_reports(
        saved,
        issues,
        base,
        stats=stats,
        samples=samples,
        options=options,
        elapsed=time.perf_counter() - started,
        input_path=str(input_path),
        output_path=str(output_path),
        dry_run=False,
        idempotent=idempotent,
    )
    return {
        "output": str(output_path),
        "stats": stats,
        "issues": [i.as_dict() for i in issues],
        "idempotent": idempotent,
        "report_html": str(html_path),
        "report_json": str(json_path),
        "elapsed": time.perf_counter() - started,
    }
