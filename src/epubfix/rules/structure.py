"""L1 — structural cleanup: empty nodes, headings, title pages, long-file splitting."""

from __future__ import annotations

import copy
import posixpath
import re

from lxml import etree

from ..container import Doc, EpubBook, XHTML
from ..markup import XHTML_NS, local_name, serialize_markup, text_of
from ..paths import is_external, rel_href, resolve_href

XHTML_TAG = f"{{{XHTML_NS}}}"
BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "td", "th", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "figure", "figcaption", "pre",
}
MEDIA_TAGS = {"img", "svg", "image", "video", "audio", "object", "iframe", "hr"}
INLINE_UNWRAP = {"font", "big", "small", "tt"}
CHAPTER_RE = re.compile(
    r"^(第[〇零一二三四五六七八九十百千万两0-9]+[章回节卷篇部集]|序章|序言|自序|前言|后记|楔子|引子|尾声|附录|终章)"
)
TOC_RE = re.compile(r"^(目\s*录|目\s*次|contents?|table of contents)$", re.I)
TOC_PREFIX_RE = re.compile(r"^(目\s*录|目\s*次|contents?|table of contents)", re.I)
GENERIC_TITLES = {"", "untitled", "无标题", "目录"}


def _iter_elements(root: etree._Element):
    for el in root.iter():
        if isinstance(el.tag, str):
            yield el


def _is_nav_doc(book: EpubBook, doc: Doc) -> bool:
    item = book.item_by_id(doc.item_id)
    return item is not None and "nav" in (item.get("properties") or "").split()


def _has_media(el: etree._Element) -> bool:
    return any(local_name(d) in MEDIA_TAGS for d in el.iter() if d is not el)


def _has_content(el: etree._Element) -> bool:
    if text_of(el).strip():
        return True
    if _has_media(el):
        return True
    # Keep otherwise-empty wrappers that carry an anchor target.
    for d in el.iter():
        if d is el or not isinstance(d.tag, str):
            continue
        if d.get("id") or (local_name(d) == "a" and d.get("name")):
            return True
    return False


def _is_block(el: etree._Element) -> bool:
    return local_name(el) in BLOCK_TAGS


def _unique_id(body: etree._Element, base: str) -> str:
    used = {e.get("id") for e in _iter_elements(body) if e.get("id")}
    if base not in used:
        return base
    n = 2
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


# ---------------------------------------------------------------------------
# headings
# ---------------------------------------------------------------------------

def _heading_level_for(doc: Doc, el: etree._Element) -> int:
    name = local_name(el)
    cls = (el.get("class") or "").lower()
    text = " ".join(text_of(el).split())
    if not text:
        return 0

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        if level == 1 and CHAPTER_RE.match(text):
            return 2
        return level

    # Only inline content may become a heading.
    if any(_is_block(d) for d in el.iter() if d is not el):
        return 0
    # A paragraph that is just a link is a TOC / navigation entry, not a heading.
    if any(
        local_name(d) == "a" and d.get("href")
        for d in el.iter()
        if d is not el
    ) and not any(k in cls for k in ("chapter", "title", "hdc", "booktitle")):
        return 0
    if len(text) > 40 or _has_media(el):
        return 0

    main_title = re.sub(r"\s*[（(].*?[)）]\s*$", "", doc.book.title()).replace(" ", "")
    if main_title and text.replace(" ", "") == main_title:
        return 1

    tokens = set(cls.split())
    if tokens & {"non", "fulu", "fuzhu", "appendix", "supplement"}:
        return 3

    if TOC_RE.match(text):
        return 2
    if CHAPTER_RE.match(text) or re.search(r"(自序|序言|前言|后记|跋|尾声|楔子|引子|附录)$", text):
        return 2
    if len(text) <= 20 and re.search(r"(摘要|评论|导读|译后记|出版说明)$", text):
        return 2

    if "booktitle" in cls or cls == "title" or cls == "book-title":
        return 1
    if any(k in cls for k in ("chapter", "hdc", "chaptertitle", "chapter-title")):
        return 2

    # <p><font size="7">...</font></p> — typical of converted EPUBs.
    for f in el.iter(f"{XHTML_TAG}font"):
        try:
            if int(f.get("size", "0")) >= 6:
                if len(text) <= 14 and not re.search(r"(序|摘要|评论|目录)$", text):
                    return 1
                return 2
        except ValueError:
            pass

    if (el.get("align") or "").lower() == "center" and len(text) <= 20:
        if "mulu" in cls or TOC_RE.match(text):
            return 0
        return 2
    return 0


