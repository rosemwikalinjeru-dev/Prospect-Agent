"""Deduplicates raw Places results and normalizes phone numbers."""

import phonenumbers
from loguru import logger

from prospecting_agent.models import CleanedLead, RawBusiness


def normalize_phone(phone: str | None) -> str | None:
    """Return E.164 format (e.g. +14155551234), or None if missing/unparseable."""
    if not phone:
        return None
    try:
        parsed = phonenumbers.parse(phone, "US")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def clean_businesses(raw_businesses: list[RawBusiness]) -> list[CleanedLead]:
    """Dedupe by place_id first (the same business surfaces under multiple search
    keywords), then by normalized phone (the same business can have multiple place_ids
    for different listings, e.g. a service-area business with no storefront).
    """
    seen_place_ids: set[str] = set()
    seen_phones: set[str] = set()
    cleaned: list[CleanedLead] = []

    for business in raw_businesses:
        if business.place_id in seen_place_ids:
            continue

        normalized_phone = normalize_phone(business.phone)
        if normalized_phone and normalized_phone in seen_phones:
            continue

        seen_place_ids.add(business.place_id)
        if normalized_phone:
            seen_phones.add(normalized_phone)

        cleaned.append(CleanedLead(**business.model_dump(), normalized_phone=normalized_phone))

    logger.info(f"Cleaned {len(raw_businesses)} raw results down to {len(cleaned)} unique leads")
    return cleaned
