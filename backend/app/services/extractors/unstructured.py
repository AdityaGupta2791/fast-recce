"""UnstructuredExtractor — pulls signals from free-text content.

Produces:
- A short property description (best-effort summary from about/home pages)
- Amenity list (matched from a curated keyword vocabulary)
- Feature tags (broader aesthetic / theme signals)
- Lower-confidence contacts found via regex in body text

Structured sources (schema.org, tel/mailto) are handled elsewhere — if a
contact matches there AND here, dedup in ContactService (M5) keeps the
higher-confidence one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.schemas.crawl import ExtractedContact, FetchedPage, UnstructuredData

# Amenities we actively look for. Ordered by frequency of appearance on
# shoot-location websites. All matching is case-insensitive word-boundary.
_AMENITIES = [
    "pool", "swimming pool", "infinity pool",
    "lawn", "garden", "terrace", "rooftop", "courtyard",
    "parking", "valet",
    "wifi", "wi-fi",
    "kitchen", "bar", "lounge", "dining",
    "bbq", "barbecue",
    "air conditioning", "ac ",
    "sea view", "beach view", "mountain view", "lake view",
    "pet friendly", "pet-friendly",
    "jacuzzi", "spa", "sauna",
    "generator", "power backup",
]

# Broader aesthetic / usage tags that reviewers care about.
_FEATURE_TAGS = [
    ("heritage", ["heritage", "colonial", "vintage", "period", "old-world"]),
    ("rustic", ["rustic", "farmhouse style", "barn", "woodland"]),
    ("industrial", ["industrial", "warehouse style", "loft", "raw concrete"]),
    ("luxury", ["luxury", "premium", "luxurious", "opulent"]),
    ("minimalist", ["minimalist", "modern", "contemporary", "scandi"]),
    ("traditional", ["traditional", "colonial", "haveli", "wada"]),
    ("film_friendly", ["photoshoot", "photo shoot", "film shoot", "shoot-ready", "film friendly"]),
    ("events", ["events", "wedding", "reception", "celebration", "gathering"]),
    ("outdoor", ["outdoor", "open-air", "alfresco", "lawn", "beach"]),
]

# Regex contact patterns for free text.
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)\d{3,4}[\s\-]?\d{3,4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class UnstructuredExtractor:
    """Stateless. Safe to reuse across pages."""

    max_description_chars: int = 500

    def extract(self, pages: list[FetchedPage]) -> UnstructuredData:
        data = UnstructuredData()
        combined_text_by_page: list[tuple[str, str]] = []

        for page in pages:
            if not page.html or page.status_code >= 400:
                continue
            soup = BeautifulSoup(page.html, "lxml")
            text = _visible_text(soup)
            combined_text_by_page.append((page.url, text))

            self._extract_text_contacts(text, page.url, data)

        # Amenities + feature tags run on concatenated corpus.
        corpus = " ".join(text for _, text in combined_text_by_page).lower()
        data.amenities = self._match_amenities(corpus)
        data.feature_tags = self._match_feature_tags(corpus)
        data.description = self._pick_description(combined_text_by_page)
        return data

    def _extract_text_contacts(
        self, text: str, page_url: str, data: UnstructuredData
    ) -> None:
        for match in _PHONE_RE.finditer(text):
            candidate = match.group(0).strip()
            if _looks_like_phone(candidate):
                data.text_contacts.append(
                    ExtractedContact(
                        contact_type="phone",
                        value=candidate,
                        source_url=page_url,
                        extraction_method="text_regex",
                        confidence=0.60,
                    )
                )
        for match in _EMAIL_RE.finditer(text):
            candidate = match.group(0).strip()
            if not candidate.endswith(("@example.com", "@sentry.io", "@domain.com")):
                data.text_contacts.append(
                    ExtractedContact(
                        contact_type="email",
                        value=candidate,
                        source_url=page_url,
                        extraction_method="text_regex",
                        confidence=0.55,
                    )
                )

    def _match_amenities(self, corpus: str) -> list[str]:
        found: list[str] = []
        for amenity in _AMENITIES:
            if _word_contains(corpus, amenity):
                # Normalize to the canonical form (strip variants like "wi-fi" -> "wifi")
                canonical = amenity.replace("-", " ").replace("  ", " ").strip()
                if canonical not in found:
                    found.append(canonical)
        return found

    def _match_feature_tags(self, corpus: str) -> list[str]:
        found: list[str] = []
        for tag, keywords in _FEATURE_TAGS:
            if any(_word_contains(corpus, kw) for kw in keywords):
                if tag not in found:
                    found.append(tag)
        return found

    def _pick_description(self, texts: list[tuple[str, str]]) -> str | None:
        """Pick the best description text. Prefer about pages, fall back to home."""
        if not texts:
            return None

        def _score(url: str) -> int:
            url_l = url.lower()
            if "/about" in url_l:
                return 3
            if url_l.endswith("/") or url_l.count("/") <= 3:
                return 2
            return 1

        best_url, best_text = max(texts, key=lambda t: _score(t[0]))
        cleaned = _clean_whitespace(best_text)
        if len(cleaned) < 60:
            return None
        return cleaned[: self.max_description_chars].rsplit(" ", 1)[0] + "..."


# --- Module-private helpers ---


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        if isinstance(tag, Tag):
            tag.decompose()
    return soup.get_text(" ", strip=True)


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _word_contains(corpus: str, phrase: str) -> bool:
    """Word-boundary containment. Allows plural forms (trailing 's')."""
    # Escape regex special chars; allow optional trailing 's' for plurals.
    pattern = r"(?<![a-z])" + re.escape(phrase.lower()) + r"s?(?![a-z])"
    return re.search(pattern, corpus) is not None


def _looks_like_phone(text: str) -> bool:
    """Reject matches with < 10 digits (too short) or > 15 (not a phone)."""
    digits = sum(1 for c in text if c.isdigit())
    return 10 <= digits <= 15