def normalize_headings(book: EpubBook) -> None:
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        changed = False
        # Existing headings first.
        for el in list(body.iter()):
            if not isinstance(el.tag, str):
                continue
            name = local_name(el)
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = " ".join(text_of(el).split())
                if name == "h1" and CHAPTER_RE.match(text):
                    el.tag = f"{XHTML_TAG}h2"
                    changed = True
                if not el.get("id"):
                    el.set("id", _unique_id(body, "epubfix-h"))
                    changed = True
        # Candidate paragraphs.
        for el in list(body.iter()):
            if not isinstance(el.tag, str):
                continue
            if local_name(el) not in ("p", "div"):
                continue
            level = _heading_level_for(doc, el)
            if not level:
                continue
            text = " ".join(text_of(el).split())
            if not text:
                continue
            el.tag = f"{XHTML_TAG}h{level}"
            if not el.get("id"):
                el.set("id", _unique_id(body, "epubfix-h"))
            book.stats.add("structure.heading_converted", 1, f"{doc.name}: {text[:30]} -> h{level}")
            changed = True
        if changed:
            doc.mark()
        # Reader UI titles: replace empty/generic titles with the first heading.
        if not doc.title() or re.match(r"^(chapter|text|section|part|untitled|无标题)\b", doc.title(), re.I):
            for el in body.iter():
                if isinstance(el.tag, str) and re.fullmatch(r"h[1-6]", local_name(el)):
                    text = " ".join(text_of(el).split())
                    if text:
                        doc.set_title(text)
                    break


def normalize_doc_titles(book: EpubBook) -> None:
    """Replace placeholder document titles (e.g. \"目录\") with the first heading."""
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        current = doc.title().strip()
        if current and not TOC_RE.match(current) and current.lower() not in GENERIC_TITLES | {"正文"}:
            continue
        heading = ""
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            if local_name(el) not in ("h1", "h2", "h3", "h4", "h5", "h6"):
                continue
            text = " ".join("".join(el.itertext()).split())
            if text:
                heading = text
                break
        if heading and heading != current:
            doc.set_title(heading)
            book.stats.add("structure.doc_title_fixed", 1, doc.name)


# ---------------------------------------------------------------------------
# SVG attribute case repair
# ---------------------------------------------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"
_SVG_ATTR_CASE = {
    "viewbox": "viewBox",
    "preserveaspectratio": "preserveAspectRatio",
    "gradientunits": "gradientUnits",
    "gradienttransform": "gradientTransform",
    "patternunits": "patternUnits",
    "patterncontentunits": "patternContentUnits",
    "patterntransform": "patternTransform",
    "markerwidth": "markerWidth",
    "markerheight": "markerHeight",
    "markerunits": "markerUnits",
    "refx": "refX",
    "refy": "refY",
    "textlength": "textLength",
    "lengthadjust": "lengthAdjust",
    "baseprofile": "baseProfile",
    "zoomandpan": "zoomAndPan",
    "attributename": "attributeName",
    "attributetype": "attributeType",
    "repeatcount": "repeatCount",
    "keytimes": "keyTimes",
    "keysplines": "keySplines",
    "calcmode": "calcMode",
    "pathlength": "pathLength",
    "startoffset": "startOffset",
    "textanchor": "textAnchor",
    "dominantbaseline": "dominantBaseline",
    "alignmentbaseline": "alignmentBaseline",
    "stopcolor": "stopColor",
    "stopopacity": "stopOpacity",
    "fillopacity": "fillOpacity",
    "fillrule": "fillRule",
    "strokedasharray": "strokeDasharray",
    "strokedashoffset": "strokeDashoffset",
    "strokelinecap": "strokeLinecap",
    "strokelinejoin": "strokeLinejoin",
    "strokewidth": "strokeWidth",
    "clippath": "clipPath",
    "cliprule": "clipRule",
}


