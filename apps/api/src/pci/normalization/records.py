from collections.abc import Callable
from datetime import date, datetime
from typing import Any, cast

from pci.ingestion.contracts import HarvestedRecord
from pci.models.enums import ProductionType
from pci.normalization.contracts import NormalizedAuthor, NormalizedRecord
from pci.normalization.identifiers import (
    classify_identifier,
    normalize_doi,
    normalize_handle,
    normalize_isbn,
    normalize_orcid,
    normalize_patent,
    normalize_url,
    string_values,
)
from pci.normalization.text import normalize_display

Transformation = dict[str, object]
IdentifierNormalizer = Callable[[str], str | None]


def normalize_record(raw: HarvestedRecord) -> NormalizedRecord:
    payload = raw.payload
    transformations: list[Transformation] = []
    title = _text_field(payload.get("title"), "title", transformations)
    abstract = _text_field(payload.get("abstract"), "abstract", transformations)

    publication_date, publication_year = _publication_date(payload, transformations)
    language = _text_field(payload.get("language"), "language", transformations)
    if language is not None:
        normalized_language = language.casefold()
        _record_change(transformations, "language", language, normalized_language)
        language = normalized_language
    production_type = _production_type(payload.get("type"), transformations)
    authors = _authors(payload.get("authors", payload.get("creator")), transformations)
    organizations = _organizations(
        payload.get("institution", payload.get("organization")), transformations
    )
    keywords = _keywords(payload.get("keywords", payload.get("subject")), transformations)
    publishers = _publishers(payload.get("publisher"), transformations)
    identifiers = _identifiers(payload, transformations)

    source_identifier = normalize_display(raw.source_identifier)
    _record_change(transformations, "source_identifier", raw.source_identifier, source_identifier)
    identifiers["source"] = source_identifier

    source_url = None
    if raw.source_url is not None:
        source_url = normalize_url(raw.source_url)
        _record_change(transformations, "source_url", raw.source_url, source_url)
        if source_url is not None:
            existing_url = identifiers.get("url")
            if existing_url is None:
                identifiers["url"] = source_url
            elif existing_url != source_url:
                transformations.append(
                    {
                        "field": "source_url.identifier",
                        "original": raw.source_url,
                        "normalized": source_url,
                        "retained": existing_url,
                        "reason": "duplicate_discarded",
                    }
                )

    missing_fields = tuple(
        name
        for name, value in (
            ("title", title),
            ("abstract", abstract),
            ("publication_date", publication_year),
            ("language", language),
            ("type", production_type),
            ("authors", authors),
            ("organizations", organizations),
            ("keywords", keywords),
            ("source_url", source_url),
            ("rights", raw.rights),
        )
        if value is None or value == ()
    )

    report: dict[str, Any] = {
        "transformations": transformations,
        "missing_fields": list(missing_fields),
    }
    return NormalizedRecord(
        source_identifier=source_identifier,
        title=title,
        abstract=abstract,
        publication_date=publication_date,
        publication_year=publication_year,
        language=language,
        type=production_type,
        identifiers=identifiers,
        authors=authors,
        organizations=organizations,
        keywords=keywords,
        publishers=publishers,
        source_url=source_url,
        rights=raw.rights,
        full_text_available=raw.full_text is not None,
        missing_fields=missing_fields,
        normalization_report=report,
    )


def _text_field(value: object, field: str, transformations: list[Transformation]) -> str | None:
    original, discarded = _first_scalar_string(value)
    if original is None:
        return None
    normalized = normalize_display(original)
    result = normalized or None
    _record_change(transformations, field, original, result)
    for index, discarded_value in discarded:
        _record_scalar_discard(
            transformations,
            field,
            index,
            discarded_value,
            normalize_display(discarded_value) or None,
            result,
        )
    return result


def _first_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, str)), None)
    return None


def _first_scalar_string(value: object) -> tuple[str | None, list[tuple[int, str]]]:
    if isinstance(value, str):
        return value, []
    if not isinstance(value, list):
        return None, []
    values = [(index, item) for index, item in enumerate(value) if isinstance(item, str)]
    if not values:
        return None, []
    _, first = values[0]
    return first, values[1:]


