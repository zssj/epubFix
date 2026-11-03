# -*- coding: utf-8 -*-
"""End-to-end tests for the epubfix pipeline.

Run with:

    set PYTHONPATH=src
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import posixpath
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubfix.container import EpubBook  # noqa: E402
from epubfix.pipeline import FixOptions, fix  # noqa: E402
from epubfix.validate import validate_book  # noqa: E402

XHTML = "http://www.w3.org/1999/xhtml"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="bookid" version="2.0">
  <metadata>
    <dc:title>测试书</dc:title>
    <dc:creator>测试作者</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:identifier id="bookid">urn:uuid:11111111-1111-1111-1111-111111111111</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="Style/style.css" media-type="text/css"/>
    <item id="toc" href="Text/toc.html" media-type="application/xhtml+xml"/>
    <item id="title" href="Text/title.html" media-type="application/xhtml+xml"/>
    <item id="ch1" href="Text/chapter1.html" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="toc"/>
    <itemref idref="title"/>
    <itemref idref="ch1"/>
  </spine>
  <guide>
    <reference type="toc" title="目录" href="Text/toc.html"/>
    <reference type="text" title="正文" href="Text/title.html"/>
  </guide>
</package>
"""

NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:11111111-1111-1111-1111-111111111111"/></head>
  <docTitle><text>测试书</text></docTitle>
  <navMap>
    <navPoint id="n1" playOrder="1"><navLabel><text>第一章 开端</text></navLabel><content src="Text/title.html"/></navPoint>
    <navPoint id="n2" playOrder="2"><navLabel><text>第二章 发展</text></navLabel><content src="Text/chapter1.html#sec2"/></navPoint>
    <navPoint id="n3" playOrder="3"><navLabel><text>第三章 转折</text></navLabel><content src="Text/chapter1.html#sec3"/></navPoint>
    <navPoint id="n4" playOrder="4"><navLabel><text>第四章 高潮</text></navLabel><content src="Text/chapter1.html#sec4"/></navPoint>
  </navMap>
</ncx>
"""

TOC_DOC = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>目录</title>
<link rel="stylesheet" href="../Style/style.css"/></head>
<body><h1>目录</h1>
<p><a href="title.html">第一章 开端</a></p>
<p><a href="chapter1.html#sec2">第二章 发展</a></p>
<p><a href="chapter1.html#sec3">第三章 转折</a></p>
</body></html>
"""

TITLE_DOC = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>test</title></head>
<body><p align="center" height="3em"><font size="7"><b>第一章 开端</b></font></p></body></html>
"""


def _paragraphs() -> str:
    body = []
    for i in range(1, 41):
        anchor = f' id="sec{i}"' if i in (2, 3) else ""
        if i == 35:
            anchor = ' id="sec4"'
        body.append(
            f'<p{anchor} style="text-indent: 2em" height="1em" width="2em" align="justify">'
            f"这是第 {i} 段测试文字，用来检查断行、缩进、标点……以及空格   是否被正确规范化。"
            f"</p>"
        )
        if i == 2:
            body.append('<p><a href="#sec4">跳到第四章</a></p>')
        if i == 5:
            body.append("<p>---</p>")
    return "\n".join(body)


CHAPTER_DOC = (
    """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>chapter 1</title>
<link rel="stylesheet" href="../Style/style.css"/></head>
<body><div class="hdc"><h1>第一章 开端</h1><div class="hdr">副标题<br/>第二行</div></div>
<svg xmlns="http://www.w3.org/2000/svg" height="100%" preserveaspectratio="xMidYMid meet" viewbox="0 0 10 10" width="100%"><rect width="10" height="10"/></svg>
<p>诗曰：</p>
<p class="Shi">床前明月光，疑是地上霜。</p>
"""
    + _paragraphs()
    + """