def repair_svg_attributes(book: EpubBook) -> None:
    for doc in book.all_xhtml():
        body = doc.body()
        if body is None:
            continue
        changed = 0
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            if not el.tag.startswith(f"{{{SVG_NS}}}"):
                continue
            for attr in list(el.attrib):
                fixed = _SVG_ATTR_CASE.get(attr.lower())
                if fixed and fixed != attr:
                    el.set(fixed, el.attrib.pop(attr))
                    changed += 1
        if changed:
            doc.mark()
            book.stats.add("structure.svg_repaired", changed, doc.name)


# ---------------------------------------------------------------------------
# presentation / inline junk
# ---------------------------------------------------------------------------

def remove_empty_nodes(book: EpubBook) -> None:
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        removed = 0
        for el in list(body.iter()):
            if not isinstance(el.tag, str) or el is body:
                continue
            if local_name(el) not in ("div", "p", "span", "section", "article"):
                continue
            if el.get("id"):
                continue
            if not _has_content(el):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
                    removed += 1
        if removed:
            doc.mark()
            book.stats.add("structure.empty_removed", removed)


def _unwrap(el: etree._Element) -> bool:
    """Replace an element by its children/text, preserving document order."""
    parent = el.getparent()
    if parent is None:
        return False
    idx = parent.index(el)
    for child in list(el):
        el.remove(child)
        parent.insert(idx, child)
        idx += 1
    if el.text:
        if idx > 0:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + el.text
        else:
            parent.text = (parent.text or "") + el.text
    if el.tail:
        if idx > 0:
            prev = parent[idx - 1]
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)
    return True


def unwrap_inline_junk(book: EpubBook) -> None:
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        removed = 0
        for el in list(body.iter()):
            if not isinstance(el.tag, str) or el is body:
                continue
            name = local_name(el)
            if name in INLINE_UNWRAP:
                if _unwrap(el):
                    removed += 1
            elif name == "span" and not el.get("class") and not el.get("id"):
                keep = (
                    el.get("lang")
                    or el.get("{http://www.w3.org/XML/1998/namespace}lang")
                    or el.get("{http://www.idpf.org/2007/ops}type")
                    or el.get("role")
                )
                if not keep and _unwrap(el):
                    removed += 1
        if removed:
            doc.mark()
            book.stats.add("structure.inline_unwrapped", removed)


def strip_presentation(book: EpubBook) -> None:
    attrs = {
        "align", "valign", "height", "width", "bgcolor", "border",
        "cellpadding", "cellspacing", "face", "size", "color", "clear",
        "nowrap", "hspace", "vspace", "text", "link", "vlink", "alink",
    }
    for doc in book.content_docs():
        if _is_nav_doc(book, doc):
            continue
        body = doc.body()
        if body is None:
            continue
        changed = 0
        media_only = doc.text_length() < 60 and _has_media(body)
        for el in _iter_elements(body):
            if el is body:
                continue
            if el.tag.startswith(f"{{{SVG_NS}}}"):
                # SVG geometry (rect/@width, circle/@r, image/@height ...) is
                # content, not legacy HTML presentation.
                continue
            name = local_name(el)
            align = (el.get("align") or "").lower()
            if align in ("center", "right") and name in ("p", "div"):
                classes = set((el.get("class") or "").split())
                classes.add(align)
                el.set("class", " ".join(sorted(classes)))
            if name in ("img", "image", "svg"):
                continue
            for a in list(el.attrib):
                if a in attrs:
                    del el.attrib[a]
                    changed += 1
            if not media_only and el.get("style"):
                del el.attrib["style"]
                changed += 1
            if el.get("class") == "":
                del el.attrib["class"]
        if changed:
            doc.mark()
            book.stats.add("structure.presentation_stripped", changed)


# ---------------------------------------------------------------------------
# title-only pages + legacy TOC pages
# ---------------------------------------------------------------------------

