"""EPUB container model: zip, container.xml, OPF, manifest, spine, documents."""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from .markup import (
    CONTAINER_NS,
    DC_NS,
    NCX_NS,
    OPF_NS,
    XHTML_NS,
    MarkupMeta,
    local_name,
    parse_markup,
    serialize_markup,
)
from .paths import resolve_href

OPF = f"{{{OPF_NS}}}"
DC = f"{{{DC_NS}}}"
NCX = f"{{{NCX_NS}}}"
XHTML = f"{{{XHTML_NS}}}"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

XHTML_TYPES = {"application/xhtml+xml", "text/html"}


@dataclass
class Doc:
    book: "EpubBook"
    name: str
    item_id: str
    data: bytes
    root: etree._Element
    meta: MarkupMeta
    dirty: bool = False

    def body(self) -> etree._Element | None:
        body = self.root.find(f"{XHTML}body")
        if body is None:
            body = self.root.find(".//body")
        return body

    def mark(self) -> "Doc":
        self.dirty = True
        return self

    def text_length(self) -> int:
        body = self.body()
        return len("".join(body.itertext()).strip()) if body is not None else 0

    def title(self) -> str:
        t = self.root.find(f".//{XHTML}title")
        return "".join(t.itertext()).strip() if t is not None else ""

    def set_title(self, text: str) -> None:
        t = self.root.find(f".//{XHTML}title")
        if t is not None:
            t.text = text
            self.mark()


@dataclass
class Issue:
    level: str  # error / warning / info
    code: str
    message: str
    where: str = ""

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "where": self.where}


@dataclass
class Stats:
    counts: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)

    def add(self, key: str, n: int = 1, sample: str | None = None) -> None:
        if not n:
            return
        self.counts[key] = self.counts.get(key, 0) + n
        if sample and len(self.samples) < 200:
            self.samples.append(sample)


