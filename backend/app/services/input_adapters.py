"""Input adapters — Phase 19."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

# Hard caps.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_PAGES = 40
# Per page.
MAX_CHARS_PER_PAGE = 8_000

# PDF magic bytes.
_PDF_MAGIC = b"%PDF-"


class UnsupportedDocument(ValueError):
    """The document cannot be read, with a reason a person can act on."""


@dataclass(frozen=True)
class NormalizedEvidence:
    """One readable chunk of source material, with its identity."""

    document_id: str
    document_name: str
    text: str
    page: int | None = None


@dataclass
class IngestionResult:
    """What an adapter produced, including what it could not read."""

    document_id: str
    document_name: str
    media_type: str
    evidence: list[NormalizedEvidence] = field(default_factory=list)
    pages: int | None = None
    # Pages that yielded no extractable text. Reported, never guessed at.
    pages_without_text: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ingested_on: date = field(default_factory=date.today)

    @property
    def has_text(self) -> bool:
        return any(e.text.strip() for e in self.evidence)


def _document_id(payload: bytes, name: str) -> str:
    """Stable id from the content, so re-uploading the same file matches."""
    return hashlib.sha256(payload + name.encode("utf-8")).hexdigest()[:16]


# Text

def ingest_text(text: str, *, name: str = "Description") -> IngestionResult:
    """The engineer's own words. No parsing, no interpretation, no failure mode."""
    cleaned = text.strip()
    document_id = _document_id(cleaned.encode("utf-8"), name)
    return IngestionResult(
        document_id=document_id,
        document_name=name,
        media_type="text/plain",
        evidence=(
            [NormalizedEvidence(document_id=document_id, document_name=name, text=cleaned)]
            if cleaned
            else []
        ),
    )


# PDF

def pdf_support() -> tuple[bool, str]:
    """Whether PDF ingestion is available in this environment."""
    try:
        import fitz  # noqa: F401, PLC0415
    except ImportError:
        return False, (
            "PDF reading needs PyMuPDF, which is not installed. "
            "Describe the product in text instead."
        )
    return True, ""


def ingest_pdf(payload: bytes, *, name: str) -> IngestionResult:
    """Extract the text layer of a PDF, page by page."""
    available, reason = pdf_support()
    if not available:
        raise UnsupportedDocument(reason)

    if len(payload) > MAX_DOCUMENT_BYTES:
        raise UnsupportedDocument(
            f"The file is {len(payload) / 1_048_576:.1f} MB; the limit is "
            f"{MAX_DOCUMENT_BYTES // 1_048_576} MB."
        )
    # Magic bytes, not the filename: the uploader controls the name.
    if not payload.startswith(_PDF_MAGIC):
        raise UnsupportedDocument("That file is not a PDF.")

    import fitz  # noqa: PLC0415

    document_id = _document_id(payload, name)
    try:
        document = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - any parser failure is one answer
        raise UnsupportedDocument(f"The PDF could not be opened: {str(exc)[:160]}")

    result = IngestionResult(
        document_id=document_id,
        document_name=name,
        media_type="application/pdf",
        pages=document.page_count,
    )

    if document.page_count > MAX_PAGES:
        result.notes.append(
            f"The document has {document.page_count} pages; only the first {MAX_PAGES} were read."
        )

    try:
        for index in range(min(document.page_count, MAX_PAGES)):
            text = document[index].get_text().strip()
            if not text:
                # A page with no text layer is a scan or a drawing.
                result.pages_without_text.append(index + 1)
                continue
            result.evidence.append(
                NormalizedEvidence(
                    document_id=document_id,
                    document_name=name,
                    text=text[:MAX_CHARS_PER_PAGE],
                    page=index + 1,
                )
            )
    finally:
        document.close()

    if result.pages_without_text:
        result.notes.append(
            f"Pages {', '.join(str(p) for p in result.pages_without_text)} contain visual "
            "content only. Drawings and images are not interpreted in this version."
        )
    if not result.has_text:
        result.notes.append(
            "No readable text was found. If this is a scanned document, describe the product "
            "in text instead."
        )

    return result


def ingest(payload: bytes, *, name: str, media_type: str | None = None) -> IngestionResult:
    """Route an uploaded file to the adapter that can read it."""
    if payload.startswith(_PDF_MAGIC):
        return ingest_pdf(payload, name=name)

    # Anything that decodes as text is treated as text.
    try:
        return ingest_text(payload.decode("utf-8"), name=name)
    except UnicodeDecodeError:
        raise UnsupportedDocument(
            f"'{name}' is not a PDF or a text file. Supported: PDF with a text layer, "
            "and plain text. Drawings, images, spreadsheets and CAD are not read in this version."
        )
