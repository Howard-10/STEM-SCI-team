from stem_sci.knowledge.document_parser import GrobidDocumentParser
from stem_sci.knowledge.evidence_quality import configured_evidence_provider
from stem_sci.research_data.schema_validation import PanderaSchemaValidator


def test_grobid_tei_parser_preserves_research_structure() -> None:
    xml = """
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader><fileDesc><titleStmt><title>Physics Study</title></titleStmt>
        <sourceDesc><biblStruct><author><persName>Ada Lovelace</persName></author></biblStruct></sourceDesc>
      </fileDesc></teiHeader>
      <text><body><div><head>Results</head><p>Effect estimate was positive.</p></div></body></text>
    </TEI>
    """
    parsed = GrobidDocumentParser().parse_tei(xml)
    assert parsed.title == "Physics Study"
    assert parsed.authors == ("Ada Lovelace",)
    assert parsed.sections[0].heading == "Results"
    assert "positive" in parsed.sections[0].text


def test_nli_configuration_has_explicit_offline_fallback(monkeypatch) -> None:
    monkeypatch.delenv("STEM_SCI_NLI", raising=False)
    provider = configured_evidence_provider()
    assert provider.model_id == "lexical-evidence-screen-v1"


def test_pandera_adapter_reports_missing_optional_dependency() -> None:
    report = PanderaSchemaValidator().validate(report_id="schema-1", frame=object(), schema=object())
    assert report.passed is False
    assert report.findings[0].code in {"PANDERA_UNAVAILABLE", "PANDERA_INVALID_INPUT"}
