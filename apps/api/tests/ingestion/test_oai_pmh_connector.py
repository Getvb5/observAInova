import pytest

from pci.ingestion.connectors.oai_pmh import OaiPmhConnector


def first_oai_page_with_token(token: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-09-08T00:00:00Z</responseDate>
  <request verb="ListRecords" metadataPrefix="oai_dc">https://repo.example/oai</request>
  <ListRecords>
    <record>
      <header><identifier>oai:repo:1</identifier><datestamp>2026-01-01</datestamp></header>
      <metadata>
        <oai_dc:dc>
          <dc:title>Primeiro registro</dc:title>
          <dc:creator>Ana Silva</dc:creator>
          <dc:identifier>https://repo.example/items/1</dc:identifier>
          <dc:rights>CC BY 4.0</dc:rights>
          <dc:subject>inovação social</dc:subject>
        </oai_dc:dc>
      </metadata>
    </record>
    <resumptionToken>{token}</resumptionToken>
  </ListRecords>
</OAI-PMH>"""


def second_oai_page_without_token() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-09-08T00:00:01Z</responseDate>
  <request verb="ListRecords">https://repo.example/oai</request>
  <ListRecords>
    <record>
      <header><identifier>oai:repo:2</identifier><datestamp>2026-01-02</datestamp></header>
      <metadata>
        <oai_dc:dc>
          <dc:title>Segundo registro</dc:title>
          <dc:description>Resumo do segundo registro.</dc:description>
          <dc:publisher>Universidade de Pernambuco</dc:publisher>
          <dc:date>2025</dc:date>
          <dc:type>article</dc:type>
        </oai_dc:dc>
      </metadata>
    </record>
    <resumptionToken />
  </ListRecords>
</OAI-PMH>"""


def oai_page_with_complete_source_record(datestamp: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <responseDate>2026-09-08T00:00:02Z</responseDate>
  <request verb="ListRecords" metadataPrefix="oai_dc">https://repo.example/oai</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:repo:versioned</identifier>
        <datestamp>{datestamp}</datestamp>
        <setSpec>articles</setSpec>
        <setSpec>pernambuco</setSpec>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title xml:lang="pt-BR">Registro versionado</dc:title>
          <dc:relation>prefixo <dc:identifier>urn:related:1</dc:identifier> sufixo</dc:relation>
        </oai_dc:dc>
      </metadata>
    </record>
    <record>
      <header status="deleted">
        <identifier>oai:repo:deleted</identifier>
        <datestamp>2026-02-02</datestamp>
        <setSpec>withdrawn</setSpec>
      </header>
    </record>
    <resumptionToken />
  </ListRecords>
</OAI-PMH>"""


def oai_page_with_preserved_title(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <ListRecords>
    <record>
      <header>
        <identifier>oai:repo:whitespace</identifier>
        <datestamp>2026-02-04</datestamp>
      </header>
      <metadata>
        <oai_dc:dc>
          <dc:title xml:space="preserve">{title}</dc:title>
        </oai_dc:dc>
      </metadata>
    </record>
    <resumptionToken />
  </ListRecords>
</OAI-PMH>"""


@pytest.mark.asyncio
async def test_oai_connector_follows_resumption_token(httpx_mock) -> None:
    """Ignoring an OAI resumption token must lose the second literal record."""
    httpx_mock.add_response(text=first_oai_page_with_token("next-page"))
    httpx_mock.add_response(text=second_oai_page_without_token())

    records = [
        record async for record in OaiPmhConnector("https://repo.example/oai").harvest(None)
    ]

    assert [record.source_identifier for record in records] == ["oai:repo:1", "oai:repo:2"]
    assert records[0].payload["title"] == "Primeiro registro"
    assert records[0].payload["subject"] == "inovação social"
    assert records[0].source_url == "https://repo.example/items/1"
    assert records[0].rights == "CC BY 4.0"
    assert records[1].payload["publisher"] == "Universidade de Pernambuco"
    assert "institution" not in records[1].payload
    requests = httpx_mock.get_requests()
    assert str(requests[0].url.params) == "verb=ListRecords&metadataPrefix=oai_dc"
    assert str(requests[1].url.params) == "verb=ListRecords&resumptionToken=next-page"


@pytest.mark.asyncio
async def test_oai_connector_retries_transient_http_errors(httpx_mock) -> None:
    """Removing bounded transient retry must expose the first 503 response."""
    httpx_mock.add_response(status_code=503)
    httpx_mock.add_response(text=second_oai_page_without_token())

    records = [
        record
        async for record in OaiPmhConnector(
            "https://repo.example/oai", max_retries=1
        ).harvest(None)
    ]

    assert [record.source_identifier for record in records] == ["oai:repo:2"]
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_oai_connector_preserves_complete_namespaced_source_record(httpx_mock) -> None:
    """Flattening Dublin Core must not discard source version, attributes or structure."""
    httpx_mock.add_response(text=oai_page_with_complete_source_record("2026-02-01"))

    records = [
        record async for record in OaiPmhConnector("https://repo.example/oai").harvest(None)
    ]

    source_record = records[0].payload["_oai_pmh"]
    header, metadata = source_record["children"]
    dc = metadata["children"][0]
    title, relation = dc["children"]
    assert source_record["text"] == "\n      "
    assert header["tag"] == "{http://www.openarchives.org/OAI/2.0/}header"
    assert [child["text"] for child in header["children"]] == [
        "oai:repo:versioned",
        "2026-02-01",
        "articles",
        "pernambuco",
    ]
    assert dc["tag"] == "{http://www.openarchives.org/OAI/2.0/oai_dc/}dc"
    assert title["tag"] == "{http://purl.org/dc/elements/1.1/}title"
    assert title["attributes"] == {
        "{http://www.w3.org/XML/1998/namespace}lang": "pt-BR",
    }
    assert title["text"] == "Registro versionado"
    assert title["children"] == []
    assert title["tail"] == "\n          "
    assert relation["children"][0]["tag"] == (
        "{http://purl.org/dc/elements/1.1/}identifier"
    )
    assert relation["text"] == "prefixo "
    assert relation["children"][0]["tail"] == " sufixo"
    deleted_header = records[1].payload["_oai_pmh"]["children"][0]
    assert deleted_header["attributes"] == {"status": "deleted"}
    assert deleted_header["children"][2]["text"] == "withdrawn"
    assert records[1].is_tombstone is True


@pytest.mark.asyncio
async def test_oai_datestamp_change_changes_preserved_payload(httpx_mock) -> None:
    """Excluding source datestamp must make distinct repository versions identical."""
    httpx_mock.add_response(text=oai_page_with_complete_source_record("2026-02-01"))
    httpx_mock.add_response(text=oai_page_with_complete_source_record("2026-02-03"))
    connector = OaiPmhConnector("https://repo.example/oai")

    first = [record async for record in connector.harvest(None)]
    changed = [record async for record in connector.harvest(None)]

    assert first[0].payload != changed[0].payload


@pytest.mark.asyncio
async def test_oai_source_tree_preserves_significant_whitespace(httpx_mock) -> None:
    """Stripping xml:space content must collapse distinct source records and checksums."""
    httpx_mock.add_response(text=oai_page_with_preserved_title("A "))
    httpx_mock.add_response(text=oai_page_with_preserved_title("A"))
    connector = OaiPmhConnector("https://repo.example/oai")

    spaced = [record async for record in connector.harvest(None)]
    unspaced = [record async for record in connector.harvest(None)]

    spaced_title = spaced[0].payload["_oai_pmh"]["children"][1]["children"][0][
        "children"
    ][0]
    assert spaced_title["attributes"] == {
        "{http://www.w3.org/XML/1998/namespace}space": "preserve"
    }
    assert spaced_title["text"] == "A "
    assert spaced[0].payload != unspaced[0].payload
