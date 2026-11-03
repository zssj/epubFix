"""L3 — semantic classes and stylesheet installation."""

from __future__ import annotations

import posixpath

from lxml import etree

from ..container import EpubBook, XHTML
from ..markup import XHTML_NS, local_name
from ..themes import THEMES

XHTML_TAG = f"{{{XHTML_NS}}}"


def _classes(el: etree._Element) -> set[str]:
    return set((el.get("class") or "").split())


def _is_nav(book: EpubBook, doc) -> bool:
    item = book.item_by_id(doc.item_id)
    return item is not None and "nav" in (item.get("properties") or "").split()


def _add_class(el: etree._Element, name: str) -> bool:
    cls = _classes(el)
    if name in cls:
        return False
    cls.add(name)
    el.set("class", " ".join(sorted(cls)))
    return True


def _has_media(el: etree._Element) -> bool:
    return any(local_name(d) in {"img", "svg", "image", "video", "audio"} for d in el.iter() if d is not el)


# Legacy books often use compound class names for alignment.  Only add the
# generic theme class; keep the original class so the source intent is visible.
_ALIGN_HINTS = {
    "center": "center",
    "centre": "center",
    "center_right": "right",
    "center-right": "right",
    "centerright": "right",
    "right": "right",
    "left": "left",
}


def _ensure_stylesheet(book: EpubBook, theme: str) -> str:
    css = THEMES[theme]
    css_zip = posixpath.normpath(posixpath.join(book.opf_dir, "styles", "epubfix.css"))
    data = css.encode("utf-8")
    if book.files.get(css_zip) != data:
        book.files[css_zip] = data
        book.added.add(css_zip)
        book.stats.add("style.stylesheet", 1, css_zip)
    item = book.item_by_zip(css_zip)
    if item is None:
        rel = posixpath.relpath(css_zip, book.opf_dir)
        book.add_item(rel, "text/css", "epubfix-css")
    book.stylesheet_zip = css_zip
    return css_zip


def _head(doc) -> etree._Element:
    head = doc.root.find(f"{XHTML}head")
    if head is None:
        head = etree.Element(f"{XHTML}head")
        doc.root.insert(0, head)
        doc.mark()
    return head


def _set_stylesheet_link(doc, css_zip: str) -> int:
    head = _head(doc)
    desired = posixpath.relpath(css_zip, posixpath.dirname(doc.name) or ".")
    links = [
        el for el in head.findall(f"{XHTML}link")
        if "stylesheet" in (el.get("rel") or "").lower()
    ]
    changed = 0
    ours = [l for l in links if l.get("href") == desired]
    if len(links) == 1 and ours and not head.findall(f"{XHTML}style"):
        return 0
    for link in links:
        head.remove(link)
        changed += 1
    for style in head.findall(f"{XHTML}style"):
        head.remove(style)
        changed += 1
    link = etree.SubElement(head, f"{XHTML}link")
    link.set("rel", "stylesheet")
    link.set("type", "text/css")
    link.set("href", desired)
    doc.mark()
    return changed + 1


def _meaningful(el: etree._Element) -> bool:
    if "".join(el.itertext()).strip():
        return True
    return _has_media(el)


def _has_content_before(node: etree._Element, target: etree._Element) -> bool:
    """True when meaningful content appears before ``target`` in doc order."""
    if node is target:
        return False
    if node.text and node.text.strip():
        return True
    for child in node:
        if not isinstance(child.tag, str):
            continue
        if child is target:
            return False
        if target in child.iter():
            return _has_content_before(child, target)
        if _meaningful(child):
            return True
        if child.tail and child.tail.strip():
            return True
    return False


def apply_semantics(book: EpubBook) -> None:
    for doc in book.all_xhtml():
        if _is_nav(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        changed = 0
        # A real cover page carries (almost) no text. Pages with a photo plus a
        # caption are content pages and must keep their normal typography.
        media_only = doc.text_length() < 60 and _has_media(body)
        if media_only:
            changed += _add_class(body, "cover")
        elif "cover" in _classes(body):
            body.attrib.pop("class", None)
            changed += 1

        for el in body.iter():
            if not isinstance(el.tag, str) or el is body:
                continue
            name = local_name(el)
            cls = {c.lower() for c in _classes(el)}
            if name == "div" and ({"hdr", "subtitle", "subhead"} & cls):
                changed += _add_class(el, "subtitle")
            if name == "p" and ({"shi", "poem", "poetry", "verse"} & cls):
                changed += _add_class(el, "poem")
            if name == "blockquote":
                changed += _add_class(el, "quote")
            if name in ("div", "p", "figure") and _has_media(el) and not "".join(el.itertext()).strip():
                changed += _add_class(el, "image")
            if (el.get("{http://www.idpf.org/2007/ops}type") or "") == "footnote":
                changed += _add_class(el, "footnote")
            if name == "a" and (el.get("{http://www.idpf.org/2007/ops}type") or "") == "noteref":
                changed += _add_class(el, "noteref")
            for token in cls:
                align = _ALIGN_HINTS.get(token)
                if align:
                    changed += _add_class(el, align)

        # Heading page-break policy: headings at the very top of a file do not
        # need a forced break; mid-file h1/h2 headings do.
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            tag = local_name(el)
            if tag not in ("h1", "h2", "h3", "h4", "h5", "h6"):
                continue
            level = int(tag[1])
            if not _has_content_before(body, el):
                changed += _add_class(el, "first")
                cls = _classes(el)
                if "chapter" in cls:
                    cls.discard("chapter")
                    el.set("class", " ".join(sorted(cls)) or "")
                    if not el.get("class"):
                        del el.attrib["class"]
                    changed += 1
            elif level <= 2:
                changed += _add_class(el, "chapter")
            else:
                cls = _classes(el)
                if "chapter" in cls:
                    cls.discard("chapter")
                    el.set("class", " ".join(sorted(cls)) or "")
                    if not el.get("class"):
                        del el.attrib["class"]
                    changed += 1
        if changed:
            doc.mark()
            book.stats.add("style.semantics", changed, doc.name)


def install_styles(book: EpubBook, theme: str = "novel") -> None:
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r}, available: {', '.join(THEMES)}")
    css_zip = _ensure_stylesheet(book, theme)
    for doc in book.all_xhtml():
        if _is_nav(book, doc):
            continue
        _set_stylesheet_link(doc, css_zip)
    apply_semantics(book)
