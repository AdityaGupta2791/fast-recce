"""Unit tests for the three extractors (structured, unstructured, media)."""

from __future__ import annotations

import hashlib
import textwrap

from app.schemas.crawl import FetchedPage
from app.services.extractors.media import MediaExtractor
from app.services.extractors.structured import StructuredExtractor
from app.services.extractors.unstructured import UnstructuredExtractor


def _page(url: str, html: str, page_type: str = "home", status: int = 200) -> FetchedPage:
    return FetchedPage(
        url=url,
        page_type=page_type,  # type: ignore[arg-type]
        status_code=status,
        html=html,
        content_hash=hashlib.sha256(html.encode()).hexdigest(),
        fetched_at="2026-04-14T00:00:00+00:00",
    )


# --- StructuredExtractor ---


def test_structured_extracts_schema_org_and_tel_mailto() -> None:
    html = textwrap.dedent(
        """
        <html><head>
          <meta property="og:title" content="Sunset Villa">
          <meta name="description" content="A premium villa in Alibaug.">
          <meta property="og:image" content="https://cdn.example.com/cover.jpg">
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Hotel",
            "name": "Sunset Villa",
            "telephone": "+91 9876543210",
            "email": "info@sunsetvilla.com",
            "address": {
              "@type": "PostalAddress",
              "streetAddress": "Nagaon Beach Road",
              "addressLocality": "Alibaug",
              "addressRegion": "Maharashtra",
              "postalCode": "402201"
            }
          }
          </script>
        </head><body>
          <a href="tel:+919999888877">Call us</a>
          <a href="mailto:bookings@sunsetvilla.com">Book now</a>
          <a href="https://wa.me/919876543210">WhatsApp us</a>
          <a href="https://www.instagram.com/sunsetvilla">Instagram</a>
          <address>Nagaon Beach Road, Alibaug 402201</address>
        </body></html>
        """
    )
    data = StructuredExtractor().extract([_page("https://sunset.com/", html)])

    phones = {p.value for p in data.phones}
    assert "+91 9876543210" in phones
    assert "+919999888877" in phones

    emails = {e.value for e in data.emails}
    assert "info@sunsetvilla.com" in emails
    assert "bookings@sunsetvilla.com" in emails

    assert any("wa.me" in w.value for w in data.whatsapp_links)
    assert any("instagram.com" in i.value for i in data.instagram_links)
    assert data.meta_title == "Sunset Villa"
    assert data.meta_description == "A premium villa in Alibaug."
    assert data.og_image == "https://cdn.example.com/cover.jpg"
    assert data.schema_org_data is not None
    assert any("Alibaug" in a for a in data.addresses)


def test_structured_dedupes_same_phone_across_pages() -> None:
    tel_html = '<a href="tel:+91 98765 43210">Call</a>'
    ext = StructuredExtractor()
    data = ext.extract(
        [
            _page("https://a.com/", tel_html),
            _page("https://a.com/contact", tel_html, page_type="contact"),
        ]
    )
    # Phone appears on both pages but normalized to same key.
    assert len(data.phones) == 1


def test_structured_ignores_mailformed_json_ld() -> None:
    html = '<script type="application/ld+json">{"telephone":</script>'
    data = StructuredExtractor().extract([_page("https://x.com/", html)])
    assert data.phones == []
    assert data.schema_org_data is None


def test_structured_finds_contact_form_only_on_contact_page() -> None:
    home_html = "<html><body><form><input></form></body></html>"
    contact_html = "<html><body><form><input></form></body></html>"
    ext = StructuredExtractor()

    home_only = ext.extract([_page("https://a.com/", home_html)])
    assert home_only.contact_forms == []

    with_contact = ext.extract(
        [_page("https://a.com/contact", contact_html, page_type="contact")]
    )
    assert len(with_contact.contact_forms) == 1


# --- UnstructuredExtractor ---


