"""Abstract base parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

import pdfplumber

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
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text and text.strip():
                    pages.append(text.strip())
        return "\n\n--- PAGE BREAK ---\n\n".join(pages)

    @staticmethod
    def is_text_extractable(file: Path) -> bool:
        """Return True if the PDF has selectable text (not a scanned image)."""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages[:3]:
                if page.extract_text():
                    return True
        return False