def _is_title_only(doc: Doc) -> etree._Element | None:
    body = doc.body()
    if body is None or _has_media(body):
        return None
    text = "".join(body.itertext()).strip()
    if not text or len(text) > 80:
        return None
    headings = [e for e in body.iter() if isinstance(e.tag, str) and re.fullmatch(r"h[1-6]", local_name(e))]
    if len(headings) != 1:
        return None
    heading_text = " ".join(text_of(headings[0]).split())
    if heading_text != " ".join(text.split()):
        return None
    if TOC_RE.match(heading_text):
        return None
    return headings[0]


def _first_heading_text(body: etree._Element) -> str:
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        if re.fullmatch(r"h[1-6]", local_name(el)):
            text = " ".join(text_of(el).split())
            if text:
                return text
    return ""


def _titles_equivalent(a: str, b: str) -> bool:
    a = "".join(a.split())
    b = "".join(b.split())
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long.startswith(short)


def merge_title_pages(book: EpubBook) -> None:
    spine = list(book.spine_ids())
    i = 0
    while i < len(spine):
        item = book.item_by_id(spine[i])
        if item is None or item.get("media-type") != "application/xhtml+xml":
            i += 1
            continue
        name = book.zip_name(item)
        if not book.exists(name):
            i += 1
            continue
        doc = book.doc(name)
        heading = _is_title_only(doc)
        if heading is None:
            i += 1
            continue
        # Find the next content document.
        j = i + 1
        while j < len(spine):
            nxt_item = book.item_by_id(spine[j])
            if nxt_item is not None and nxt_item.get("media-type") == "application/xhtml+xml":
                break
            j += 1
        if j >= len(spine):
            i += 1
            continue
        nxt_name = book.zip_name(nxt_item)
        if not book.exists(nxt_name):
            i += 1
            continue
        nxt = book.doc(nxt_name)
        nxt_body = nxt.body()
        if nxt_body is None:
            i += 1
            continue

        heading_text = " ".join(text_of(heading).split())
        existing = _first_heading_text(nxt_body)
        if existing and _titles_equivalent(heading_text, existing):
            # The next page already carries this title; the extra title page is
            # redundant and would produce a duplicate heading after merging.
            book.redirects[name] = nxt_name
            book.remove_item(item)
            spine.pop(i)
            book.set_spine_ids(spine)
            book.stats.add(
                "structure.title_page_dropped", 1, f"{name} -> {nxt_name} (duplicate title)"
            )
            i = 0
            continue
        # Move the heading (and any other meaningful inline blocks) to the next doc.
        existing_ids = {
            e.get("id")
            for e in nxt_body.iter()
            if isinstance(e.tag, str) and e.get("id")
        }
        moved = 0
        for child in list(doc.body()):
            if isinstance(child.tag, str) and _has_content(child):
                child.tail = None
                for d in child.iter():
                    if not isinstance(d.tag, str):
                        continue
                    old = d.get("id")
                    if old and old in existing_ids:
                        new = _unique_id(nxt_body, old)
                        d.set("id", new)
                        book.frag_moves[(nxt_name, old)] = (nxt_name, new)
                        existing_ids.add(new)
                    elif old:
                        existing_ids.add(old)
                nxt_body.insert(moved, child)
                moved += 1
        if not moved:
            i += 1
            continue
        nxt.mark()
        if nxt.title() in GENERIC_TITLES or not nxt.title():
            nxt.set_title(heading_text)
        book.redirects[name] = nxt_name
        book.remove_item(item)
        spine.pop(i)
        book.set_spine_ids(spine)
        book.stats.add("structure.title_page_merged", 1, f"{name} -> {nxt_name}")
        # keep i unchanged: the next doc is now at this position
        i = 0


