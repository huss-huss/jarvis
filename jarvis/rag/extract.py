"""Extract plain text from common document formats."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

SUPPORTED_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".pdf",
    ".docx",
    ".html",
    ".htm",
}


class ExtractError(ValueError):
    pass


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES and suffix != "":
        raise ExtractError(f"Unsupported file type: {suffix or '(none)'}")

    if suffix in {".txt", ".md", ".markdown", ".rst", ".log", ".toml", ".yaml", ".yml", ""}:
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".json":
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            data = json.loads(raw)
            return json.dumps(data, indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return raw

    if suffix in {".csv", ".tsv"}:
        delim = "\t" if suffix == ".tsv" else ","
        text = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(StringIO(text), delimiter=delim)
        rows = [", ".join(cell.strip() for cell in row) for row in reader if any(cell.strip() for cell in row)]
        return "\n".join(rows)

    if suffix in {".html", ".htm"}:
        return _strip_html(path.read_text(encoding="utf-8", errors="replace"))

    if suffix == ".pdf":
        return _extract_pdf(path)

    if suffix == ".docx":
        return _extract_docx(path)

    return path.read_text(encoding="utf-8", errors="replace")


def _strip_html(html: str) -> str:
    import re

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractError(
            "PDF support needs pypdf. Install with: uv sync --extra rag"
        ) from exc
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    if not text:
        raise ExtractError(f"No extractable text in PDF: {path}")
    return text


def _extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise ExtractError(
            "DOCX support needs python-docx. Install with: uv sync --extra rag"
        ) from exc
    document = docx.Document(str(path))
    parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    if not parts:
        raise ExtractError(f"No extractable text in DOCX: {path}")
    return "\n".join(parts)
