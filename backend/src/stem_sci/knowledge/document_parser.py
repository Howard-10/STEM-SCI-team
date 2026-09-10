"""Optional GROBID document parser adapter."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

import httpx


@dataclass(frozen=True)
class ParsedSection:
    heading: str
    text: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    parser_id: str
    title: str
    authors: tuple[str, ...]
    sections: tuple[ParsedSection, ...]
    references: tuple[str, ...]


class GrobidDocumentParser:
    """Call a local/remote GROBID service without coupling the Controller to it."""

    parser_id = "grobid-tei-v1"

    def __init__(self, endpoint: str = "http://localhost:8070") -> None:
        self.endpoint = endpoint.rstrip("/")

    def parse_pdf(self, content: bytes, *, filename: str = "document.pdf", timeout: float = 60.0) -> ParsedDocument:
        response = httpx.post(
            f"{self.endpoint}/api/processFulltextDocument",
            files={"input": (filename, content, "application/pdf")},
            timeout=timeout,
        )
        response.raise_for_status()
        return self.parse_tei(response.text)

    def parse_tei(self, tei_xml: str) -> ParsedDocument:
        root = ElementTree.fromstring(tei_xml)
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        title = " ".join(root.findtext(".//tei:titleStmt/tei:title", default="", namespaces=ns).split())
        authors = tuple(
            " ".join(node.itertext()).strip()
            for node in root.findall(".//tei:sourceDesc//tei:author", ns)
        )
        sections: list[ParsedSection] = []
        for div in root.findall(".//tei:text//tei:div", ns):
            heading = " ".join((div.findtext("tei:head", default="", namespaces=ns) or "").split())
            paragraphs = [" ".join(" ".join(p.itertext()).split()) for p in div.findall("tei:p", ns)]
            text = " ".join(item for item in paragraphs if item)
            if text:
                sections.append(ParsedSection(heading=heading or "body", text=text))
        references = tuple(
            " ".join(" ".join(item.itertext()).split())
            for item in root.findall(".//tei:listBibl//tei:biblStruct", ns)
        )
        return ParsedDocument(
            parser_id=self.parser_id,
            title=title,
            authors=authors,
            sections=tuple(sections),
            references=references,
        )