def remove_legacy_toc(book: EpubBook) -> None:
    docs = book.content_docs()
    for doc in docs[:5]:
        body = doc.body()
        if body is None:
            continue
        item = book.item_by_id(doc.item_id)
        if item is not None and "nav" in (item.get("properties") or "").split():
            continue
        if posixpath.basename(doc.name).lower() in ("nav.xhtml", "toc.xhtml", "contents.xhtml"):
            continue
        text = "".join(body.itertext()).strip()
        title = doc.title()
        if not (
            TOC_PREFIX_RE.match(text)
            or TOC_RE.match(title)
            or "目录" in title
            or "table of contents" in title.lower()
        ):
            continue
        # A real table-of-contents page is redundant once nav/NCX are rebuilt.
        if TOC_RE.match(title) or TOC_PREFIX_RE.match(text):
            if len(text) <= 3000:
                item = book.item_by_id(doc.item_id)
                if item is not None:
                    book.toc_removed.add(doc.name)
                    book.remove_item(item)
                    book.set_spine_ids([i for i in book.spine_ids() if i != doc.item_id])
                    book.stats.add("structure.legacy_toc_removed", 1, doc.name)
                continue
        internal = 0
        for a in body.iter(f"{XHTML_TAG}a"):
            href = a.get("href")
            if href and not is_external(href):
                internal += 1
        if internal < 3 or len(text) > 3000:
            continue
        item = book.item_by_id(doc.item_id)
        if item is None:
            continue
        book.toc_removed.add(doc.name)
        book.remove_item(item)
        book.set_spine_ids([i for i in book.spine_ids() if i != doc.item_id])
        book.stats.add("structure.legacy_toc_removed", 1, doc.name)


# ---------------------------------------------------------------------------
# long document splitting
# ---------------------------------------------------------------------------

def remove_inline_toc(book: EpubBook) -> None:
    """Strip legacy "目录" sections embedded at the top of a content file."""
    for doc in book.content_docs()[:5]:
        body = doc.body()
        if body is None:
            continue
        item = book.item_by_id(doc.item_id)
        if item is not None and "nav" in (item.get("properties") or "").split():
            continue
        heading = None
        for el in body.iter():
            if not isinstance(el.tag, str):
                continue
            if not re.fullmatch(r"h[1-6]", local_name(el)):
                continue
            text = " ".join(text_of(el).split())
            if TOC_RE.match(text):
                heading = el
                break
        if heading is None:
            continue
        parent = heading.getparent()
        if parent is None:
            continue
        siblings = list(parent)
        start = siblings.index(heading)
        victims: list[etree._Element] = [heading]
        links = 0
        for sib in siblings[start + 1 :]:
            if not isinstance(sib.tag, str):
                continue
            if re.fullmatch(r"h[1-6]", local_name(sib)):
                break
            text = "".join(sib.itertext()).strip()
            anchors = [a for a in sib.iter(f"{XHTML_TAG}a") if a.get("href")]
            if anchors and len(text) <= 80:
                links += len(anchors)
                victims.append(sib)
            elif not text:
                if any(
                    d.get("id") or d.get("name")
                    for d in sib.iter()
                    if isinstance(d.tag, str)
                ):
                    break
                victims.append(sib)
            else:
                break
        if links < 3:
            continue
        for el in victims:
            if el.getparent() is parent:
                parent.remove(el)
        doc.mark()
        book.stats.add("structure.inline_toc_removed", len(victims), doc.name)


