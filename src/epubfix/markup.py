"""XHTML / XML parsing and serialization helpers.

The main risk in this project is silently corrupting markup. Rules:

* Only documents that are actually modified get re-serialized.
* The original XML declaration / DOCTYPE is preserved.
* Named HTML entities are converted to numeric references before XML parsing,
  otherwise lxml refuses documents that use ``&nbsp;`` without a DTD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.entities import name2codepoint

from lxml import etree

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
XLINK_NS = "http://www.w3.org/1999/xlink"

_DECL_RE = re.compile(rb"^\s*<\?xml[^>]*\?>", re.I)
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE[^>]*(?:\[.*?\])?>", re.I | re.S)
_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]+);")
_KEEP_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


@dataclass
class MarkupMeta:
    has_decl: bool = False
    doctype: bytes | None = None
    encoding: str = "utf-8"


def decode_markup(data: bytes) -> tuple[str, MarkupMeta]:
    """Decode bytes using the XML declaration, then sane Chinese fallbacks."""
    meta = MarkupMeta()
    meta.has_decl = bool(_DECL_RE.match(data))
    m = _DOCTYPE_RE.search(data[:4096])
    if m:
        meta.doctype = m.group(0)

    declared = None
    if meta.has_decl:
        dm = re.search(rb'encoding\s*=\s*["\']([A-Za-z0-9._-]+)["\']', data[:200], re.I)
        if dm:
            declared = dm.group(1).decode("ascii", "ignore")

    for enc in (declared, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            text = data.decode(enc)
            meta.encoding = enc
            return text, meta
        except (UnicodeDecodeError, LookupError):
            continue
    text = data.decode("utf-8", "replace")
    meta.encoding = "utf-8"
    return text, meta


def _numeric_entities(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in _KEEP_ENTITIES:
            return m.group(0)
        code = name2codepoint.get(name)
        return f"&#{code};" if code is not None else m.group(0)

    return _ENTITY_RE.sub(repl, text)


def parse_markup(data: bytes) -> tuple[etree._Element, MarkupMeta]:
    """Parse XHTML (tolerant) and return ``(root, meta)``."""
    text, meta = decode_markup(data)
    text = _numeric_entities(text)
    # lxml's XML serializer injects <meta http-equiv="Content-Type"> when the
    # tree carries an XHTML 1.x doctype. Strip it while parsing; it is restored
    # verbatim by serialize_markup().
    text = re.sub(r"<!DOCTYPE[^>]*(?:\[.*?\])?>", "", text, count=1, flags=re.I | re.S)
    payload = text.encode("utf-8")

    parser = etree.XMLParser(
        recover=True,
        resolve_entities=False,
        huge_tree=True,
        remove_blank_text=False,
        remove_comments=False,
    )
    root = etree.fromstring(payload, parser)
    if root is None:
        raise ValueError("empty or unparseable markup")
    return root, meta


def serialize_markup(root: etree._Element, meta: MarkupMeta) -> bytes:
    payload = etree.tostring(
        root, method="xml", encoding="utf-8", xml_declaration=False
    )
    out = bytearray()
    if meta.has_decl:
        out += b'<?xml version="1.0" encoding="utf-8"?>\n'
    if meta.doctype:
        out += meta.doctype.strip() + b"\n"
    out += payload
    if not out.endswith(b"\n"):
        out += b"\n"
    return bytes(out)


def local_name(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def text_of(el: etree._Element) -> str:
    return "".join(el.itertext())


def collapse_text(text: str) -> str:
    return " ".join(text.split())


def ensure_xhtml_root(root: etree._Element) -> None:
    """Give a bare ``<html>`` the XHTML namespace expected by EPUB3."""
    if not isinstance(root.tag, str):
        return
    if local_name(root) != "html":
        return
    if not root.tag.startswith("{"):
        root.tag = f"{{{XHTML_NS}}}html"


def make_xhtml_document(
    title: str, body_children: list[etree._Element], stylesheet_href: str | None = None
) -> tuple[etree._Element, MarkupMeta]:
    """Build a small XHTML5 document."""
    root = etree.Element(f"{{{XHTML_NS}}}html", nsmap={None: XHTML_NS})
    root.set("lang", "zh-CN")
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "zh-CN")
    head = etree.SubElement(root, f"{{{XHTML_NS}}}head")
    etree.SubElement(head, f"{{{XHTML_NS}}}title").text = title
    if stylesheet_href:
        link = etree.SubElement(head, f"{{{XHTML_NS}}}link")
        link.set("rel", "stylesheet")
        link.set("type", "text/css")
        link.set("href", stylesheet_href)
    body = etree.SubElement(root, f"{{{XHTML_NS}}}body")
    for child in body_children:
        body.append(child)
    meta = MarkupMeta(has_decl=True, doctype=b"<!DOCTYPE html>")
    return root, meta
