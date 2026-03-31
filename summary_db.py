"""
summary_db.py -- Rolling chapter summary storage for KindlePi.

Stores AI-generated summaries per book per chapter in SQLite.
Summaries are generated once and cached -- no redundant AI calls.

The "rolling" aspect: when the reader requests a summary, we pass
the previous chapter's summary as context to the AI, so each new
summary builds on what came before rather than treating each chapter
in isolation. This compensates for the small context window of
Qwen2.5-1.5B.
"""

import sqlite3
import os
from typing import Optional

DB_PATH = "/home/kailash/reader/state.db"


class SummaryDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def init(self) -> None:
        """Create the summaries table if it doesn't exist. Safe to call every boot."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chapter_summaries (
                    epub_path    TEXT    NOT NULL,
                    chapter_idx  INTEGER NOT NULL,
                    summary      TEXT    NOT NULL,
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (epub_path, chapter_idx)
                )
            """)

    def get_summary(self, epub_path: str, chapter_idx: int) -> Optional[str]:
        """Return cached summary for this chapter, or None if not yet generated."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT summary FROM chapter_summaries
                   WHERE epub_path = ? AND chapter_idx = ?""",
                (epub_path, chapter_idx)
            ).fetchone()
        return row[0] if row else None

    def save_summary(self, epub_path: str, chapter_idx: int, summary: str) -> None:
        """Upsert a summary for the given chapter."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO chapter_summaries (epub_path, chapter_idx, summary)
                VALUES (?, ?, ?)
                ON CONFLICT(epub_path, chapter_idx) DO UPDATE SET
                    summary    = excluded.summary,
                    created_at = datetime('now')
            """, (epub_path, chapter_idx, summary))

    def get_previous_summary(self, epub_path: str, chapter_idx: int) -> Optional[str]:
        """
        Return the summary of the previous chapter if it exists.
        Used to build rolling context for the AI prompt.
        """
        if chapter_idx == 0:
            return None
        return self.get_summary(epub_path, chapter_idx - 1)

    def get_all_summaries(self, epub_path: str) -> list[tuple[int, str]]:
        """Return all summaries for a book as [(chapter_idx, summary), ...]."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT chapter_idx, summary FROM chapter_summaries
                   WHERE epub_path = ? ORDER BY chapter_idx ASC""",
                (epub_path,)
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def delete_summaries(self, epub_path: str) -> None:
        """
        WARNING -- DELETES all summaries for a book.
        Only call if the user explicitly requests a reset.
        """
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM chapter_summaries WHERE epub_path = ?",
                (epub_path,)
            )

    def _conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


if __name__ == "__main__":
    db = SummaryDB()
    db.init()

    epub = "/home/kailash/books/test.epub"
    ch   = 1
    text = "Mr. Bennet visits Mr. Bingley. Mrs. Bennet is delighted."

    print("Saving test summary...")
    db.save_summary(epub, ch, text)

    print("Retrieving summary...")
    result = db.get_summary(epub, ch)
    assert result == text, f"Mismatch: {result!r}"

    print("Retrieving previous summary (ch 0, should be None)...")
    assert db.get_previous_summary(epub, 0) is None

    print("Retrieving previous summary for ch 1 (ch 0 not saved yet, should be None)...")
    assert db.get_previous_summary(epub, ch) is None

    print("Saving ch 0 summary and retesting...")
    db.save_summary(epub, 0, "Introduction chapter.")
    assert db.get_previous_summary(epub, ch) == "Introduction chapter."

    print("\nAll assertions passed. summary_db.py smoke test complete.")
