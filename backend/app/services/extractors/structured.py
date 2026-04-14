"""StructuredExtractor — pulls semantically-tagged data from HTML.

Sources in order of confidence:
- schema.org JSON-LD blocks
- <a href="tel:...">, <a href="mailto:...">, wa.me links
- <meta> description / og:title / og:image
- <address> blocks

No regex over free text — that's the UnstructuredExtractor's job.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.schemas.crawl import ExtractedContact, FetchedPage, StructuredData

_WHATSAPP_HOSTS = ("wa.me", "api.whatsapp.com", "whatsapp.com")
_INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com")


@dataclass
class StructuredExtractor:
    """Stateless extractor. Safe to reuse across pages."""

    def extract(self, pages: list[FetchedPage]) -> StructuredData:
        data = StructuredData()
        for page in pages:
            if not page.html or page.status_code >= 400:
                continue
            soup = BeautifulSoup(page.html, "lxml")

            self._extract_schema_org(soup, data)
            self._extract_tel_mailto(soup, page.url, data)
            self._extract_social_links(soup, page.url, data)
            self._extract_contact_forms(soup, page.url, data)

            # Capture the first page's meta fields (usually home page is richest).
            if data.meta_title is None:
                data.meta_title = self._meta_content(soup, "og:title") or self._title_text(soup)
            if data.meta_description is None:
                data.meta_description = self._meta_content(
                    soup, "og:description"
                ) or self._meta_content(soup, "description")
            if data.og_image is None:
                data.og_image = self._meta_content(soup, "og:image")

            address = self._extract_address_block(soup)
            if address and address not in data.addresses:
                data.addresses.append(address)

        self._dedupe(data)
        return data

    # --- Schema.org JSON-LD ---

    def _extract_schema_org(self, soup: BeautifulSoup, data: StructuredData) -> None:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                parsed = json.loads(script.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue

            # JSON-LD can be a dict or a list at the top level.
            items: list[dict[str, Any]] = (
                parsed if isinstance(parsed, list) else [parsed]
            )
            for item in items:
                if not isinstance(item, dict):
                    continue

                # Store first schema.org block we find (richest one usually).
                if data.schema_org_data is None:
                    data.schema_org_data = item

                phone = item.get("telephone")
                if isinstance(phone, str) and phone.strip():
                    data.phones.append(
                        ExtractedContact(
                            contact_type="phone",
                            value=phone.strip(),
                            source_url=item.get("url", ""),
                            extraction_method="schema_org",
                            confidence=0.90,
                        )
                    )

                email = item.get("email")
                if isinstance(email, str) and "@" in email:
                    data.emails.append(
                        ExtractedContact(
                            contact_type="email",
                            value=email.strip(),
                            source_url=item.get("url", ""),
                            extraction_method="schema_org",
                            confidence=0.90,
                        )
                    )

                address = _format_schema_address(item.get("address"))
                if address:
                    data.addresses.append(address)

    # --- tel: / mailto: links ---

    def _extract_tel_mailto(
        self, soup: BeautifulSoup, page_url: str, data: StructuredData
    ) -> None:
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if href.startswith("tel:"):
                value = href[4:].strip()
                if value:
                    data.phones.append(
                        ExtractedContact(
                            contact_type="phone",
                            value=value,
                            source_url=page_url,
                            extraction_method="html_tel_link",
                            confidence=0.85,
                        )
                    )
            elif href.startswith("mailto:"):
                value = href[7:].split("?", 1)[0].strip()
                if "@" in value:
                    data.emails.append(
                        ExtractedContact(
                            contact_type="email",
                            value=value,
                            source_url=page_url,
                            extraction_method="html_mailto",
                            confidence=0.85,
                        )
                    )

    # --- WhatsApp / Instagram social links ---

    def _extract_social_links(
        self, soup: BeautifulSoup, page_url: str, data: StructuredData
    ) -> None:
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href.startswith(("http://", "https://")):
                continue
            host = href.split("//", 1)[1].split("/", 1)[0].lower()

            if any(host.endswith(h) for h in _WHATSAPP_HOSTS):
                data.whatsapp_links.append(
                    ExtractedContact(
                        contact_type="whatsapp",
                        value=href,
                        source_url=page_url,
                        extraction_method="whatsapp_link",
                        confidence=0.80,
                    )
                )
            elif any(host == h for h in _INSTAGRAM_HOSTS):
                data.instagram_links.append(
                    ExtractedContact(
                        contact_type="instagram",
                        value=href,
                        source_url=page_url,
                        extraction_method="instagram",
                        confidence=0.30,
                    )
                )

    # --- Contact forms ---

    def _extract_contact_forms(
        self, soup: BeautifulSoup, page_url: str, data: StructuredData
    ) -> None:
        if "/contact" not in page_url.lower() and "contact" not in page_url.lower():
            # Only count forms on contact pages to avoid login / newsletter forms.
            return
        if soup.find("form"):
            data.contact_forms.append(
                ExtractedContact(
                    contact_type="form",
                    value=page_url,
                    source_url=page_url,
                    extraction_method="contact_form",
                    confidence=0.50,
                )
            )

    # --- Address blocks ---

    def _extract_address_block(self, soup: BeautifulSoup) -> str | None:
        tag = soup.find("address")
        if isinstance(tag, Tag):
            text = tag.get_text(" ", strip=True)
            return text if len(text) >= 10 else None
        return None

    # --- Meta tags ---

    def _meta_content(self, soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if isinstance(tag, Tag):
            content = tag.get("content")
            if isinstance(content, str):
                stripped = content.strip()
                return stripped or None
        return None

    def _title_text(self, soup: BeautifulSoup) -> str | None:
        tag = soup.find("title")
        if isinstance(tag, Tag):
            text = tag.get_text(strip=True)
            return text or None
        return None

    # --- Dedupe ---

    def _dedupe(self, data: StructuredData) -> None:
        data.phones = _dedupe_contacts(data.phones, _normalize_phone)
        data.emails = _dedupe_contacts(data.emails, lambda s: s.lower().strip())
        data.whatsapp_links = _dedupe_contacts(
            data.whatsapp_links, lambda s: s.lower()
        )
        data.instagram_links = _dedupe_contacts(
            data.instagram_links, lambda s: s.lower()
        )


# --- Module-private helpers ---

_PHONE_STRIP_RE = re.compile(r"[\s\-().]+")


def _normalize_phone(raw: str) -> str:
    cleaned = _PHONE_STRIP_RE.sub("", raw)
    # Strip leading '+' for comparison, but keep digits + optional country code.
    return cleaned.lstrip("+")


def _dedupe_contacts(
    contacts: list[ExtractedContact], key_fn: Any
) -> list[ExtractedContact]:
    """Keep the highest-confidence contact per normalized key."""
    best: dict[str, ExtractedContact] = {}
    for c in contacts:
        key = key_fn(c.value)
        if key in best and best[key].confidence >= c.confidence:
            continue
        best[key] = c
    return list(best.values())


def _format_schema_address(value: Any) -> str | None:
    """schema.org PostalAddress → 'street, locality, region postal'."""
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    parts = [
        value.get("streetAddress"),
        value.get("addressLocality"),
        value.get("addressRegion"),
        value.get("postalCode"),
        value.get("addressCountry"),
    ]
    joined = ", ".join(str(p).strip() for p in parts if p)
    return joined or None