def test_unstructured_extracts_amenities_and_feature_tags() -> None:
    html = """
    <html><body>
      <p>Our heritage villa in Alibaug offers a pool, spacious lawn,
      rooftop terrace, and parking. Perfect for photoshoots, film shoots,
      and outdoor events.</p>
    </body></html>
    """
    data = UnstructuredExtractor().extract([_page("https://v.com/", html)])

    assert "pool" in data.amenities
    assert "lawn" in data.amenities
    assert "terrace" in data.amenities
    assert "parking" in data.amenities

    assert "heritage" in data.feature_tags
    assert "film_friendly" in data.feature_tags
    assert "events" in data.feature_tags
    assert "outdoor" in data.feature_tags


def test_unstructured_picks_description_from_about_page() -> None:
    home = _page(
        "https://v.com/",
        "<html><body><h1>Welcome</h1></body></html>",
    )
    about_html = """
    <html><body>
      <p>Nestled along the coast of Alibaug, Sunset Villa offers a peaceful
      retreat with sweeping ocean views, private lawns, and a rooftop terrace
      ideal for filmmakers and photographers. Built in 1924, the heritage
      property has hosted countless brand shoots and destination weddings.</p>
    </body></html>
    """
    about = _page("https://v.com/about", about_html, page_type="about")

    data = UnstructuredExtractor().extract([home, about])
    assert data.description is not None
    assert "Alibaug" in data.description


def test_unstructured_finds_text_contacts_only_when_phone_plausible() -> None:
    html = """
    <html><body>
      <p>Call 9876543210 or email info@villa.com. Also try 12-34 which isn't a phone.</p>
    </body></html>
    """
    data = UnstructuredExtractor().extract([_page("https://v.com/", html)])

    phones = [c for c in data.text_contacts if c.contact_type == "phone"]
    emails = [c for c in data.text_contacts if c.contact_type == "email"]
    assert any("9876543210" in p.value for p in phones)
    assert any("info@villa.com" in e.value for e in emails)
    # '12-34' should not qualify
    assert not any(c.value.strip() == "12-34" for c in data.text_contacts)


# --- MediaExtractor ---


def test_media_extracts_images_and_skips_icons() -> None:
    html = """
    <html><body>
      <img src="/images/villa-exterior.jpg" alt="Villa exterior" width="800" height="600">
      <img src="/images/logo.png" alt="logo" width="100" height="40">
      <img src="https://cdn.example.com/pool.jpg" alt="Pool view">
      <img src="/favicon.ico">
      <img src="/images/social-icon.png" width="30" height="30">
    </body></html>
    """
    items = MediaExtractor().extract([_page("https://v.com/", html)])
    urls = {item.media_url for item in items}

    assert "https://v.com/images/villa-exterior.jpg" in urls
    assert "https://cdn.example.com/pool.jpg" in urls
    assert not any("logo" in u for u in urls)
    assert not any("favicon" in u for u in urls)
    assert not any("social" in u for u in urls)


def test_media_falls_back_to_og_image_when_few_inline() -> None:
    html = """
    <html><head>
      <meta property="og:image" content="https://cdn.example.com/hero.jpg">
    </head><body>
      <img src="/images/logo.png" alt="logo" width="100" height="40">
    </body></html>
    """
    items = MediaExtractor().extract([_page("https://v.com/", html)])
    urls = {item.media_url for item in items}
    assert "https://cdn.example.com/hero.jpg" in urls


def test_media_dedupes_across_pages() -> None:
    html_home = '<img src="https://cdn.example.com/pool.jpg" alt="Pool">'
    html_rooms = '<img src="https://cdn.example.com/pool.jpg" alt="Pool view">'
    items = MediaExtractor().extract(
        [
            _page("https://v.com/", html_home),
            _page("https://v.com/rooms", html_rooms, page_type="rooms"),
        ]
    )
    urls = [item.media_url for item in items]
    assert urls.count("https://cdn.example.com/pool.jpg") == 1
