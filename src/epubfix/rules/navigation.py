"""L4 — rebuild nav.xhtml (EPUB3) and toc.ncx (compatibility)."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from lxml import etree

from ..container import EpubBook, NCX_NS
from ..markup import (
    EPUB_NS,
    XHTML_NS,
    MarkupMeta,
    local_name,
    parse_markup,
    serialize_markup,
)
from ..paths import rel_href, resolve_href

XHTML_TAG = f"{{{XHTML_NS}}}"
NCX_TAG = f"{{{NCX_NS}}}"
EPUB_TYPE = f"{{{EPUB_NS}}}type"
_TOC_TITLE = re.compile(r"^(目\s*录|目\s*次|contents?|table of contents)$", re.I)


@dataclass
class Entry:
    level: int
    text: str
    zip_name: str
    frag: str = ""


def _heading_level(el: etree._Element) -> int:
    name = local_name(el)
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return int(name[1])
    return 0


def _entries_from_ncx(book: EpubBook) -> list[Entry]:
    """Use a human-curated NCX when it is detailed enough."""
    ncx_item = next(
        (i for i in book.manifest_items() if i.get("media-type") == "application/x-dtbncx+xml"),
        None,
    )
    if ncx_item is None:
        return []
    ncx_zip = book.zip_name(ncx_item)
    if not book.exists(ncx_zip):
        return []
    try:
        root, _ = parse_markup(book.files[ncx_zip])
    except Exception:  # noqa: BLE001
        return []

    entries: list[Entry] = []

    def walk(parent: etree._Element, depth: int) -> None:
        for point in parent.findall(f"{NCX_TAG}navPoint"):
            label = point.find(f"{NCX_TAG}navLabel/{NCX_TAG}text")
            content = point.find(f"{NCX_TAG}content")
            text = " ".join("".join(label.itertext()).split()) if label is not None else ""
            if text and content is not None and content.get("src"):
                if _TOC_TITLE.match(text):
                    continue
                target, frag = resolve_href(ncx_zip, content.get("src"))
                if target:
                    target = book.redirects.get(target, target)
                if target and frag:
                    moved = book.anchor_moves.get((target, frag))
                    if moved:
                        target = moved
                    fm = book.frag_moves.get((target, frag))
                    if fm:
                        target, frag = fm
                if target and book.exists(target):
                    entries.append(Entry(min(depth, 3), text[:80], target, frag))
            walk(point, depth + 1)

    walk_target = root.find(f"{NCX_TAG}navMap")
    if walk_target is None:
        return []
    walk(walk_target, 1)
    return entries


def collect_entries(book: EpubBook, nav_zip: str) -> list[Entry]:
    curated = _entries_from_ncx(book)
    if len(curated) >= 4:
        seen: set[tuple[str, str, str]] = set()
        unique: list[Entry] = []
        for e in curated:
            key = (e.zip_name, e.frag, e.text)
            if key in seen:
                continue
            seen.add(key)
            unique.append(e)
        return unique

    raw: list[Entry] = []
    for doc in book.content_docs():
        if doc.name == nav_zip:
            continue
        body = doc.body()
        if body is None:
            continue
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            level = _heading_level(el)
            if not level:
                continue
            text = " ".join("".join(el.itertext()).split())
            if not text:
                continue
            if _TOC_TITLE.match(text):
                continue
            raw.append(Entry(level, text[:80], doc.name, el.get("id") or ""))
    if not raw:
        docs = [d for d in book.content_docs() if d.name != nav_zip]
        if docs:
            raw.append(Entry(1, book.title() or "正文", docs[0].name, ""))
    if not raw:
        return []
    minimum = min(e.level for e in raw)
    for e in raw:
        e.level = max(1, min(3, e.level - minimum + 1))
    return raw


def _build_nav(book: EpubBook, entries: list[Entry], nav_zip: str, css_zip: str | None) -> bytes:
    root = etree.Element(
        f"{XHTML_TAG}html",
        nsmap={None: XHTML_NS, "epub": EPUB_NS},
    )
    root.set("lang", "zh-CN")
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "zh-CN")
    head = etree.SubElement(root, f"{XHTML_TAG}head")
    etree.SubElement(head, f"{XHTML_TAG}title").text = "目录"
    if css_zip:
        link = etree.SubElement(head, f"{XHTML_TAG}link")
        link.set("rel", "stylesheet")
        link.set("type", "text/css")
        link.set("href", rel_href(nav_zip, css_zip))
    body = etree.SubElement(root, f"{XHTML_TAG}body")
    nav = etree.SubElement(body, f"{XHTML_TAG}nav")
    nav.set(EPUB_TYPE, "toc")
    nav.set("id", "toc")
    etree.SubElement(nav, f"{XHTML_TAG}h1").text = "目录"

    root_ol = etree.SubElement(nav, f"{XHTML_TAG}ol")
    stack: list[tuple[int, etree._Element]] = [(0, root_ol)]
    for idx, entry in enumerate(entries):
        while len(stack) > 1 and stack[-1][0] >= entry.level:
            stack.pop()
        parent_ol = stack[-1][1]
        li = etree.SubElement(parent_ol, f"{XHTML_TAG}li")
        a = etree.SubElement(li, f"{XHTML_TAG}a")
        a.set("href", rel_href(nav_zip, entry.zip_name, entry.frag))
        a.text = entry.text
        nxt = entries[idx + 1].level if idx + 1 < len(entries) else 0
        if nxt > entry.level:
            child_ol = etree.SubElement(li, f"{XHTML_TAG}ol")
            stack.append((entry.level, child_ol))

    meta = MarkupMeta(has_decl=True, doctype=b"<!DOCTYPE html>")
    return serialize_markup(root, meta)


def _build_ncx(book: EpubBook, entries: list[Entry], ncx_zip: str) -> bytes:
    root = etree.Element(
        f"{NCX_TAG}ncx",
        nsmap={None: NCX_NS},
        version="2005-1",
    )
    head = etree.SubElement(root, f"{NCX_TAG}head")
    uid = etree.SubElement(head, f"{NCX_TAG}meta")
    uid.set("name", "dtb:uid")
    uid.set("content", book.dc("identifier") or "epubfix")
    depth = etree.SubElement(head, f"{NCX_TAG}meta")
    depth.set("name", "dtb:depth")
    depth.set("content", str(max((e.level for e in entries), default=1)))
    total = etree.SubElement(head, f"{NCX_TAG}meta")
    total.set("name", "dtb:totalPageCount")
    total.set("content", "0")
    maxp = etree.SubElement(head, f"{NCX_TAG}meta")
    maxp.set("name", "dtb:maxPageNumber")
    maxp.set("content", "0")

    doc_title = etree.SubElement(root, f"{NCX_TAG}docTitle")
    etree.SubElement(doc_title, f"{NCX_TAG}text").text = book.title() or "正文"
    nav_map = etree.SubElement(root, f"{NCX_TAG}navMap")
    for idx, entry in enumerate(entries, 1):
        point = etree.SubElement(nav_map, f"{NCX_TAG}navPoint")
        point.set("id", f"navPoint-{idx}")
        point.set("playOrder", str(idx))
        label = etree.SubElement(point, f"{NCX_TAG}navLabel")
        etree.SubElement(label, f"{NCX_TAG}text").text = entry.text
        content = etree.SubElement(point, f"{NCX_TAG}content")
        content.set("src", rel_href(ncx_zip, entry.zip_name, entry.frag))

    meta = MarkupMeta(has_decl=True, doctype=None)
    return serialize_markup(root, meta)


def _ensure_nav_item(book: EpubBook, data: bytes) -> tuple[str, etree._Element]:
    nav_item = None
    for item in book.manifest_items():
        if "nav" in (item.get("properties") or "").split():
            nav_item = item
            break
    if nav_item is None:
        nav_zip = posixpath.normpath(posixpath.join(book.opf_dir, "nav.xhtml"))
        rel = posixpath.relpath(nav_zip, book.opf_dir)
        nav_item = book.add_item(rel, "application/xhtml+xml", "epubfix-nav", "nav")
    else:
        nav_zip = book.zip_name(nav_item)
        book.set_properties(nav_item, "nav")
    if book.files.get(nav_zip) != data:
        book.files[nav_zip] = data
        if nav_zip not in book.infos:
            book.added.add(nav_zip)
        book.docs.pop(nav_zip, None)
    return nav_zip, nav_item


def _ensure_ncx_item(book: EpubBook, data: bytes) -> tuple[str, etree._Element]:
    ncx_item = None
    for item in book.manifest_items():
        if item.get("media-type") == "application/x-dtbncx+xml":
            ncx_item = item
            break
    if ncx_item is None:
        ncx_zip = posixpath.normpath(posixpath.join(book.opf_dir, "toc.ncx"))
        rel = posixpath.relpath(ncx_zip, book.opf_dir)
        ncx_item = book.add_item(rel, "application/x-dtbncx+xml", "epubfix-ncx")
    else:
        ncx_zip = book.zip_name(ncx_item)
    if book.files.get(ncx_zip) != data:
        book.files[ncx_zip] = data
        if ncx_zip not in book.infos:
            book.added.add(ncx_zip)
    return ncx_zip, ncx_item


def _repoint_links(book: EpubBook, nav_zip: str) -> None:
    """Rewrite links that pointed at merged title pages or removed TOC pages."""
    changed = 0
    for doc in book.all_xhtml():
        if doc.name == nav_zip:
            continue
        item = book.item_by_id(doc.item_id)
        if item is not None and "nav" in (item.get("properties") or "").split():
            continue
        doc_changed = False
        for a in doc.root.iter(f"{XHTML_TAG}a"):
            href = a.get("href")
            if not href:
                continue
            target, frag = resolve_href(doc.name, href)
            if target is None:
                continue
            new_target = target
            new_frag = frag
            if target in book.redirects:
                new_target = book.redirects[target]
                fm = book.frag_moves.get((new_target, frag))
                if fm:
                    new_target, new_frag = fm
            elif target in book.toc_removed:
                new_target, new_frag = nav_zip, ""
            elif frag and book.anchor_moves.get((target, frag)):
                new_target = book.anchor_moves[(target, frag)]
            if new_target != target or new_frag != frag:
                a.set("href", rel_href(doc.name, new_target, new_frag))
                doc_changed = True
                changed += 1
        if doc_changed:
            doc.mark()
    if changed:
        book.stats.add("navigation.links_repointed", changed)


def rebuild_navigation(book: EpubBook) -> None:
    # Locate the (possibly existing) nav path before collecting entries.
    nav_zip = posixpath.normpath(posixpath.join(book.opf_dir, "nav.xhtml"))
    for item in book.manifest_items():
        if "nav" in (item.get("properties") or "").split():
            nav_zip = book.zip_name(item)
            break
    ncx_zip = posixpath.normpath(posixpath.join(book.opf_dir, "toc.ncx"))
    for item in book.manifest_items():
        if item.get("media-type") == "application/x-dtbncx+xml":
            ncx_zip = book.zip_name(item)
            break
    prev_nav = book.files.get(nav_zip)
    prev_ncx = book.files.get(ncx_zip)

    entries = collect_entries(book, nav_zip)
    css_zip = getattr(book, "stylesheet_zip", None)
    nav_data = _build_nav(book, entries, nav_zip, css_zip)
    nav_zip, nav_item = _ensure_nav_item(book, nav_data)

    _ensure_ncx_item(book, _build_ncx(book, entries, ncx_zip))
    ncx_data = _build_ncx(book, entries, ncx_zip)
    if book.files.get(ncx_zip) != ncx_data:
        book.files[ncx_zip] = ncx_data
        if ncx_zip not in book.infos:
            book.added.add(ncx_zip)

    spine_item = book.spine()
    spine_item.set("toc", book.item_by_zip(ncx_zip).get("id"))
    book._touch_opf()

    ids = book.spine_ids()
    if nav_item.get("id") not in ids:
        ids.insert(1 if len(ids) > 0 else 0, nav_item.get("id"))
        book.set_spine_ids(ids)
    _repoint_links(book, nav_zip)
    if book.files.get(nav_zip) != prev_nav or book.files.get(ncx_zip) != prev_ncx:
        book.stats.add("navigation.entries", len(entries), f"{len(entries)} TOC entries")
