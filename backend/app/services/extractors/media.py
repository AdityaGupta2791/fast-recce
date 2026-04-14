"""MediaExtractor — collects image URLs referenced from property pages.

For MVP this is URL-level only: we record the src, alt text, dimensions if
present in the markup. Perceptual hashing for visual dedup is M6's concern
and will fetch/hash the images then.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from app.schemas.crawl import FetchedPage, MediaItem

# Images smaller than this (in either dimension) are usually icons/logos.
_MIN_INLINE_DIMENSION = 200

# URL fragments that commonly indicate non-property images.
_SKIP_URL_FRAGMENTS = (
    "logo", "icon", "favicon", "sprite", "button",
    "loader", "loading", "placeholder", "avatar",
    "social-", "facebook", "twitter", "instagram-icon",
)

_STYLE_BG_RE = re.compile(r"url\([\"']?([^\"')]+)[\"']?\)", re.IGNORECASE)


@dataclass
class MediaExtractor:
    """Stateless. Safe to reuse across pages."""

    max_items_per_page: int = 30

    def extract(self, pages: list[FetchedPage]) -> list[MediaItem]:
        seen: set[str] = set()
        items: list[MediaItem] = []
        for page in pages:
            if not page.html or page.status_code >= 400:
                continue
            items.extend(self._extract_from_page(page, seen))
        return items

    def _extract_from_page(
        self, page: FetchedPage, seen: set[str]
    ) -> list[MediaItem]:
        soup = BeautifulSoup(page.html, "lxml")
        base_url = page.url
        items: list[MediaItem] = []

        for img in soup.find_all("img", limit=self.max_items_per_page * 2):
            if not isinstance(img, Tag):
                continue
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if not isinstance(src, str) or not src:
                continue

            absolute = urljoin(base_url, src.strip())
            if not absolute.startswith(("http://", "https://")):
                continue
            if absolute in seen:
                continue
            if _should_skip(absolute):
                continue

            width = _int_attr(img, "width")
            height = _int_attr(img, "height")
            if _is_too_small(width, height):
                continue

            alt = img.get("alt")
            items.append(
                MediaItem(
                    media_url=absolute,
                    media_type="image",
                    alt_text=alt.strip() if isinstance(alt, str) and alt.strip() else None,
                    source_page_url=page.url,
                    width=width,
                    height=height,
                )
            )
            seen.add(absolute)
            if len(items) >= self.max_items_per_page:
                break

        # og:image fallback if the page has few inline images.
        if len(items) < 3:
            og = soup.find("meta", attrs={"property": "og:image"})
            if isinstance(og, Tag):
                content = og.get("content")
                if isinstance(content, str) and content.strip():
                    absolute = urljoin(base_url, content.strip())
                    if absolute not in seen and not _should_skip(absolute):
                        items.append(
                            MediaItem(
                                media_url=absolute,
                                media_type="image",
                                alt_text=None,
                                source_page_url=page.url,
                            )
                        )
                        seen.add(absolute)

        return items


# --- Module-private helpers ---


def _should_skip(url: str) -> bool:
    lower = url.lower()
    return any(frag in lower for frag in _SKIP_URL_FRAGMENTS)


def _int_attr(tag: Tag, name: str) -> int | None:
    value = tag.get(name)
    if isinstance(value, str):
        cleaned = value.replace("px", "").strip()
        if cleaned.isdigit():
            return int(cleaned)
    return None


def _is_too_small(width: int | None, height: int | None) -> bool:
    # If dimensions aren't declared in the markup, assume not tiny.
    if width is None and height is None:
        return False
    if width is not None and width < _MIN_INLINE_DIMENSION:
        return True
    if height is not None and height < _MIN_INLINE_DIMENSION:
        return True
    return False
