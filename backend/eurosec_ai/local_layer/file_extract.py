from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class ExtractedText:
    text: str
    file_type: str


def extract_text(path_str: str, max_chars: int = 200_000) -> ExtractedText:
    p = Path(path_str).expanduser().resolve()
    ext = p.suffix.lower()

    if ext == ".txt":
        txt = p.read_text(encoding="utf-8", errors="ignore")
        return ExtractedText(text=txt[:max_chars], file_type="txt")

    if ext == ".docx":
        from docx import Document  # python-docx
        doc = Document(str(p))
        parts = [para.text for para in doc.paragraphs if para.text and para.text.strip()]
        txt = "\n".join(parts)
        return ExtractedText(text=txt[:max_chars], file_type="docx")

    if ext == ".pdf":
        # Prefer pdfminer.six, fallback to PyPDF2
        txt = _extract_pdf_pdfminer(p)
        if not txt.strip():
            txt = _extract_pdf_pypdf2(p)
        return ExtractedText(text=txt[:max_chars], file_type="pdf")

    if ext in (".xlsx", ".xls"):
        # Read as tables, convert to text rows
        # openpyxl engine for xlsx
        try:
            xls = pd.ExcelFile(str(p))
            chunks = []
            for sheet in xls.sheet_names[:5]:
                df = xls.parse(sheet_name=sheet, nrows=200)
                chunks.append(f"--- Sheet: {sheet} ---\n{df.to_string(index=False)}")
            txt = "\n\n".join(chunks)
        except Exception:
            txt = ""
        return ExtractedText(text=txt[:max_chars], file_type="xlsx")

    return ExtractedText(text="", file_type="unknown")


def _extract_pdf_pdfminer(p: Path) -> str:
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(p)) or ""
    except Exception:
        return ""


def _extract_pdf_pypdf2(p: Path) -> str:
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(p))
        out = []
        for page in reader.pages[:20]:
            out.append(page.extract_text() or "")
        return "\n".join(out)
    except Exception:
        return ""