</body></html>
"""
)

STYLE_CSS = "body { margin: 0; } p { text-indent: 2em; }\n"


def build_sample(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", OPF)
        z.writestr("OEBPS/toc.ncx", NCX)
        z.writestr("OEBPS/Style/style.css", STYLE_CSS)
        z.writestr("OEBPS/Text/toc.html", TOC_DOC)
        z.writestr("OEBPS/Text/title.html", TITLE_DOC)
        z.writestr("OEBPS/Text/chapter1.html", CHAPTER_DOC)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_ids(root) -> set[str]:
    return {
        el.get("id")
        for el in root.iter()
        if isinstance(el.tag, str) and el.get("id")
    }


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.input = self.dir / "sample.epub"
        self.output = self.dir / "out" / "sample.epub"
        build_sample(self.input)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fix_repairs_structure_and_is_idempotent(self) -> None:
        before = sha256(self.input)
        result = fix(
            self.input,
            self.output,
            FixOptions(max_chars=800),
            report_dir=self.dir / "reports",
        )

        self.assertEqual(before, sha256(self.input), "input file must not change")
        self.assertEqual(sum(result["idempotent"].values()), 0, result["idempotent"])
        self.assertFalse([i for i in result["issues"] if i["level"] == "error"], result["issues"])
        self.assertTrue(self.output.exists())
        self.assertTrue(Path(result["report_html"]).exists())

        with zipfile.ZipFile(self.output) as z:
            names = z.namelist()
            first = z.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)

            opf = z.read("OEBPS/content.opf").decode("utf-8")
            self.assertIn('version="3.0"', opf)
            self.assertNotIn("Text/title.html", opf)
            self.assertNotIn("Text/toc.html", opf)
            nav = z.read("OEBPS/nav.xhtml").decode("utf-8")
            self.assertIn('epub:type="toc"', nav)
            self.assertIn("第一章 开端", nav)

            chapter = z.read("OEBPS/Text/chapter1.html").decode("utf-8")
            self.assertNotIn("<font", chapter)
            self.assertNotIn('height="1em"', chapter)
            self.assertNotIn('width="2em"', chapter)
            self.assertNotIn("style=", chapter)
            self.assertIn("<hr", chapter)
            self.assertIn('class="hdr subtitle"', chapter)
            self.assertIn('class="Shi poem"', chapter)
            self.assertIn('class="first"', chapter)
            self.assertIn('viewBox="0 0 10 10"', chapter)
            self.assertIn('preserveAspectRatio="xMidYMid meet"', chapter)
            self.assertNotIn("viewbox=", chapter)
            self.assertNotIn("preserveaspectratio=", chapter)
            # 第一段正文保留，长文被拆分
            self.assertIn("这是第1段测试文字", chapter)
            self.assertTrue(any("chapter1-p" in n for n in names), names)

            # 所有内链都必须还能解析
            nav_root = EpubBook(self.output)
            for doc in nav_root.all_xhtml():
                ids = _all_ids(doc.root)
                for a in doc.root.iter(f"{{{XHTML}}}a"):
                    href = a.get("href") or ""
                    if not href or "://" in href or href.startswith("#"):
                        continue
                    target = href.split("#", 1)[0]
                    frag = href.split("#", 1)[1] if "#" in href else ""
                    base = posixpath.dirname(doc.name)
                    target_name = posixpath.normpath(posixpath.join(base, target))
                    self.assertTrue(
                        nav_root.exists(target_name),
                        f"{doc.name}: broken link {href}",
                    )
                    if frag:
                        self.assertIn(
                            frag,
                            _all_ids(nav_root.doc(target_name).root),
                            f"{doc.name}: missing anchor {href}",
                        )

    def test_validate_clean_output(self) -> None:
        fix(self.input, self.output, FixOptions(max_chars=800), report_dir=self.dir / "reports")
        book = EpubBook(self.output)
        errors = [i for i in validate_book(book) if i.level == "error"]
        self.assertEqual(errors, [], [i.as_dict() for i in errors])

    def test_split_preserves_inline_anchors(self) -> None:
        fix(self.input, self.output, FixOptions(max_chars=800), report_dir=self.dir / "reports")
        book = EpubBook(self.output)
        moved = False
        for doc in book.content_docs():
            for a in doc.root.iter(f"{{{XHTML}}}a"):
                href = a.get("href") or ""
                if "#sec4" in href:
                    moved = "chapter1-p" in href
                    break
        self.assertTrue(moved, "link to a moved anchor should point at the split part")


if __name__ == "__main__":
    unittest.main()