def _record_scalar_discard(
    transformations: list[Transformation],
    field: str,
    index: int,
    original: str,
    normalized: object,
    retained: object,
) -> None:
    transformations.append(
        {
            "field": f"{field}[{index}]",
            "original": original,
            "normalized": normalized,
            "retained": retained,
            "reason": "multiple_values_discarded",
        }
    )


def _publication_date(
    payload: dict[str, Any], transformations: list[Transformation]
) -> tuple[date | None, int | None]:
    field, raw_value = next(
        (
            (candidate, payload[candidate])
            for candidate in ("publication_date", "date", "year")
            if candidate in payload
        ),
        ("publication_date", None),
    )
    original, discarded = _first_scalar_string(raw_value)
    if original is None and isinstance(raw_value, int):
        original = str(raw_value)
    if original is None:
        return None, None
    cleaned = normalize_display(original)
    try:
        if len(cleaned) == 4:
            year = int(cleaned)
            parsed = None
        else:
            parsed = datetime.fromisoformat(cleaned).date()
            year = parsed.year
    except (ValueError, OverflowError):
        _record_change(transformations, field, original, None)
        for index, discarded_value in discarded:
            _record_scalar_discard(
                transformations,
                field,
                index,
                discarded_value,
                normalize_display(discarded_value) or None,
                None,
            )
        return None, None
    normalized = str(year) if parsed is None else parsed.isoformat()
    _record_change(transformations, field, original, normalized)
    for index, discarded_value in discarded:
        _record_scalar_discard(
            transformations,
            field,
            index,
            discarded_value,
            normalize_display(discarded_value) or None,
            normalized,
        )
    return parsed, year


def _production_type(value: object, transformations: list[Transformation]) -> ProductionType | None:
    original, discarded = _first_scalar_string(value)
    if original is None:
        return None
    normalized = normalize_display(original).casefold().replace("-", "_").replace(" ", "_")
    try:
        result = ProductionType(normalized)
    except ValueError:
        _record_change(transformations, "type", original, None)
        for index, discarded_value in discarded:
            _record_scalar_discard(
                transformations,
                "type",
                index,
                discarded_value,
                normalize_display(discarded_value) or None,
                None,
            )
        return None
    _record_change(transformations, "type", original, result.value)
    for index, discarded_value in discarded:
        _record_scalar_discard(
            transformations,
            "type",
            index,
            discarded_value,
            normalize_display(discarded_value).casefold().replace("-", "_").replace(" ", "_")
            or None,
            result.value,
        )
    return result


def _authors(value: object, transformations: list[Transformation]) -> tuple[NormalizedAuthor, ...]:
    raw_authors: list[object]
    if isinstance(value, list):
        raw_authors = value
    elif value is None:
        raw_authors = []
    else:
        raw_authors = [value]
    result: list[NormalizedAuthor] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for index, raw_author in enumerate(raw_authors):
        original_name: str | None
        raw_orcid: str | None
        raw_organization: str | None
        if isinstance(raw_author, str):
            original_name = raw_author
            raw_orcid = None
            raw_organization = None
        elif isinstance(raw_author, dict):
            author = cast(dict[object, object], raw_author)
            original_name = _first_string(author.get("name"))
            raw_orcid = _first_string(author.get("orcid"))
            raw_organization = _first_string(author.get("organization", author.get("institution")))
        else:
            continue
        if original_name is None or not (name := normalize_display(original_name)):
            continue
        _record_change(transformations, f"authors[{index}].name", original_name, name)
        orcid = normalize_orcid(raw_orcid) if raw_orcid is not None else None
        if raw_orcid is not None:
            _record_change(transformations, f"authors[{index}].orcid", raw_orcid, orcid)
        organization = normalize_display(raw_organization) if raw_organization is not None else None
        if raw_organization is not None:
            _record_change(
                transformations,
                f"authors[{index}].organization",
                raw_organization,
                organization,
            )
        identity = (name.casefold(), orcid, organization.casefold() if organization else None)
        if identity in seen:
            transformations.append(
                {
                    "field": f"authors[{index}]",
                    "original": raw_author,
                    "normalized": {
                        "name": name,
                        "orcid": orcid,
                        "organization": organization,
                    },
                    "reason": "duplicate_discarded",
                }
            )
            continue
        seen.add(identity)
        result.append(NormalizedAuthor(name=name, orcid=orcid, organization=organization))
    return tuple(result)


