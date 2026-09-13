from copy import deepcopy

import pytest

from pci.ingestion.contracts import HarvestedRecord
from pci.normalization.records import normalize_record


def harvested_record(**payload: object) -> HarvestedRecord:
    return HarvestedRecord(
        source_identifier="oai:repository.example:42",
        payload=dict(payload),
        source_url=" HTTPS://Repository.Example:443/items/42/ ",
        rights="metadata-only",
    )


def test_normalize_record_preserves_display_text_and_reports_every_change() -> None:
    raw = harvested_record(
        title="  A\u0301gua\u00a0e   inovação  ",
        doi="HTTPS://DOI.ORG/10.1000/ABC",
    )

    normalized = normalize_record(raw)

    assert normalized.title == "Água e inovação"
    assert normalized.identifiers == {
        "doi": "10.1000/abc",
        "source": "oai:repository.example:42",
        "url": "https://repository.example/items/42",
    }
    assert normalized.missing_fields == (
        "abstract",
        "publication_date",
        "language",
        "type",
        "authors",
        "organizations",
        "keywords",
    )
    assert normalized.normalization_report == {
        "transformations": [
            {
                "field": "title",
                "original": "  A\u0301gua\u00a0e   inovação  ",
                "normalized": "Água e inovação",
            },
            {
                "field": "doi",
                "original": "HTTPS://DOI.ORG/10.1000/ABC",
                "normalized": "10.1000/abc",
            },
            {
                "field": "source_url",
                "original": " HTTPS://Repository.Example:443/items/42/ ",
                "normalized": "https://repository.example/items/42",
            },
        ],
        "missing_fields": [
            "abstract",
            "publication_date",
            "language",
            "type",
            "authors",
            "organizations",
            "keywords",
        ],
    }


def test_normalize_record_cleans_all_supported_identifier_kinds() -> None:
    normalized = normalize_record(
        harvested_record(
            title="Identifiers",
            abstract="Present",
            identifiers=[
                "doi:10.5555/ABC.DEF",
                "https://orcid.org/0000-0002-1825-0097",
                "ISBN 978-85-333-0227-3",
                "https://hdl.handle.net/12345/ABC",
            ],
            patent_number=" BR 10 2022 001234-5 ",
        )
    )

    assert normalized.identifiers == {
        "doi": "10.5555/abc.def",
        "orcid": "0000-0002-1825-0097",
        "isbn": "9788533302273",
        "patent": "BR1020220012345",
        "handle": "12345/abc",
        "source": "oai:repository.example:42",
        "url": "https://repository.example/items/42",
    }


def test_normalize_record_is_deterministic_and_does_not_mutate_harvested_payload() -> None:
    raw = harvested_record(
        title="  Deterministic  ",
        abstract="  Same\n value ",
        authors=[{"name": "  Joana\u00a0Silva ", "orcid": "0000 0001 2345 678X"}],
        institution=["  UFPE ", "UFPE"],
        date="2024-07-05",
        keywords=[" ciência  aberta ", "ciência aberta", "Dados"],
    )
    before = deepcopy(raw.payload)

    first = normalize_record(raw)
    second = normalize_record(raw)

    assert first == second
    assert raw.payload == before
    assert first.publication_date is not None
    assert first.publication_date.isoformat() == "2024-07-05"
    assert first.publication_year == 2024
    assert first.authors[0].name == "Joana Silva"
    assert first.authors[0].orcid == "0000-0001-2345-678X"
    assert first.organizations == ("UFPE",)
    assert first.keywords == ("ciência aberta", "Dados")


def test_normalize_record_records_missing_title_without_inventing_one() -> None:
    normalized = normalize_record(harvested_record(abstract="Only an abstract"))

    assert normalized.title is None
    assert normalized.missing_fields == (
        "title",
        "publication_date",
        "language",
        "type",
        "authors",
        "organizations",
        "keywords",
    )
    assert normalized.normalization_report["missing_fields"] == [
        "title",
        "publication_date",
        "language",
        "type",
        "authors",
        "organizations",
        "keywords",
    ]


def test_generic_repository_url_stays_a_url_instead_of_becoming_a_handle() -> None:
    normalized = normalize_record(
        harvested_record(
            title="Repository URL",
            abstract="Present",
            identifiers=["https://repository.example/items/42"],
        )
    )

    assert normalized.identifiers["url"] == "https://repository.example/items/42"
    assert "handle" not in normalized.identifiers


