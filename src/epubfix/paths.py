"""Href / path helpers."""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit


def is_external(href: str) -> bool:
    if not href:
        return True
    return bool(urlsplit(href).scheme) or href.startswith("//") or href.startswith("mailto:")


def split_href(href: str) -> tuple[str, str]:
    if "#" in href:
        path, frag = href.split("#", 1)
        return path, frag
    return href, ""


def resolve_href(doc_name: str, href: str) -> tuple[str | None, str]:
    """Resolve an href found in ``doc_name`` to a zip path and fragment."""
    if is_external(href):
        return None, ""
    path, frag = split_href(href)
    if not path:
        return doc_name, unquote(frag)
    path = unquote(path)
    if path.startswith("/"):
        name = posixpath.normpath(path.lstrip("/"))
    else:
        base = posixpath.dirname(doc_name)
        name = posixpath.normpath(posixpath.join(base, path))
    return name, unquote(frag)


def rel_href(from_doc: str, to_zip: str, frag: str = "") -> str:
    start = posixpath.dirname(from_doc) or "."
    rel = posixpath.relpath(to_zip, start)
    if frag:
        rel += "#" + frag
    return rel


def url_quote_path(path: str) -> str:
    """Quote only characters that commonly break EPUB readers."""
    return path.replace(" ", "%20").replace("#", "%23")
