"""Abstract base parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

import fitz  # PyMuPDF

from pfile.models.documents import ParseConfidence

T = TypeVar("T")


class BaseParser(ABC, Generic[T]):
    @abstractmethod
    def parse(self, file: Path) -> T:
        """Parse a document file and return a structured model."""
        ...

    @staticmethod
    def extract_text(file: Path) -> str:
        """Extract all text from a PDF, joining pages with a separator."""
        pages: list[str] = []
        with fitz.open(str(file)) as doc:
            for page in doc:
                text = page.get_text("text")
                if text and text.strip():
                    pages.append(text.strip())
        return "\n\n--- PAGE BREAK ---\n\n".join(pages)

    @staticmethod
    def is_text_extractable(file: Path) -> bool:
        """Return True if the PDF has selectable text (not a scanned image)."""
        with fitz.open(str(file)) as doc:
            for page in doc[:3]:
                if page.get_text("text").strip():
                    return True
        return False