def test_normalize_record_records_discarded_duplicate_keywords() -> None:
    normalized = normalize_record(
        harvested_record(
            title="Keywords",
            abstract="Present",
            keywords=["Dados abertos", " dados abertos "],
        )
    )

    assert normalized.keywords == ("Dados abertos",)
    assert {
        "field": "keywords[1]",
        "original": " dados abertos ",
        "normalized": "dados abertos",
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]


def test_normalize_record_reports_discarded_authors_and_identifiers() -> None:
    raw = harvested_record(
        title="Discard report",
        abstract="Present",
        doi="10.1000/direct",
        authors=["Ana Silva", "Ana Silva"],
        identifiers=[
            "https://doi.org/10.1000/generic",
            "https://repository.example/one",
            "https://repository.example/two",
        ],
    )

    normalized = normalize_record(raw)

    assert [author.name for author in normalized.authors] == ["Ana Silva"]
    assert normalized.identifiers["doi"] == "10.1000/direct"
    assert normalized.identifiers["url"] == "https://repository.example/one"
    assert {
        "field": "authors[1]",
        "original": "Ana Silva",
        "normalized": {"name": "Ana Silva", "orcid": None, "organization": None},
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]
    assert {
        "field": "identifiers[0].doi",
        "original": "https://doi.org/10.1000/generic",
        "normalized": "10.1000/generic",
        "retained": "10.1000/direct",
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]
    assert {
        "field": "identifiers[2].url",
        "original": "https://repository.example/two",
        "normalized": "https://repository.example/two",
        "retained": "https://repository.example/one",
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]
    assert {
        "field": "source_url.identifier",
        "original": " HTTPS://Repository.Example:443/items/42/ ",
        "normalized": "https://repository.example/items/42",
        "retained": "https://repository.example/one",
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]
    assert normalize_record(raw) == normalized


@pytest.mark.parametrize(
    ("payload", "identifier_key", "retained", "alternate_alias", "alternate"),
    [
        (
            {"patent_number": "BR 10 2022 001234-5", "patent": "US 123/456"},
            "patent",
            "BR1020220012345",
            "patent",
            "US123456",
        ),
        (
            {"repository_handle": "12345/first", "handle": "12345/second"},
            "handle",
            "12345/first",
            "handle",
            "12345/second",
        ),
    ],
)
def test_normalize_record_reports_discarded_direct_identifier_aliases(
    payload: dict[str, str],
    identifier_key: str,
    retained: str,
    alternate_alias: str,
    alternate: str,
) -> None:
    normalized = normalize_record(
        harvested_record(title="Direct aliases", abstract="Present", **payload)
    )

    assert normalized.identifiers[identifier_key] == retained
    assert {
        "field": identifier_key,
        "source_field": alternate_alias,
        "original": payload[alternate_alias],
        "normalized": alternate,
        "retained": retained,
        "reason": "duplicate_discarded",
    } in normalized.normalization_report["transformations"]


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("HTTP://Example.COM:80/a/", "http://example.com/a"),
        (
            "https://Example.COM:8443/A?q=Two Words#fragment",
            "https://example.com:8443/A?q=Two%20Words",
        ),
    ],
)
def test_normalize_record_normalizes_urls_without_lowercasing_paths(
    raw_url: str, expected: str
) -> None:
    raw = HarvestedRecord(
        source_identifier="record:1",
        payload={"title": "URL", "abstract": "Present"},
        source_url=raw_url,
        rights=None,
    )

    assert normalize_record(raw).source_url == expected


def test_normalize_record_omits_and_reports_invalid_urls() -> None:
    raw = HarvestedRecord(
        source_identifier="record:invalid-url",
        payload={"title": "URL", "abstract": "Present", "url": "https://example.com:bad"},
        source_url="https://example.com:bad",
        rights=None,
    )

    normalized = normalize_record(raw)

    assert normalized.source_url is None
    assert "url" not in normalized.identifiers
    assert {
        "field": "source_url",
        "original": "https://example.com:bad",
        "normalized": None,
    } in normalized.normalization_report["transformations"]
    assert {
        "field": "url",
        "original": "https://example.com:bad",
        "normalized": None,
    } in normalized.normalization_report["transformations"]


def test_normalize_record_preserves_brackets_in_ipv6_urls() -> None:
    raw = HarvestedRecord(
        source_identifier="record:ipv6",
        payload={"title": "IPv6", "abstract": "Present"},
        source_url="https://[2001:db8::1]:8443/A",
        rights=None,
    )

    assert normalize_record(raw).source_url == "https://[2001:db8::1]:8443/A"