class EpubBook:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path)
        self.order = [i.filename for i in self._zip.infolist()]
        self.infos = {i.filename: i for i in self._zip.infolist()}
        self.files: dict[str, bytes] = {n: self._zip.read(n) for n in self.order}
        self._zip.close()
        self.removed: set[str] = set()
        self.added: set[str] = set()
        self.docs: dict[str, Doc] = {}
        self.redirects: dict[str, str] = {}
        self.anchor_moves: dict[tuple[str, str], str] = {}
        self.frag_moves: dict[tuple[str, str], tuple[str, str]] = {}
        self.toc_removed: set[str] = set()
        self.stats = Stats()
        self.issues: list[Issue] = []

        if "META-INF/container.xml" not in self.files:
            raise ValueError("not an EPUB: META-INF/container.xml missing")
        container = etree.fromstring(self.files["META-INF/container.xml"])
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            raise ValueError("not an EPUB: rootfile missing in container.xml")
        self.opf_path = rootfile.get("full-path")
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.opf_root, self.opf_meta = parse_markup(self.files[self.opf_path])
        self.version = self.opf_root.get("version", "2.0")

    # ------------------------------------------------------------------ paths
    def zip_name(self, item: etree._Element) -> str:
        href = unquote(item.get("href", "").split("#", 1)[0])
        return posixpath.normpath(posixpath.join(self.opf_dir, href))

    def href_from(self, target_zip: str, doc_zip: str) -> str:
        start = posixpath.dirname(doc_zip) or "."
        return posixpath.relpath(target_zip, start)

    def exists(self, name: str) -> bool:
        return name in self.files and name not in self.removed

    # --------------------------------------------------------------- manifest
    def manifest(self) -> etree._Element:
        el = self.opf_root.find(f"{OPF}manifest")
        if el is None:
            el = etree.SubElement(self.opf_root, f"{OPF}manifest")
        return el

    def manifest_items(self) -> list[etree._Element]:
        return list(self.manifest().findall(f"{OPF}item"))

    def item_by_id(self, item_id: str) -> etree._Element | None:
        for item in self.manifest_items():
            if item.get("id") == item_id:
                return item
        return None

    def item_by_zip(self, name: str) -> etree._Element | None:
        for item in self.manifest_items():
            if self.zip_name(item) == name:
                return item
        return None

    def unique_id(self, base: str) -> str:
        ids = {i.get("id") for i in self.manifest_items()}
        if base not in ids:
            return base
        n = 2
        while f"{base}{n}" in ids:
            n += 1
        return f"{base}{n}"

    def add_item(
        self,
        href: str,
        media_type: str,
        item_id: str | None = None,
        properties: str | None = None,
    ) -> etree._Element:
        item_id = self.unique_id(item_id or Path(href).stem.replace(".", "-") or "item")
        item = etree.SubElement(self.manifest(), f"{OPF}item")
        item.set("id", item_id)
        item.set("href", href)
        item.set("media-type", media_type)
        if properties:
            item.set("properties", properties)
        self._touch_opf()
        return item

    def remove_item(self, item: etree._Element) -> None:
        name = self.zip_name(item)
        parent = item.getparent()
        if parent is not None:
            parent.remove(item)
        self.remove_file(name)
        self._touch_opf()

    def set_properties(self, item: etree._Element, *props: str) -> None:
        current = set((item.get("properties") or "").split())
        current.update(p for p in props if p)
        if current:
            item.set("properties", " ".join(sorted(current)))
        self._touch_opf()

    # ------------------------------------------------------------------ spine
    def spine(self) -> etree._Element:
        el = self.opf_root.find(f"{OPF}spine")
        if el is None:
            el = etree.SubElement(self.opf_root, f"{OPF}spine")
        return el

    def spine_ids(self) -> list[str]:
        return [r.get("idref") for r in self.spine().findall(f"{OPF}itemref") if r.get("idref")]

    def spine_items(self) -> list[etree._Element]:
        out = []
        for item_id in self.spine_ids():
            item = self.item_by_id(item_id)
            if item is not None:
                out.append(item)
        return out

    def set_spine_ids(self, ids: list[str]) -> None:
        spine = self.spine()
        for ref in list(spine.findall(f"{OPF}itemref")):
            spine.remove(ref)
        for item_id in ids:
            ref = etree.SubElement(spine, f"{OPF}itemref")
            ref.set("idref", item_id)
        self._touch_opf()

    # ------------------------------------------------------------------- docs
    def doc(self, name: str) -> Doc:
        if name in self.docs:
            return self.docs[name]
        item = self.item_by_zip(name)
        if item is None:
            raise KeyError(f"no manifest item for {name}")
        root, meta = parse_markup(self.files[name])
        d = Doc(self, name, item.get("id"), self.files[name], root, meta)
        self.docs[name] = d
        return d

    def content_docs(self) -> list[Doc]:
        out = []
        for item in self.spine_items():
            if item.get("media-type") not in XHTML_TYPES:
                continue
            name = self.zip_name(item)
            if not self.exists(name):
                continue
            out.append(self.doc(name))
        return out

    def all_xhtml(self) -> list[Doc]:
        out = []
        for item in self.manifest_items():
            if item.get("media-type") not in XHTML_TYPES:
                continue
            name = self.zip_name(item)
            if not self.exists(name):
                continue
            out.append(self.doc(name))
        return out

    # -------------------------------------------------------------- metadata
    def metadata(self) -> etree._Element:
        el = self.opf_root.find(f"{OPF}metadata")
        if el is None:
            el = etree.SubElement(self.opf_root, f"{OPF}metadata")
        return el

    def dc(self, tag: str) -> str:
        el = self.metadata().find(f"{DC}{tag}")
        return "".join(el.itertext()).strip() if el is not None else ""

    def set_dc(self, tag: str, text: str) -> None:
        md = self.metadata()
        el = md.find(f"{DC}{tag}")
        if el is None:
            el = etree.SubElement(md, f"{DC}{tag}")
        if "".join(el.itertext()).strip() != text:
            el.text = text
            self._touch_opf()

    def meta_content(self, name: str) -> str:
        for m in self.metadata().findall(f"{OPF}meta"):
            if m.get("name") == name:
                return m.get("content", "")
        return ""

    def set_meta_name(self, name: str, content: str) -> None:
        for m in self.metadata().findall(f"{OPF}meta"):
            if m.get("name") == name:
                if m.get("content") != content:
                    m.set("content", content)
                    self._touch_opf()
                return
        m = etree.SubElement(self.metadata(), f"{OPF}meta")
        m.set("name", name)
        m.set("content", content)
        self._touch_opf()

    def cover_id(self) -> str:
        cid = self.meta_content("cover")
        if cid and self.item_by_id(cid) is not None:
            return cid
        for item in self.manifest_items():
            props = (item.get("properties") or "").split()
            if "cover-image" in props:
                return item.get("id")
        for item in self.manifest_items():
            if item.get("media-type", "").startswith("image/"):
                if "cover" in item.get("href", "").lower():
                    return item.get("id")
        return ""

    def title(self) -> str:
        return self.dc("title")

    # ---------------------------------------------------------------- writing
    def _touch_opf(self) -> None:
        self.opf_dirty = True

    def flush(self) -> None:
        for name, doc in self.docs.items():
            if doc.dirty:
                self.files[name] = serialize_markup(doc.root, doc.meta)
                doc.dirty = False
        if getattr(self, "opf_dirty", False):
            self.ensure_dc_namespace()
            data = serialize_markup(self.opf_root, self.opf_meta)
            # Keep the package element unprefixed, matching common EPUB tooling.
            data = re.sub(rb"<(/?)opf:([A-Za-z][\w.-]*)", rb"<\1\2", data)
            self.files[self.opf_path] = data
            self.opf_dirty = False

    def ensure_dc_namespace(self) -> None:
        if "dc" in self.opf_root.nsmap:
            return
        nsmap = dict(self.opf_root.nsmap)
        nsmap["dc"] = DC_NS
        new = etree.Element(self.opf_root.tag, nsmap=nsmap)
        for k, v in self.opf_root.attrib.items():
            new.set(k, v)
        new.text = self.opf_root.text
        for child in list(self.opf_root):
            new.append(child)
        self.opf_root = new

    def remove_file(self, name: str) -> None:
        self.removed.add(name)
        self.docs.pop(name, None)

    def prune_guide(self) -> None:
        """Drop/repair legacy <guide> references after structural changes."""
        guide = self.opf_root.find(f"{OPF}guide")
        if guide is None:
            return
        for ref in list(guide.findall(f"{OPF}reference")):
            href = ref.get("href") or ""
            target, frag = resolve_href(self.opf_path, href)
            if target:
                target = self.redirects.get(target, target)
            if not target or not self.exists(target):
                guide.remove(ref)
                self._touch_opf()
                continue
            new_href = posixpath.relpath(target, self.opf_dir)
            if frag:
                new_href += "#" + frag
            if new_href != href:
                ref.set("href", new_href)
                self._touch_opf()
        if len(guide) == 0:
            self.opf_root.remove(guide)
            self._touch_opf()

    def save(self, out_path: str | Path) -> Path:
        self.flush()
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w") as z:
            info = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, b"application/epub+zip")

            for name in self.order:
                if name == "mimetype" or name in self.removed:
                    continue
                if name not in self.files:
                    continue
                orig = self.infos.get(name)
                zi = zipfile.ZipInfo(name, date_time=(orig.date_time if orig else (1980, 1, 1, 0, 0, 0)))
                zi.compress_type = orig.compress_type if orig else zipfile.ZIP_DEFLATED
                zi.external_attr = orig.external_attr if orig else 0
                z.writestr(zi, self.files[name])

            for name in sorted(self.added):
                if name in self.removed or name not in self.files:
                    continue
                zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, self.files[name])
        return out_path

    # ------------------------------------------------------------- validation
    def is_encrypted(self) -> bool:
        if "META-INF/encryption.xml" not in self.files:
            return False
        try:
            root = etree.fromstring(self.files["META-INF/encryption.xml"])
        except etree.XMLSyntaxError:
            return True
        return any(local_name(el) == "EncryptedData" for el in root.iter())
