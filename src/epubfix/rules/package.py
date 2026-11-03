"""L0 — package metadata and EPUB3 upgrade."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from ..container import DC, OPF, EpubBook
from ..markup import DC_NS


def _has_dc_namespace(book: EpubBook) -> bool:
    return any(
        v == DC_NS
        for el in book.opf_root.iter()
        if isinstance(el.tag, str)
        for v in el.nsmap.values()
    )


def upgrade_package(book: EpubBook) -> None:
    changed = False
    if book.version != "3.0":
        book.opf_root.set("version", "3.0")
        book.version = "3.0"
        changed = True

    # EPUB3 requires unique-identifier to point at a dc:identifier/@id.
    identifiers = book.metadata().findall(f"{DC}identifier")
    if not identifiers:
        el = etree.SubElement(book.metadata(), f"{DC}identifier")
        el.set("id", "bookid")
        el.text = "urn:uuid:00000000-0000-0000-0000-000000000000"
        identifiers = [el]
        changed = True
    uid = book.opf_root.get("unique-identifier")
    if not uid or not any(i.get("id") == uid for i in identifiers):
        first = identifiers[0]
        if not first.get("id"):
            first.set("id", "bookid")
        book.opf_root.set("unique-identifier", first.get("id"))
        changed = True

    if not book.dc("title"):
        book.set_dc("title", Path(book.path).stem)
        changed = True
    if not book.dc("language"):
        book.set_dc("language", "zh-CN")
        changed = True
    if not book.dc("identifier"):
        book.set_dc("identifier", "urn:uuid:00000000-0000-0000-0000-000000000000")
        changed = True

    modified = None
    for meta in book.metadata().findall(f"{OPF}meta"):
        if meta.get("property") == "dcterms:modified":
            modified = meta
            break
    if modified is None:
        meta = etree.SubElement(book.metadata(), f"{OPF}meta")
        meta.set("property", "dcterms:modified")
        meta.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        changed = True

    cover = book.cover_id()
    if cover:
        item = book.item_by_id(cover)
        if item is not None:
            book.set_properties(item, "cover-image")
            book.set_meta_name("cover", cover)
            changed = True

    if not _has_dc_namespace(book):
        book.ensure_dc_namespace()
        changed = True
    if changed:
        book._touch_opf()