def _organizations(value: object, transformations: list[Transformation]) -> tuple[str, ...]:
    return _normalized_string_tuple(value, "organizations", transformations)


def _keywords(value: object, transformations: list[Transformation]) -> tuple[str, ...]:
    return _normalized_string_tuple(value, "keywords", transformations)


def _publishers(value: object, transformations: list[Transformation]) -> tuple[str, ...]:
    return _normalized_string_tuple(value, "publishers", transformations)


def _normalized_string_tuple(
    value: object, field: str, transformations: list[Transformation]
) -> tuple[str, ...]:
    values = list(string_values(value))
    result: list[str] = []
    seen: set[str] = set()
    for index, original in enumerate(values):
        normalized = normalize_display(original)
        _record_change(transformations, f"{field}[{index}]", original, normalized or None)
        key = normalized.casefold()
        if not normalized:
            continue
        if key in seen:
            transformations.append(
                {
                    "field": f"{field}[{index}]",
                    "original": original,
                    "normalized": normalized,
                    "reason": "duplicate_discarded",
                }
            )
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _identifiers(payload: dict[str, Any], transformations: list[Transformation]) -> dict[str, str]:
    result: dict[str, str] = {}
    direct: tuple[tuple[str, tuple[str, ...], IdentifierNormalizer], ...] = (
        ("doi", ("doi",), normalize_doi),
        ("orcid", ("orcid",), normalize_orcid),
        ("isbn", ("isbn",), normalize_isbn),
        ("patent", ("patent_number", "patent"), normalize_patent),
        ("handle", ("repository_handle", "handle"), normalize_handle),
        ("url", ("url",), normalize_url),
    )
    for canonical_key, aliases, normalizer in direct:
        for alias in aliases:
            raw_value = payload.get(alias)
            values: list[tuple[int | None, str]]
            if isinstance(raw_value, str):
                values = [(None, raw_value)]
            elif isinstance(raw_value, list):
                values = [
                    (index, item) for index, item in enumerate(raw_value) if isinstance(item, str)
                ]
            else:
                values = []
            for index, original in values:
                normalized = normalizer(original)
                existing = result.get(canonical_key)
                field = canonical_key if index is None else f"{alias}[{index}]"
                if normalized is None:
                    _record_change(transformations, field, original, None)
                    continue
                if existing is None:
                    result[canonical_key] = normalized
                    _record_change(transformations, canonical_key, original, normalized)
                    continue
                transformations.append(
                    {
                        "field": field,
                        "source_field": alias,
                        "original": original,
                        "normalized": normalized,
                        "retained": existing,
                        "reason": (
                            "multiple_values_discarded"
                            if index is not None
                            else "duplicate_discarded"
                        ),
                    }
                )

    generic = payload.get("identifiers", payload.get("identifier"))
    for index, original in enumerate(string_values(generic)):
        classified = classify_identifier(original)
        if classified is None:
            if normalize_display(original).casefold().startswith(("http://", "https://")):
                _record_change(transformations, f"identifiers[{index}].url", original, None)
            continue
        key, normalized = classified
        existing = result.get(key)
        if existing is None:
            result[key] = normalized
            _record_change(transformations, f"identifiers[{index}].{key}", original, normalized)
        else:
            transformations.append(
                {
                    "field": f"identifiers[{index}].{key}",
                    "original": original,
                    "normalized": normalized,
                    "retained": existing,
                    "reason": "duplicate_discarded",
                }
            )
    return result


def _record_change(
    transformations: list[Transformation], field: str, original: object, normalized: object
) -> None:
    if original != normalized:
        transformations.append({"field": field, "original": original, "normalized": normalized})
