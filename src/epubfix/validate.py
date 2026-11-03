"""Structural validation for EPUB output."""

from __future__ import annotations

import posixpath
import zipfile

from lxml import etree

from .container import DC, EpubBook, Issue, XHTML
from .markup import (
    DC_NS,
    EPUB_NS,
    NCX_NS,
    XHTML_NS,
    local_name,
    parse_markup,
)
from .paths import is_external, resolve_href

XHTML_TAG = f"{{{XHTML_NS}}}"
NCX_TAG = f"{{{NCX_NS}}}"
EPUB_TYPE = f"{{{EPUB_NS}}}type"


def _ids(root: etree._Element) -> set[str]:
    return {
        el.get("id")
        for el in root.iter()
        if isinstance(el.tag, str) and el.get("id")
    }


def validate_book(book: EpubBook) -> list[Issue]:
    issues: list[Issue] = []

    def err(code: str, msg: str, where: str = "") -> None:
        issues.append(Issue("error", code, msg, where))

    def warn(code: str, msg: str, where: str = "") -> None:
        issues.append(Issue("warning", code, msg, where))

    # ---- mimetype / zip -------------------------------------------------
    if "mimetype" not in book.files:
        err("E001", "缺少 mimetype 文件")
    else:
        if book.order and book.order[0] != "mimetype":
            err("E002", "mimetype 不是 zip 的第一项", book.order[0])
        info = book.infos.get("mimetype")
        if info is not None and info.compress_type != zipfile.ZIP_STORED:
            err("E003", "mimetype 必须是 STORED（不压缩）")
        if book.files["mimetype"].strip() != b"application/epub+zip":
            err("E004", "mimetype 内容不正确")

    if len(book.order) != len(set(book.order)):
        err("E005", "zip 中存在重复文件名")

    # ---- package / metadata --------------------------------------------
    has_dc = any(
        v == DC_NS
        for el in book.opf_root.iter()
        if isinstance(el.tag, str)
        for v in el.nsmap.values()
    )
    if not has_dc:
        err("E010", "OPF 缺少 dc 命名空间（会导致标题/作者识别失败）")
    if book.version != "3.0":
        warn("W010", f"OPF version={book.version}，不是 EPUB3")
    if not book.dc("title"):
        err("E011", "缺少 dc:title")
    if not book.dc("language"):
        warn("W011", "缺少 dc:language")
    if not book.dc("identifier"):
        err("E012", "缺少 dc:identifier")
    if not book.opf_root.get("unique-identifier"):
        warn("W012", "package 缺少 unique-identifier")

    # ---- manifest -------------------------------------------------------
    ids: set[str] = set()
    hrefs: set[str] = set()
    for item in book.manifest_items():
        iid = item.get("id")
        href = item.get("href")
        mt = item.get("media-type")
        if not iid:
            err("E020", "manifest 中存在没有 id 的 item")
        elif iid in ids:
            err("E021", f"manifest id 重复: {iid}")
        ids.add(iid)
        if not href:
            err("E022", f"manifest item 缺少 href: {iid}")
            continue
        if href in hrefs:
            warn("W020", f"manifest href 重复: {href}")
        hrefs.add(href)
        if not mt:
            warn("W021", f"manifest item 缺少 media-type: {iid}")
        name = book.zip_name(item)
        if not book.exists(name):
            err("E023", f"manifest href 指向的文件不存在: {name}", iid)

    # ---- spine ----------------------------------------------------------
    spine_ids = book.spine_ids()
    for item_id in spine_ids:
        if book.item_by_id(item_id) is None:
            err("E030", f"spine idref 在 manifest 中不存在: {item_id}")
    content_count = sum(
        1 for item in book.spine_items() if item.get("media-type") == "application/xhtml+xml"
    )
    if content_count < 3:
        warn("W030", f"spine 只有 {content_count} 个正文文件，部分阅读器进度条可能异常")

    # ---- nav ------------------------------------------------------------
    nav_item = None
    for item in book.manifest_items():
        if "nav" in (item.get("properties") or "").split():
            nav_item = item
            break
    if nav_item is None:
        err("E040", "没有 EPUB3 nav 文档")
    else:
        nav_zip = book.zip_name(nav_item)
        if not book.exists(nav_zip):
            err("E041", f"nav 文件不存在: {nav_zip}")
        else:
            try:
                nav_root, _ = parse_markup(book.files[nav_zip])
                navs = [n for n in nav_root.iter(f"{XHTML_TAG}nav") if n.get(EPUB_TYPE) == "toc"]
                if not navs:
                    err("E042", "nav 文档中没有 epub:type=\"toc\" 的 nav")
                else:
                    for a in navs[0].iter(f"{XHTML_TAG}a"):
                        href = a.get("href") or ""
                        target, frag = resolve_href(nav_zip, href)
                        if target and not book.exists(target):
                            err("E043", f"nav 链接指向不存在的文件: {href}")
                        elif frag:
                            tdoc = book.doc(target)
                            if frag not in _ids(tdoc.root):
                                warn("W040", f"nav 链接锚点不存在: {href}")
            except Exception as exc:  # noqa: BLE001
                err("E044", f"nav 解析失败: {exc}")

    # ---- ncx ------------------------------------------------------------
    ncx_item = next(
        (i for i in book.manifest_items() if i.get("media-type") == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_item is None:
        warn("W050", "没有 NCX，旧阅读器可能无法显示目录")
    else:
        ncx_zip = book.zip_name(ncx_item)
        if not book.exists(ncx_zip):
            err("E051", f"NCX 文件不存在: {ncx_zip}")
        else:
            try:
                ncx_root, _ = parse_markup(book.files[ncx_zip])
                points = list(ncx_root.iter(f"{NCX_TAG}navPoint"))
                if not points:
                    warn("W051", "NCX 中没有 navPoint")
                for p in points:
                    c = p.find(f"{NCX_TAG}content")
                    if c is None or not c.get("src"):
                        warn("W052", "NCX navPoint 缺少 content src")
                        continue
                    target, frag = resolve_href(ncx_zip, c.get("src"))
                    if target and not book.exists(target):
                        err("E052", f"NCX 指向不存在的文件: {c.get('src')}")
            except Exception as exc:  # noqa: BLE001
                err("E053", f"NCX 解析失败: {exc}")

    # ---- documents / links ---------------------------------------------
    docs = []
    for doc in book.all_xhtml():
        try:
            ids = _ids(doc.root)
        except Exception as exc:  # noqa: BLE001
            err("E060", f"XHTML 解析失败: {doc.name}: {exc}")
            continue
        docs.append((doc, ids))

    for doc, doc_ids in docs:
        for a in doc.root.iter(f"{XHTML_TAG}a"):
            href = a.get("href")
            if not href:
                continue
            if is_external(href):
                if href.startswith(("http://", "https://")):
                    warn("W060", f"外部链接: {href}", doc.name)
                continue
            target, frag = resolve_href(doc.name, href)
            if target and not book.exists(target):
                err("E061", f"断链: {href}", doc.name)
            elif frag:
                if target == doc.name:
                    if frag not in doc_ids:
                        warn("W061", f"锚点不存在: {href}", doc.name)
                elif target:
                    try:
                        tdoc = book.doc(target)
                        if frag not in _ids(tdoc.root):
                            warn("W061", f"锚点不存在: {href}", doc.name)
                    except Exception:  # noqa: BLE001
                        pass

        for el in doc.root.iter():
            if not isinstance(el.tag, str):
                continue
            name = local_name(el)
            src = None
            if name == "img":
                src = el.get("src")
            elif name == "image":
                src = el.get("{http://www.w3.org/1999/xlink}href")
            if not src:
                continue
            if is_external(src):
                warn("W062", f"外部图片: {src}", doc.name)
                continue
            target, _ = resolve_href(doc.name, src)
            if target and not book.exists(target):
                err("E062", f"图片不存在: {src}", doc.name)

        for link in doc.root.iter(f"{XHTML_TAG}link"):
            href = link.get("href")
            if not href or is_external(href):
                continue
            target, _ = resolve_href(doc.name, href)
            if target and not book.exists(target):
                err("E063", f"样式表/资源不存在: {href}", doc.name)

    if book.is_encrypted():
        err("E070", "检测到加密内容（DRM），本工具不做处理")

    return issues
