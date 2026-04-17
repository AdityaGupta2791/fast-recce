"""Unit tests for the Airbnb JSON extractor.

We intentionally do NOT launch a real browser here — those are manual
smoke tests. Instead we feed the extractor canned JSON and assert it
surfaces the right fields. That's the part most likely to regress when
Airbnb changes their embed structure.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.airbnb_scraper import (
    AirbnbListing,
    _extract_fields,
    _extract_image_gallery,
    _extract_json_blob,
    _first_list_of_strings,
    _first_non_empty_str,
    _is_airbnb_error_payload,
    _search_any_key,
)

pytestmark = pytest.mark.asyncio


# Realistic snippet of what Airbnb's embedded JSON *roughly* looks like.
_FAKE_LISTING_JSON = {
    "props": {
        "pageProps": {
            "listing": {
                "name": "Sunset Heritage Villa",
                "description": "A colonial villa overlooking the Arabian Sea, "
                               "with open lawns and a rooftop terrace.",
                "amenities": [
                    {"name": "WiFi"},
                    {"name": "Kitchen"},
                    {"name": "Free parking"},
                    "Pool",
                ],
                "primaryHost": {"firstName": "Aditya"},
                "city": "Alibaug",
                "neighborhood": "Nagaon Beach",
                "photos": [{"xLarge": "https://cdn.example/photo1.jpg"}],
            }
        }
    }
}


def test_extract_fields_happy_path() -> None:
    fields = _extract_fields(_FAKE_LISTING_JSON)
    assert fields["title"] == "Sunset Heritage Villa"
    assert "colonial villa" in fields["description"]
    assert fields["amenities"] == ["WiFi", "Kitchen", "Free parking", "Pool"]
    assert fields["host_first_name"] == "Aditya"
    assert fields["city_hint"] == "Alibaug"
    assert fields["neighborhood"] == "Nagaon Beach"
    assert fields["primary_image_url"] == "https://cdn.example/photo1.jpg"


def test_extract_fields_returns_placeholder_when_all_paths_miss() -> None:
    """Unknown layout → title falls back to a placeholder, NOT a random
    deep-tree "name" hit. The DFS fallback was dropped because Airbnb's
    error payloads contain GraphQL type names like "NiobeError" under
    `name`, which used to leak through as fake titles."""
    data = {"totally": {"different": {"shape": {"name": "NiobeError"}}}}
    fields = _extract_fields(data)
    # Placeholder, not the random "name" found via DFS.
    assert fields["title"] == "Airbnb Listing"


def test_extract_fields_default_title_when_no_hint() -> None:
    data = {"no": "useful data here"}
    fields = _extract_fields(data)
    assert fields["title"] == "Airbnb Listing"


def test_first_non_empty_str_prefers_first_match() -> None:
    data = {"a": {"b": ""}, "c": "winner"}
    value = _first_non_empty_str(
        data,
        (("a", "b"), ("c",)),
    )
    assert value == "winner"


def test_first_list_of_strings_normalizes_dicts() -> None:
    data = {"amenities": [{"name": "Pool"}, {"title": "Lawn"}, "Terrace"]}
    out = _first_list_of_strings(data, (("amenities",),))
    assert out == ["Pool", "Lawn", "Terrace"]


def test_first_list_of_strings_returns_none_on_miss() -> None:
    assert _first_list_of_strings({}, (("nope",),)) is None


def test_search_any_key_handles_mixed_types() -> None:
    data = [{"outer": {"inner": {"name": "Found me"}}}]
    assert _search_any_key(data, "name") == "Found me"


def test_search_any_key_respects_max_depth() -> None:
    deep = {"a": {"b": {"c": {"d": {"e": {"name": "too deep"}}}}}}
    assert _search_any_key(deep, "name", max_depth=3) is None


def test_extract_json_blob_matches_deferred_state() -> None:
    blob = json.dumps({"hello": "world"})
    html = f'<html><body><script id="data-deferred-state-0">{blob}</script></body></html>'
    assert _extract_json_blob(html) == blob


def test_extract_json_blob_matches_next_data() -> None:
    blob = json.dumps({"hello": "world"})
    html = (
        f'<html><head>'
        f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'
        f'</head></html>'
    )
    assert _extract_json_blob(html) == blob


def test_extract_json_blob_returns_none_when_missing() -> None:
    html = "<html><body>No JSON here</body></html>"
    assert _extract_json_blob(html) is None


def test_airbnb_listing_dataclass_shape() -> None:
    listing = AirbnbListing(
        listing_id="12345",
        url="https://www.airbnb.com/rooms/12345",
        title="Sunset Villa",
    )
    # Defaults are preserved.
    assert listing.description is None
    assert listing.amenities == []
    assert listing.image_urls == []
    assert listing.raw_top_keys == []


def test_extract_image_gallery_pulls_dedup_capped_urls() -> None:
    """Walks niobeClientData → sections.sections → HERO_DEFAULT/PHOTO_TOUR_*
    and returns deduped baseUrls in order, capped at max_images."""
    blob = {
        "niobeClientData": [
            ["StaysPdpSections:irrelevant", {
                "data": {
                    "presentation": {
                        "stayProductDetailPage": {
                            "sections": {
                                "sections": [
                                    {
                                        "sectionComponentType": "HERO_DEFAULT",
                                        "section": {
                                            "previewImages": [
                                                {"baseUrl": "https://cdn/a.jpg"},
                                                {"baseUrl": "https://cdn/b.jpg"},
                                                {"baseUrl": "https://cdn/a.jpg"},  # dup → drop
                                            ],
                                        },
                                    },
                                    {
                                        "sectionComponentType": "PHOTO_TOUR_SCROLLABLE",
                                        "section": {
                                            "mediaItems": [
                                                {"baseUrl": "https://cdn/c.jpg"},
                                                {"baseUrl": "https://cdn/d.jpg"},
                                            ],
                                        },
                                    },
                                    {
                                        # Wrong section type → ignored.
                                        "sectionComponentType": "AMENITIES_DEFAULT",
                                        "section": {
                                            "mediaItems": [
                                                {"baseUrl": "https://cdn/skip.jpg"},
                                            ],
                                        },
                                    },
                                ]
                            }
                        }
                    }
                }
            }]
        ]
    }

    urls = _extract_image_gallery(blob, max_images=10)
    assert urls == [
        "https://cdn/a.jpg",
        "https://cdn/b.jpg",
        "https://cdn/c.jpg",
        "https://cdn/d.jpg",
    ]


def test_extract_image_gallery_returns_empty_when_no_niobe() -> None:
    assert _extract_image_gallery({"unrelated": "shape"}) == []
    assert _extract_image_gallery({"niobeClientData": []}) == []
    assert _extract_image_gallery("not even a dict") == []


def test_is_airbnb_error_payload_detects_errordata() -> None:
    """Delisted / private listings come back as 200 OK with errorData set
    and sharingConfig=None. We must skip these to avoid persisting them
    as 'NiobeError'-titled garbage rows."""
    blob = {
        "niobeClientData": [
            ["StaysPdpSections:irrelevant", {
                "data": {
                    "presentation": {
                        "stayProductDetailPage": {
                            "sections": {
                                "sections": [],
                                "metadata": {
                                    "sharingConfig": None,
                                    "errorData": {
                                        "errorMessage": {
                                            "errorTitle": "Internal error",
                                        },
                                        "redirectUrl": "https://airbnb.co.in/404",
                                    },
                                },
                            }
                        }
                    }
                }
            }]
        ]
    }
    assert _is_airbnb_error_payload(blob) is True


def test_is_airbnb_error_payload_returns_false_for_real_listing() -> None:
    blob = {
        "niobeClientData": [
            ["StaysPdpSections:real", {
                "data": {
                    "presentation": {
                        "stayProductDetailPage": {
                            "sections": {
                                "sections": [{"sectionComponentType": "HERO_DEFAULT"}],
                                "metadata": {
                                    "sharingConfig": {"title": "Real villa"},
                                    "errorData": None,
                                },
                            }
                        }
                    }
                }
            }]
        ]
    }
    assert _is_airbnb_error_payload(blob) is False


def test_is_airbnb_error_payload_returns_false_for_unknown_shape() -> None:
    # Empty / unrelated shapes shouldn't trigger the error guard — the
    # caller treats False as "proceed with extraction".
    assert _is_airbnb_error_payload({}) is False
    assert _is_airbnb_error_payload({"niobeClientData": []}) is False
    assert _is_airbnb_error_payload("not a dict") is False
