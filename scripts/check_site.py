#!/usr/bin/env python3
"""Validate local links/assets and basic sitemap rules for this static GitHub Pages site."""

from __future__ import annotations

import posixpath
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SITE_HOSTS = {"shirazpcrepair.ir", "www.shirazpcrepair.ir"}
RESOURCE_ATTRIBUTES = {"href", "src", "action", "poster"}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []
        self.canonical_urls: list[str] = []
        self.robots_values: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        for attribute in RESOURCE_ATTRIBUTES:
            value = values.get(attribute, "").strip()
            if value:
                if tag == "link" and attribute == "href" and "canonical" in values.get("rel", "").lower().split():
                    self.canonical_urls.append(value)
                else:
                    self.references.append((value, f"<{tag} {attribute}>"))
        if tag == "meta":
            meta_name = values.get("name", "").lower()
            meta_property = values.get("property", "").lower()
            content = values.get("content", "").strip()
            if content and (meta_property == "og:image" or meta_name == "twitter:image"):
                self.references.append((content, f"<meta {meta_property or meta_name}>"))
            if meta_name == "robots" and content:
                self.robots_values.append(content.lower())
        element_id = values.get("id", "").strip()
        if element_id:
            self.ids.add(element_id)
        if tag == "a":
            name = values.get("name", "").strip()
            if name:
                self.ids.add(name)


def resolve_local_path(url: str, source: str) -> str | None:
    """Return a repo-relative target for same-site URLs; return None for external URLs."""
    raw = url.strip()
    if not raw or raw.startswith("#"):
        return None

    parsed = urlsplit(raw)
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.netloc and parsed.netloc.lower() not in SITE_HOSTS:
        return None
    if parsed.scheme and not parsed.netloc:
        return None

    path = unquote(parsed.path)
    if not path:
        path = source
    elif path.startswith("/"):
        path = path.lstrip("/")
    else:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))

    if path in {"", "."}:
        path = "index.html"
    if path.endswith("/"):
        path += "index.html"
    return path


def main() -> int:
    errors: list[str] = []
    html_files = sorted(ROOT.rglob("*.html"))
    if not (ROOT / "index.html").is_file():
        errors.append("Missing required root index.html")
    if not (ROOT / "404.html").is_file():
        errors.append("Missing custom 404.html")

    parsers: dict[str, PageParser] = {}
    for file in html_files:
        if ".git" in file.parts:
            continue
        rel = file.relative_to(ROOT).as_posix()
        parser = PageParser()
        try:
            parser.feed(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: cannot read HTML ({exc})")
            continue
        parsers[rel] = parser

        for url, context in parser.references:
            target = resolve_local_path(url, rel)
            if target is None:
                continue
            target_path = ROOT / target
            if not target_path.is_file():
                errors.append(f"{rel}: missing local target {target!r} from {context}={url!r}")

        for url in parser.canonical_urls:
            target = resolve_local_path(url, rel)
            if target is not None and not (ROOT / target).is_file():
                errors.append(f"{rel}: canonical URL points to missing local page {url!r}")

    sitemap = ROOT / "sitemap.xml"
    try:
        xml_root = ElementTree.parse(sitemap).getroot()
        locations = [
            element.text.strip()
            for element in xml_root.iter()
            if element.tag.endswith("loc") and element.text and element.text.strip()
        ]
        for url in locations:
            target = resolve_local_path(url, "sitemap.xml")
            if target is not None and not (ROOT / target).is_file():
                errors.append(f"sitemap.xml: URL has no matching file: {url}")
    except (OSError, ElementTree.ParseError) as exc:
        errors.append(f"sitemap.xml: invalid or missing XML ({exc})")
        locations = []

    software = ROOT / "software.html"
    if software.is_file():
        software_parser = parsers.get("software.html")
        robots = ",".join(software_parser.robots_values) if software_parser else ""
        if "noindex" not in robots:
            errors.append("software.html: placeholder should remain noindex until product details are ready")
        if any(urlsplit(url).path.rstrip("/").endswith("/software.html") for url in locations):
            errors.append("sitemap.xml: software.html is noindex but appears in sitemap")

    home = parsers.get("index.html")
    if home and not any(urlsplit(url).path.rstrip("/").endswith("/software.html") or url == "software.html"
                        for url, _ in home.references):
        errors.append("index.html: expected a link to software.html")

    if errors:
        print("Site validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print(f"Site validation passed: checked {len(parsers)} HTML pages and {len(locations)} sitemap URLs.")
    print("Local links/assets resolve; sitemap XML is valid; software placeholder remains noindex.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
