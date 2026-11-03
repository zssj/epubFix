# -*- coding: utf-8 -*-
"""Round-trip fidelity check: compare an input EPUB with an epubfix output.

The goal is to catch silent content loss, not to require byte equality.

Usage:

    set PYTHONPATH=src
    python scripts/roundtrip_check.py input.epub output.epub
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from epubfix.container import EpubBook  # noqa: E402
from epubfix.markup import local_name, text_of  # noqa: E402
from epubfix.rules.text import _clean_zh  # noqa: E402

BLOCK_TAGS = {
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "figcaption", "pre",
}
TOC_TITLE = re.compile(r"^(目\s*录|目\s*次|contents?|table\s*of\s*contents)$", re.I)
SEPARATOR = re.compile(r"^(?:-{3,}|\*{3,}|·{3,}|—{2,}|_{3,}|={3,})$")


def clean(text: str) -> str:
    return re.sub(r"\s+", "", _clean_zh(text))


def is_nav(book: EpubBook, doc) -> bool:
    item = book.item_by_id(doc.item_id)
    return item is not None and "nav" in (item.get("properties") or "").split()


def is_toc_doc(doc) -> bool:
    body = doc.body()
    if body is None:
        return False
    text = "".join(body.itertext()).strip()
    title = doc.title()
    if not (TOC_TITLE.match(text[:32]) or TOC_TITLE.match(title)):
        return False
    links = sum(1 for a in body.iter() if isinstance(a.tag, str) and local_name(a) == "a" and a.get("href"))
    return links >= 3


def is_title_only(doc) -> bool:
    body = doc.body()
    if body is None:
        return False
    text = "".join(body.itertext()).strip()
    headings = [e for e in body.iter() if isinstance(e.tag, str) and re.fullmatch(r"h[1-6]", local_name(e))]
    return len(headings) == 1 and text == " ".join(text_of(headings[0]).split())


def collect_blocks(book: EpubBook, skip_nav: bool = True) -> tuple[Counter, Counter]:
    counter: Counter = Counter()
    links: Counter = Counter()
    for doc in book.content_docs():
        if skip_nav and is_nav(book, doc):
            continue
        if is_toc_doc(doc):
            continue
        body = doc.body()
        if body is None:
            continue
        for el in body.iter():
            if not isinstance(el.tag, str) or el is body:
                continue
            if local_name(el) not in BLOCK_TAGS:
                continue
            text = clean("".join(el.itertext()))
            if not text:
                continue
            counter[text] += 1
            anchors = [
                a for a in el.iter()
                if isinstance(a.tag, str) and local_name(a) == "a" and a.get("href")
            ]
            if anchors and len(text) <= 80:
                links[text] += 1
    return counter, links


def assets(book: EpubBook) -> dict[str, str]:
    out = {}
    for name in book.files:
        if name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ttf", ".otf", ".woff", ".woff2")):
            out[name] = hashlib.sha256(book.files[name]).hexdigest()
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    a, b = EpubBook(src), EpubBook(dst)

    ca, ca_links = collect_blocks(a)
    cb, _ = collect_blocks(b)
    lost = ca - cb
    added = cb - ca
    total = sum(ca.values())

    # Legacy inline TOC links and separators are intentionally removed.
    expected = Counter()
    for text, n in list(lost.items()):
        if SEPARATOR.match(text) or TOC_TITLE.match(text) or text in ca_links:
            expected[text] = n
            del lost[text]

    print(f"input : {src}")
    print(f"output: {dst}")
    print(f"blocks: {total} in, {sum(cb.values())} out")
    print(f"expected removals: {sum(expected.values())} (separators / legacy TOC labels)")
    print(f"unexplained lost : {sum(lost.values())}")
    for text, n in list(lost.items())[:20]:
        print(f"  LOST x{n}: {text[:70]}")
    print(f"added blocks     : {sum(added.values())}")
    for text, n in list(added.items())[:10]:
        print(f"  ADD  x{n}: {text[:70]}")

    a_assets, b_assets = assets(a), assets(b)
    by_hash_b = {h: n for n, h in b_assets.items()}
    missing_assets = [n for n, h in a_assets.items() if h not in by_hash_b]
    print(f"assets: {len(a_assets)} in, {len(b_assets)} out, missing {len(missing_assets)}")
    for n in missing_assets[:10]:
        print(f"  MISSING: {n}")

    ok = not lost and not missing_assets
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
