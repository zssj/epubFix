# -*- coding: utf-8 -*-
"""Tests for the pure helper functions used by the Tkinter GUI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubfix.gui import (  # noqa: E402
    default_output_path,
    format_idempotent,
    format_issues,
    format_result,
    format_stats,
)


class GuiHelperTest(unittest.TestCase):
    def test_default_output_path(self) -> None:
        path = default_output_path(Path("E:/books/活着.epub"))
        self.assertEqual(path, Path("E:/books/活着-精排.epub"))

    def test_format_stats(self) -> None:
        text = format_stats({"text.normalized": 3, "navigation.entries": 7})
        self.assertIn("文本规范化", text)
        self.assertIn("目录条目", text)
        self.assertIn("7", text)

    def test_format_issues_clean(self) -> None:
        self.assertEqual(format_issues([]), "结构校验：通过")

    def test_format_issues_with_errors(self) -> None:
        text = format_issues(
            [
                {
                    "level": "error",
                    "code": "E001",
                    "message": "坏文件",
                    "where": "a.xhtml",
                }
            ]
        )
        self.assertIn("1 个错误", text)
        self.assertIn("E001", text)
        self.assertIn("a.xhtml", text)

    def test_format_idempotent(self) -> None:
        self.assertIn("0 处改动（通过）", format_idempotent({}))
        self.assertIn("未执行", format_idempotent(None))
        self.assertIn("未通过", format_idempotent({"__files_changed__": 1}))

    def test_format_result(self) -> None:
        text = format_result(
            {
                "output": "out/book.epub",
                "elapsed": 1.25,
                "idempotent": {},
                "issues": [],
                "stats": {"text.normalized": 3},
            }
        )
        self.assertIn("out/book.epub", text)
        self.assertIn("1.25 秒", text)
        self.assertIn("结构校验：通过", text)
        self.assertIn("文本规范化", text)


if __name__ == "__main__":
    unittest.main()
