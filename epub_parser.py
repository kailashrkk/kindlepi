"""
epub_parser.py -- Parse an epub and paginate its content for KindlePi.

Design goals:
  - Pagination is pixel-accurate, using the same font and measurements
    as display.py via layout.py.
  - Display-agnostic in the sense that it never calls epd or writes BMPs.
  - Testable on a laptop (Pillow is the only hardware-free dependency).
  - Returns pages as list[list[str]] -- a list of pre-wrapped lines per page.
    display.py renders these verbatim, no re-wrapping.

Usage:
    parser = EpubParser("book.epub")
    parser.load()

    lines = parser.get_page(0, 2)        # chapter 0, page 2
    state.total_chapters    = parser.total_chapters
    state.pages_per_chapter = parser.pages_per_chapter
"""

import re
from dataclasses import dataclass, field

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from PIL import ImageDraw, Image

from layout import (
    MAX_WIDTH,
    LINE_HEIGHT,
    load_font,
    max_lines_per_page,
    FONT_SIZE,
)


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class Chapter:
    title: str
    raw_text: str
    pages: list[list[str]] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class EpubParser:
    def __init__(self, epub_path: str):
        self.epub_path = epub_path
        self._chapters: list[Chapter] = []
        self._loaded = False

        # Build a throwaway draw context for textbbox measurements.
        # This is the same font display.py uses -- pixel-perfect match.
        self._font = load_font(FONT_SIZE)
        _img = Image.new("L", (1, 1))
        self._draw = ImageDraw.Draw(_img)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Parse and paginate all chapters. Call once on startup."""
        book = epub.read_epub(self.epub_path)
        raw_chapters = self._extract_chapters(book)
        self._chapters = [self._paginate(ch) for ch in raw_chapters]
        self._loaded = True

    @property
    def total_chapters(self) -> int:
        self._assert_loaded()
        return len(self._chapters)

    @property
    def pages_per_chapter(self) -> list[int]:
        self._assert_loaded()
        return [ch.page_count for ch in self._chapters]

    def get_page(self, chapter_idx: int, page_idx: int) -> list[str]:
        """
        Return pre-wrapped lines for the given position.
        display.py renders these top-to-bottom with no further wrapping.
        Returns [] at end of book.
        """
        self._assert_loaded()
        if chapter_idx >= len(self._chapters):
            return []
        chapter = self._chapters[chapter_idx]
        if page_idx >= len(chapter.pages):
            return []
        return chapter.pages[page_idx]

    def get_chapter_title(self, chapter_idx: int) -> str:
        self._assert_loaded()
        if chapter_idx >= len(self._chapters):
            return ""
        return self._chapters[chapter_idx].title

    def get_chapter_text(self, chapter_idx: int) -> str:
        """Full raw text for a chapter -- used by ai.py for summarisation."""
        self._assert_loaded()
        if chapter_idx >= len(self._chapters):
            return ""
        return self._chapters[chapter_idx].raw_text

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_chapters(self, book: epub.EpubBook) -> list[Chapter]:
        chapters: list[Chapter] = []
        seen_ids: set[str] = set()

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            if item.get_id() in seen_ids:
                continue
            seen_ids.add(item.get_id())

            text, title = self._html_to_text(item.get_content())

            if len(text.strip()) < 150:
                continue  # skip nav / toc pages

            chapters.append(Chapter(title=title, raw_text=text))

        return chapters

    def _html_to_text(self, html_bytes: bytes) -> tuple[str, str]:
        soup = BeautifulSoup(html_bytes, "html.parser")

        title = ""
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            candidate = tag.get_text(strip=True)
            if candidate:
                title = candidate
                break

        for tag in soup(["script", "style", "head"]):
            tag.decompose()

        for tag in soup.find_all(["p", "div", "br", "li"]):
            tag.insert_before("\n\n")

        raw = soup.get_text(separator=" ")

        lines = raw.splitlines()
        cleaned_lines: list[str] = []
        blank_run = 0
        for line in lines:
            line = re.sub(r"[ \t]+", " ", line).strip()
            if not line:
                blank_run += 1
                if blank_run <= 1:
                    cleaned_lines.append("")
            else:
                blank_run = 0
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip(), title

    # ------------------------------------------------------------------
    # Pagination -- pixel-aware
    # ------------------------------------------------------------------

    def _paginate(self, chapter: Chapter) -> Chapter:
        """
        Wrap chapter text using real pixel measurements, then slice into pages.
        The first page of each chapter reserves space for the title block.
        """
        paragraphs = chapter.raw_text.split("\n")
        all_lines: list[str] = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                if all_lines and all_lines[-1] != "":
                    all_lines.append("")
                continue
            all_lines.extend(self._pixel_wrap(para))

        # Trim leading/trailing blanks
        while all_lines and all_lines[0] == "":
            all_lines.pop(0)
        while all_lines and all_lines[-1] == "":
            all_lines.pop()

        pages: list[list[str]] = []
        first_page = True

        while all_lines:
            while all_lines and all_lines[0] == "":
                all_lines.pop(0)

            # First page is shorter because the title block takes up space
            limit = max_lines_per_page(with_title=first_page)
            page = all_lines[:limit]
            all_lines = all_lines[limit:]
            if page:
                pages.append(page)
            first_page = False

        chapter.pages = pages if pages else [[]]
        return chapter

    def _pixel_wrap(self, text: str) -> list[str]:
        """
        Wrap a single paragraph into lines that fit within MAX_WIDTH pixels,
        using the exact font that display.py renders with.
        """
        words = text.split()
        lines: list[str] = []
        current: list[str] = []

        for word in words:
            candidate = " ".join(current + [word])
            bbox = self._draw.textbbox((0, 0), candidate, font=self._font)
            if bbox[2] <= MAX_WIDTH:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                # Word wider than MAX_WIDTH -- hard break by character
                while True:
                    bbox = self._draw.textbbox((0, 0), word, font=self._font)
                    if bbox[2] <= MAX_WIDTH:
                        break
                    # Binary-search the break point
                    lo, hi = 1, len(word)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        b = self._draw.textbbox((0, 0), word[:mid], font=self._font)
                        if b[2] <= MAX_WIDTH:
                            lo = mid
                        else:
                            hi = mid - 1
                    lines.append(word[:lo])
                    word = word[lo:]
                current = [word]

        if current:
            lines.append(" ".join(current))

        return lines

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assert_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError(
                "EpubParser.load() must be called before accessing content."
            )


# ---------------------------------------------------------------------------
# CLI smoke test: python epub_parser.py path/to/book.epub
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python epub_parser.py <path_to_epub>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"Parsing: {path}")
    parser = EpubParser(path)
    parser.load()

    print(f"Chapters found : {parser.total_chapters}")
    print(f"Pages/chapter  : {parser.pages_per_chapter}")
    print()

    for page_idx in range(min(2, parser.pages_per_chapter[0])):
        title = parser.get_chapter_title(0)
        print(f"--- Chapter 0 ({title!r}), Page {page_idx} ---")
        for line in parser.get_page(0, page_idx):
            print(repr(line))
        print()
