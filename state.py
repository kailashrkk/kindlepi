"""
state.py -- PageState dataclass + SQLite persistence for KindlePi.

Tracks the reader's current position (epub file, chapter, page) and
persists it across reboots. Also stores per-book metadata (chapter
count, page counts per chapter) so the parser doesn't re-paginate on
every boot.
"""

import sqlite3
import os
from dataclasses import dataclass, field
from typing import Optional

DB_PATH = "/home/kailash/reader/state.db"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class PageState:
    epub_path: str
    chapter_idx: int = 0
    page_idx: int = 0
    total_chapters: int = 0
    pages_per_chapter: list[int] = field(default_factory=list)

    @property
    def total_pages_in_chapter(self) -> int:
        if not self.pages_per_chapter:
            return 0
        if self.chapter_idx >= len(self.pages_per_chapter):
            return 0
        return self.pages_per_chapter[self.chapter_idx]

    def next_page(self) -> bool:
        """Advance one page. Returns True if the chapter boundary was crossed."""
        if self.page_idx < self.total_pages_in_chapter - 1:
            self.page_idx += 1
            return False
        elif self.chapter_idx < self.total_chapters - 1:
            self.chapter_idx += 1
            self.page_idx = 0
            return True
        return False

    def prev_page(self) -> bool:
        """Go back one page. Returns True if the chapter boundary was crossed."""
        if self.page_idx > 0:
            self.page_idx -= 1
            return False
        elif self.chapter_idx > 0:
            self.chapter_idx -= 1
            self.page_idx = max(0, self.total_pages_in_chapter - 1)
            return True
        return False

    def is_last_page(self) -> bool:
        return (
            self.chapter_idx == self.total_chapters - 1
            and self.page_idx == self.total_pages_in_chapter - 1
        )

    def is_first_page(self) -> bool:
        return self.chapter_idx == 0 and self.page_idx == 0


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def _get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every boot."""
    with _get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reading_position (
                epub_path        TEXT PRIMARY KEY,
                chapter_idx      INTEGER NOT NULL DEFAULT 0,
                page_idx         INTEGER NOT NULL DEFAULT 0,
                total_chapters   INTEGER NOT NULL DEFAULT 0,
                updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chapter_page_counts (
                epub_path        TEXT NOT NULL,
                chapter_idx      INTEGER NOT NULL,
                page_count       INTEGER NOT NULL,
                PRIMARY KEY (epub_path, chapter_idx)
            );
        """)


def save_state(state: PageState) -> None:
    """Upsert the current reading position for the given epub."""
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO reading_position
                (epub_path, chapter_idx, page_idx, total_chapters, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(epub_path) DO UPDATE SET
                chapter_idx    = excluded.chapter_idx,
                page_idx       = excluded.page_idx,
                total_chapters = excluded.total_chapters,
                updated_at     = excluded.updated_at
        """, (state.epub_path, state.chapter_idx, state.page_idx, state.total_chapters))

        conn.execute(
            "DELETE FROM chapter_page_counts WHERE epub_path = ?",
            (state.epub_path,)
        )
        conn.executemany(
            "INSERT INTO chapter_page_counts (epub_path, chapter_idx, page_count) VALUES (?, ?, ?)",
            [(state.epub_path, i, count) for i, count in enumerate(state.pages_per_chapter)]
        )


def load_state(epub_path: str) -> Optional[PageState]:
    """
    Load saved position for the given epub.
    Returns None if the epub has never been opened.
    """
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reading_position WHERE epub_path = ?",
            (epub_path,)
        ).fetchone()

        if row is None:
            return None

        counts = conn.execute(
            """SELECT page_count FROM chapter_page_counts
               WHERE epub_path = ? ORDER BY chapter_idx ASC""",
            (epub_path,)
        ).fetchall()

        pages_per_chapter = [r["page_count"] for r in counts]

        return PageState(
            epub_path=epub_path,
            chapter_idx=row["chapter_idx"],
            page_idx=row["page_idx"],
            total_chapters=row["total_chapters"],
            pages_per_chapter=pages_per_chapter,
        )


def load_or_create_state(epub_path: str) -> tuple[PageState, bool]:
    """
    Convenience wrapper used by reader.py on startup.

    Returns:
        (state, is_new) -- is_new=True means the epub was never opened before,
        so the caller should run the parser and call save_state() afterwards.
    """
    init_db()
    state = load_state(epub_path)
    if state is not None:
        return state, False
    return PageState(epub_path=epub_path), True