def split_long_docs(book: EpubBook, max_chars: int = 12000) -> None:
    if max_chars <= 0:
        return
    spine = list(book.spine_ids())
    new_spine: list[str] = []
    for item_id in spine:
        item = book.item_by_id(item_id)
        if item is None or item.get("media-type") != "application/xhtml+xml":
            new_spine.append(item_id)
            continue
        if "nav" in (item.get("properties") or "").split():
            new_spine.append(item_id)
            continue
        name = book.zip_name(item)
        if not book.exists(name):
            new_spine.append(item_id)
            continue
        doc = book.doc(name)
        chars = doc.text_length()
        if chars <= max_chars:
            new_spine.append(item_id)
            continue
        body = doc.body()
        if body is None:
            new_spine.append(item_id)
            continue
        children = [c for c in body if isinstance(c.tag, str)]
        if len(children) < 2:
            new_spine.append(item_id)
            continue

        # Split at top-level block boundaries, never exceeding max_chars
        # unless a single block itself is longer than the limit.
        chunks: list[list[etree._Element]] = []
        current: list[etree._Element] = []
        acc = 0
        for child in children:
            weight = len("".join(child.itertext()))
            if current and acc + weight > max_chars:
                chunks.append(current)
                current = []
                acc = 0
            current.append(child)
            acc += weight
        if current:
            chunks.append(current)
        if len(chunks) < 2:
            new_spine.append(item_id)
            continue

        # Map every anchor id to the part that will contain it.
        id_to_part: dict[str, int] = {}
        for pi, chunk in enumerate(chunks):
            for child in chunk:
                for d in child.iter():
                    if isinstance(d.tag, str) and d.get("id"):
                        id_to_part.setdefault(d.get("id"), pi)
        stem, ext = posixpath.splitext(name)
        part_names = [name]
        for n in range(2, len(chunks) + 1):
            candidate = f"{stem}-p{n:02d}{ext}"
            suffix = n
            while candidate in book.files and candidate not in book.removed:
                suffix += 1
                candidate = f"{stem}-p{suffix:02d}{ext}"
            part_names.append(candidate)

        for frag, pi in id_to_part.items():
            if pi > 0:
                book.anchor_moves[(name, frag)] = part_names[pi]

        base_title = doc.title() or book.title()
        roots: list[etree._Element] = []
        for chunk in chunks:
            root = copy.deepcopy(doc.root)
            new_body = root.find(f"{XHTML}body")
            for c in list(new_body):
                new_body.remove(c)
            for c in chunk:
                new_body.append(copy.deepcopy(c))
            roots.append(root)

        # Rewrite intra-document links that now cross part boundaries.
        for pi, root in enumerate(roots):
            for a in root.iter(f"{XHTML_TAG}a"):
                href = a.get("href")
                if not href or is_external(href):
                    continue
                target, frag = resolve_href(part_names[pi], href)
                if target != name or not frag:
                    continue
                tp = id_to_part.get(frag, 0)
                if tp != pi:
                    a.set("href", rel_href(part_names[pi], part_names[tp], frag))

        # Part 1 keeps the original manifest item and file name, so inbound
        # links without a fragment stay valid.
        doc.root = roots[0]
        doc.set_title(base_title)
        doc.mark()

        new_ids: list[str] = []
        for pi in range(1, len(roots)):
            new_name = part_names[pi]
            data = serialize_markup(roots[pi], doc.meta)
            book.files[new_name] = data
            book.added.add(new_name)
            rel = posixpath.relpath(new_name, book.opf_dir)
            new_item = book.add_item(rel, item.get("media-type"), f"{item.get('id')}-p{pi + 1:02d}")
            if item.get("properties"):
                new_item.set("properties", item.get("properties"))
            d = Doc(book, new_name, new_item.get("id"), data, roots[pi], doc.meta)
            d.set_title(f"{base_title}（{pi + 1}）" if base_title else f"Part {pi + 1}")
            d.dirty = True
            book.docs[new_name] = d
            new_ids.append(new_item.get("id"))

        # Rewrite links from other documents that target a moved anchor.
        for other in book.all_xhtml():
            if other.name in part_names:
                continue
            changed = False
            for a in other.root.iter(f"{XHTML_TAG}a"):
                href = a.get("href")
                if not href or is_external(href):
                    continue
                target, frag = resolve_href(other.name, href)
                if target != name or not frag:
                    continue
                tp = id_to_part.get(frag, 0)
                if tp > 0:
                    a.set("href", rel_href(other.name, part_names[tp], frag))
                    changed = True
            if changed:
                other.mark()

        new_spine.append(item_id)
        new_spine.extend(new_ids)
        book.stats.add(
            "structure.long_doc_split",
            len(chunks),
            f"{name} ({chars} chars) -> {len(chunks)} parts",
        )
    book.set_spine_ids(new_spine)


# ---------------------------------------------------------------------------
# language / body class
# ---------------------------------------------------------------------------

def normalize_html_lang(book: EpubBook) -> None:
    for doc in book.all_xhtml():
        html = doc.root
        if not isinstance(html.tag, str) or local_name(html) != "html":
            continue
        if not html.get("lang"):
            html.set("lang", "zh-CN")
            html.set("{http://www.w3.org/XML/1998/namespace}lang", "zh-CN")
            doc.mark()
