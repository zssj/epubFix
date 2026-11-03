"""L2 — text normalization for Chinese running text."""

from __future__ import annotations

import re

from lxml import etree

from ..container import Doc, EpubBook
from ..markup import XHTML_NS, local_name

XHTML_TAG = f"{{{XHTML_NS}}}"
CJK = r"\u3400-\u4dbf\u4e00-\u9fff"
CJK_PUNCT = r"，。！？；：、“”‘’（）《》〈〉【】…—·"
SKIP_TAGS = {"pre", "code", "script", "style", "math", "svg", "textarea"}
INLINE_TAGS = {"a", "b", "i", "em", "strong", "span", "u", "sub", "sup"}
BLOCK_TAGS = {
    "body", "p", "div", "section", "article", "li", "td", "th", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "dt", "dd",
}

_HALF_TO_FULL = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}
_SEPARATOR_RE = re.compile(r"^(?:-{3,}|\*{3,}|·{3,}|—{2,}|_{3,}|={3,})$")


def _clean_common(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\u00ad\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"[ \t\r\n]+", " ", text)
    return text


def _clean_zh(text: str) -> str:
    text = _clean_common(text)
    # Remove spaces that sit between CJK characters / CJK punctuation.
    text = re.sub(
        rf"(?<=[{CJK}{CJK_PUNCT}])\s+(?=[{CJK}{CJK_PUNCT}])", "", text
    )
    # ...and between CJK and Arabic numerals ("第 1 段" -> "第1段").
    text = re.sub(rf"(?<=[{CJK}])\s+(?=[0-9])", "", text)
    text = re.sub(rf"(?<=[0-9])\s+(?=[{CJK}])", "", text)
    # No space before closing punctuation, none after opening punctuation.
    text = re.sub(r"\s+([，。！？；：、）》】”’])", r"\1", text)
    text = re.sub(r"([（《【“‘])\s+", r"\1", text)
    # Ellipsis / dash. Only ASCII runs are rewritten; existing full-width
    # ellipses may be intentionally long and are left untouched.
    text = re.sub(r"\.{3,}", "……", text)
    text = re.sub(rf"(?<=[{CJK}])--+(?=[{CJK}])", "——", text)
    # Half-width punctuation following a CJK character.
    text = re.sub(
        rf"(?<=[{CJK}])([,;:?!])", lambda m: _HALF_TO_FULL[m.group(1)], text
    )
    return text


def _strip_block_edges(el: etree._Element) -> None:
    """Trim indentation artefacts from the start/end of a block."""
    if el.text:
        el.text = el.text.lstrip(" \u3000")
    # Walk to the last text node.
    node = el
    while len(node):
        node = node[-1]
    if node is el:
        if el.text:
            el.text = el.text.rstrip(" \u3000")
    elif node.tail:
        node.tail = node.tail.rstrip(" \u3000")


def _walk(el: etree._Element, zh: bool, counter: list[int]) -> None:
    if not isinstance(el.tag, str):
        return
    if local_name(el) in SKIP_TAGS:
        return
    if el.text:
        new = _clean_zh(el.text) if zh else _clean_common(el.text)
        if new != el.text:
            el.text = new
            counter[0] += 1
    for child in list(el):
        _walk(child, zh, counter)
        if child.tail:
            new = _clean_zh(child.tail) if zh else _clean_common(child.tail)
            if new != child.tail:
                child.tail = new
                counter[0] += 1
    # Trim whitespace inside Chinese inline elements (TOC links etc.).
    if zh and local_name(el) in INLINE_TAGS:
        inner = "".join(el.itertext())
        if re.search(rf"[{CJK}]", inner):
            if el.text:
                el.text = el.text.strip(" \u3000") if len(el) == 0 else el.text.lstrip(" \u3000")
                if not el.text:
                    el.text = None
            if len(el):
                last = el[-1]
                if last.tail:
                    last.tail = last.tail.rstrip(" \u3000")
                    if not last.tail:
                        last.tail = None


def _is_nav_doc(book: EpubBook, doc: Doc) -> bool:
    item = book.item_by_id(doc.item_id)
    return item is not None and "nav" in (item.get("properties") or "").split()


def normalize_text(book: EpubBook) -> None:
    zh = book.dc("language").lower().startswith("zh")
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        counter = [0]
        _walk(body, zh, counter)
        for el in body.iter():
            if isinstance(el.tag, str) and local_name(el) in BLOCK_TAGS:
                before = (el.text, el[-1].tail if len(el) else None)
                _strip_block_edges(el)
                after = (el.text, el[-1].tail if len(el) else None)
                if before != after:
                    counter[0] += 1
        if counter[0]:
            doc.mark()
            book.stats.add("text.normalized", counter[0], doc.name)

        # Drop paragraphs that became empty after trimming.
        removed = 0
        separators = 0
        for el in list(body.iter()):
            if not isinstance(el.tag, str) or local_name(el) != "p":
                continue
            text = "".join(el.itertext()).strip()
            if not text and not any(
                local_name(d) in {"img", "svg", "image", "hr"} for d in el.iter() if d is not el
            ):
                if el.get("id"):
                    continue
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
                    removed += 1
                continue
            if text and _SEPARATOR_RE.match(text) and not el.get("id"):
                el.tag = f"{{{XHTML_NS}}}hr"
                el.text = None
                for child in list(el):
                    el.remove(child)
                el.attrib.pop("class", None)
                separators += 1
        if removed:
            doc.mark()
            book.stats.add("text.empty_paragraph_removed", removed)
        if separators:
            doc.mark()
            book.stats.add("text.separator_converted", separators, doc.name)
