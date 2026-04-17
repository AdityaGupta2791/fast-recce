"""Unit tests for the MagicBricks HTML extractor.

We never hit the real network here — tests feed canned HTML into the
extraction helpers. Live scraping verification is a manual smoke step.
"""

from __future__ import annotations

import pytest

from app.integrations.magicbricks_scraper import (
    MagicBricksListing,
    _extract_from_html_fallback,
    _extract_from_ld_json,
    _extract_image_gallery,
    _parse_listing_html,
)
from bs4 import BeautifulSoup

pytestmark = pytest.mark.asyncio


# Minimal but realistic HTML — only the bits our extractor actually reads.
_REAL_LISTING_HTML = """
<html>
<head>
  <title>Buy 16,500 Sqft 8 BHK Villa for Sale in Kihim Alibag</title>
  <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": ["Product", "RealEstateListing"],
      "name": "8 BHK 16,500 Sqft Villa For Sale in Kihim, Alibag",
      "description": "A 16,500 sqft villa with pool and marble flooring...",
      "url": "https://www.magicbricks.com/propertyDetails/...",
      "image": {"@type": "ImageObject", "url": "https://img.staticmb.com/mbphoto/x.jpg"},
      "mainEntity": {
        "@type": "House",
        "address": {
          "@type": "PostalAddress",
          "addressLocality": "Kihim",
          "addressRegion": "Alibag"
        },
        "amenityFeature": [
          {"@type": "LocationFeatureSpecification", "name": "Parking", "value": "10 Open"},
          {"@type": "LocationFeatureSpecification", "name": "Flooring", "value": "Marble"}
        ]
      }
    }
  </script>
</head>
<body>
  <h1>8 BHK 16,500 Sqft Villa For Sale in Kihim, Alibag</h1>
  <img src="https://img.staticmb.com/mbphoto/property/cropped_images/2024/a.jpg">
  <img src="https://img.staticmb.com/mbphoto/property/cropped_images/2024/b.jpg">
  <img src="https://img.staticmb.com/mbphoto/property/cropped_images/2024/thumb_x.jpg">
  <img src="https://example.com/unrelated.jpg">
</body>
</html>
"""


_BLOCKED_HTML = """
<html><head><title>Access Denied</title></head>
<body><h1>Access Denied</h1><p>Just a moment...</p></body></html>
"""


_DELISTED_HTML = """<html><head><title>Oops... Something is missing</title></head><body></body></html>"""


def test_extract_from_ld_json_happy_path() -> None:
    soup = BeautifulSoup(_REAL_LISTING_HTML, "lxml")
    fields = _extract_from_ld_json(soup)
    assert fields["title"] == "8 BHK 16,500 Sqft Villa For Sale in Kihim, Alibag"
    assert fields["description"].startswith("A 16,500 sqft villa")
    assert fields["primary_image_url"] == "https://img.staticmb.com/mbphoto/x.jpg"
    assert fields["city_hint"] == "Alibag"
    assert fields["locality"] == "Kihim"
    assert fields["amenities"] == ["Parking", "Flooring"]


def test_extract_from_ld_json_returns_empty_when_missing() -> None:
    soup = BeautifulSoup("<html><body>no ld+json</body></html>", "lxml")
    assert _extract_from_ld_json(soup) == {}


def test_extract_from_html_fallback_uses_h1_then_title() -> None:
    soup = BeautifulSoup("<html><body><h1>Nice Villa</h1></body></html>", "lxml")
    assert _extract_from_html_fallback(soup)["title"] == "Nice Villa"

    soup2 = BeautifulSoup(
        "<html><head><title>Buy 4 BHK</title></head><body></body></html>", "lxml"
    )
    assert _extract_from_html_fallback(soup2)["title"] == "Buy 4 BHK"


def test_extract_from_html_fallback_ignores_delisted_title() -> None:
    """The 'Oops... Something is missing' page should NOT leak its title
    as a listing title (that's a 410-equivalent response from MB)."""
    soup = BeautifulSoup(_DELISTED_HTML, "lxml")
    assert _extract_from_html_fallback(soup) == {}


def test_extract_image_gallery_dedups_and_filters_thumbnails() -> None:
    soup = BeautifulSoup(_REAL_LISTING_HTML, "lxml")
    urls = _extract_image_gallery(soup)
    # Only 2 mb-CDN images pass the filter: 'thumb_x.jpg' is dropped, the
    # 'example.com/unrelated.jpg' one is filtered out entirely.
    assert urls == [
        "https://img.staticmb.com/mbphoto/property/cropped_images/2024/a.jpg",
        "https://img.staticmb.com/mbphoto/property/cropped_images/2024/b.jpg",
    ]


def test_parse_listing_html_returns_listing_on_happy_path() -> None:
    listing = _parse_listing_html(
        _REAL_LISTING_HTML,
        url="https://www.magicbricks.com/propertyDetails/x&id=abcdef1234",
        listing_id="abcdef1234",
    )
    assert listing is not None
    assert listing.source == "magicbricks"
    assert listing.listing_id == "abcdef1234"
    assert listing.title.startswith("8 BHK")
    assert listing.city_hint == "Alibag"
    assert listing.locality == "Kihim"
    assert listing.primary_image_url  # populated from either ld+json or gallery
    assert len(listing.image_urls) == 2


def test_parse_listing_html_returns_none_when_no_title() -> None:
    """If both ld+json and the HTML fallback fail to surface a title, we
    skip the row (better than persisting a placeholder)."""
    html = "<html><body>no title, no json</body></html>"
    assert _parse_listing_html(html, url="u", listing_id="id") is None


def test_magicbricks_listing_dataclass_defaults_source() -> None:
    listing = MagicBricksListing(
        listing_id="id123",
        url="https://www.magicbricks.com/propertyDetails/x&id=id123",
        title="Some Villa",
    )
    assert listing.source == "magicbricks"
    # Inherited ExternalListing defaults.
    assert listing.image_urls == []
    assert listing.phone is None
