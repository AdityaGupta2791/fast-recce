"""Unit tests for ContactService (M5)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.contact import DoNotContactCreate
from app.schemas.crawl import ExtractedContact
from app.schemas.property import PropertyUpsertFromCandidate
from app.services.contact_service import (
    ContactService,
    normalize_email,
    normalize_phone,
)
from app.services.property_service import PropertyService

pytestmark = pytest.mark.asyncio


async def _make_property(db: AsyncSession) -> uuid.UUID:
    service = PropertyService(db=db)
    prop = await service.upsert_from_candidate(
        PropertyUpsertFromCandidate(
            candidate_id=uuid.uuid4(),
            canonical_name="Sunset Villa",
            city="Alibaug",
            property_type="villa",
            google_place_id=f"place_{uuid.uuid4().hex[:8]}",
            website="https://sunset.com",
        )
    )
    return prop.id


def _ec(
    contact_type: str,
    value: str,
    method: str = "html_tel_link",
    source_url: str = "https://sunset.com/contact",
) -> ExtractedContact:
    return ExtractedContact(
        contact_type=contact_type,  # type: ignore[arg-type]
        value=value,
        source_url=source_url,
        extraction_method=method,  # type: ignore[arg-type]
        confidence=0.5,  # ignored — service re-derives confidence from method
    )


# --- normalization helpers ---


def test_normalize_phone_indian_mobile() -> None:
    assert normalize_phone("+91 98765 43210") == "919876543210"
    assert normalize_phone("9876543210") == "919876543210"
    assert normalize_phone("098765 43210") == "919876543210"
    assert normalize_phone("+1 (415) 555-1234") == "14155551234"


def test_normalize_phone_rejects_too_short_or_long() -> None:
    assert normalize_phone("12345") is None
    assert normalize_phone("1234567890123456") is None


def test_normalize_email_lowercases_and_validates() -> None:
    assert normalize_email("  Info@Sunset.COM  ") == "info@sunset.com"
    assert normalize_email("not-an-email") is None
    assert normalize_email("nope@") is None


# --- resolve_contacts ---


async def test_resolve_contacts_persists_normalized_rows(
    db_session: AsyncSession,
) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    api = [
        _ec("phone", "+919876543210", method="api_structured", source_url=""),
    ]
    crawl = [
        _ec("phone", "98765 43210", method="html_tel_link"),  # dupe of API phone
        _ec("email", "info@sunset.com", method="html_mailto"),
        _ec("whatsapp", "https://wa.me/919876543210", method="whatsapp_link"),
    ]
    result = await service.resolve_contacts(property_id, api, crawl)

    assert result.contacts_in == 4
    assert result.contacts_persisted == 3  # phone dedupe collapses 2 -> 1
    assert result.contacts_blocked_by_dnc == 0
    assert result.canonical_phone == "+919876543210"  # API phone wins
    assert result.canonical_email == "info@sunset.com"
    assert result.canonical_website == "https://sunset.com"

    contacts = await service.get_contacts_for_property(property_id)
    types = {c.contact_type for c in contacts}
    assert types == {"phone", "email", "whatsapp"}


async def test_resolve_contacts_flags_personal_email_domains(
    db_session: AsyncSession,
) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    crawl = [
        _ec("email", "owner@gmail.com", method="html_mailto"),
        _ec("email", "info@sunset.com", method="html_mailto"),
    ]
    result = await service.resolve_contacts(property_id, [], crawl)

    assert result.contacts_persisted == 2
    assert result.contacts_flagged_personal == 1
    # Business email should win as canonical even though both have same confidence.
    assert result.canonical_email == "info@sunset.com"


async def test_resolve_contacts_skips_dnc_blocked(
    db_session: AsyncSession,
) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    # Block one of the contacts upfront.
    await service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="phone",
            contact_value="+91 9876 543210",
            reason="owner asked us to stop calling",
        )
    )

    crawl = [
        _ec("phone", "+919876543210", method="html_tel_link"),
        _ec("phone", "+919999988888", method="html_tel_link"),
    ]
    result = await service.resolve_contacts(property_id, [], crawl)

    assert result.contacts_blocked_by_dnc == 1
    assert result.contacts_persisted == 1
    assert result.canonical_phone == "+919999988888"


async def test_resolve_contacts_blocks_via_email_domain_dnc(
    db_session: AsyncSession,
) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    await service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="domain",
            contact_value="blocked.com",
            reason="competitor",
        )
    )

    crawl = [
        _ec("email", "info@blocked.com", method="html_mailto"),
        _ec("email", "info@allowed.com", method="html_mailto"),
    ]
    result = await service.resolve_contacts(property_id, [], crawl)
    assert result.contacts_blocked_by_dnc == 1
    assert result.canonical_email == "info@allowed.com"


async def test_resolve_contacts_idempotent_on_re_run(db_session: AsyncSession) -> None:
    """Re-running resolution with the same inputs should not duplicate rows."""
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    crawl = [_ec("phone", "+919876543210", method="html_tel_link")]

    await service.resolve_contacts(property_id, [], crawl)
    await service.resolve_contacts(property_id, [], crawl)

    contacts = await service.get_contacts_for_property(property_id)
    assert len(contacts) == 1


async def test_resolve_contacts_promotes_higher_confidence_on_rerun(
    db_session: AsyncSession,
) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    # First run: low confidence via text regex.
    await service.resolve_contacts(
        property_id, [], [_ec("phone", "+919876543210", method="text_regex")]
    )
    # Second run: high confidence via API.
    await service.resolve_contacts(
        property_id,
        [_ec("phone", "+919876543210", method="api_structured", source_url="")],
        [],
    )

    contacts = await service.get_contacts_for_property(property_id)
    assert len(contacts) == 1
    assert contacts[0].confidence == 0.95
    assert contacts[0].extraction_method == "api_structured"


async def test_compute_contact_completeness(db_session: AsyncSession) -> None:
    property_id = await _make_property(db_session)
    service = ContactService(db=db_session, property_service=PropertyService(db_session))

    # No contacts yet but website exists from candidate payload.
    score = await service.compute_contact_completeness(property_id)
    assert score == 0.0  # has_phone/has_email both False overrides website

    await service.resolve_contacts(
        property_id,
        [],
        [
            _ec("phone", "+919876543210", method="html_tel_link"),
            _ec("email", "info@sunset.com", method="html_mailto"),
        ],
    )
    score = await service.compute_contact_completeness(property_id)
    # phone + email + website set on property → 1.0
    assert score == 1.0


async def test_add_to_dnc_is_idempotent(db_session: AsyncSession) -> None:
    service = ContactService(
        db=db_session, property_service=PropertyService(db_session)
    )
    a = await service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="phone", contact_value="+91 9876543210", reason="r1"
        )
    )
    b = await service.add_to_do_not_contact(
        DoNotContactCreate(
            contact_type="phone", contact_value="9876543210", reason="r2"
        )
    )
    assert a.id == b.id  # normalized to same key
