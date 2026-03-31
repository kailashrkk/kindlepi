"""
reader.py -- Main loop and state machine for KindlePi.

States:
    SELECTING   -- book selection screen, no book open yet
    READING     -- normal page display
    AI_LOADING  -- waiting for llama.cpp response
    AI_RESULT   -- showing AI response overlay
    QUITTING    -- clean shutdown

Button behaviour per state:

    SELECTING:
        NEXT/PREV   -- move highlight up/down the book list
        AI          -- confirm selection, open book
        BACK        -- (no-op, already at top level)

    READING:
        NEXT        -- next page
        PREV        -- prev page
        AI          -- AI summary / word lookup (NYI)
        BACK        -- return to book selection screen

    AI_RESULT:
        any button  -- dismiss overlay, return to READING

Run:
    sudo python3 reader.py
"""

import os
import glob
import time
from enum import Enum, auto

from display     import EinkDisplay
from epub_parser import EpubParser
from state       import PageState, load_or_create_state, save_state
from buttons     import ButtonHandler, ButtonEvent
from layout      import DISPLAY_HEIGHT, MARGIN_TOP, MARGIN_BOTTOM, LINE_HEIGHT


BOOKS_DIR = "/home/kailash/books"
SAVE_INTERVAL = 5   # save position every N page turns


class ReaderState(Enum):
    SELECTING  = auto()
    READING    = auto()
    AI_LOADING = auto()
    AI_RESULT  = auto()
    QUITTING   = auto()


def scan_books(directory: str) -> list[str]:
    return sorted(glob.glob(os.path.join(directory, "**", "*.epub"), recursive=True))


def epub_metadata(epub_path: str) -> tuple[str, str]:
    try:
        from ebooklib import epub
        book   = epub.read_epub(epub_path, {"ignore_ncx": True})
        title  = book.get_metadata("DC", "title")
        author = book.get_metadata("DC", "creator")
        t = title[0][0]  if title  else os.path.basename(epub_path)
        a = author[0][0] if author else "Unknown"
        return t, a
    except Exception:
        return os.path.basename(epub_path), "Unknown"


class Reader:
    def __init__(self):
        self.display  = EinkDisplay()
        self.buttons  = ButtonHandler()
        self.state    = ReaderState.SELECTING

        self.book_paths:   list[str]            = []
        self.book_meta:    list[tuple[str, str]] = []
        self.selected_idx: int                  = 0

        self.parser:     EpubParser | None = None
        self.page_state: PageState  | None = None
        self._turns_since_save: int        = 0

        self.buttons.set_callback(self._on_button)
        self._running = True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        os.makedirs(BOOKS_DIR, exist_ok=True)
        self.book_paths = scan_books(BOOKS_DIR)

        if not self.book_paths:
            self._show_message(
                "No books found.",
                detail=f"Add .epub files to {BOOKS_DIR} and restart."
            )
            return

        print("Scanning book metadata...")
        self.book_meta = [epub_metadata(p) for p in self.book_paths]

        self.buttons.start()
        self._enter_selecting()

        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.buttons.stop()
            if self.page_state:
                save_state(self.page_state)
            print("\nShutdown complete.")

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _enter_selecting(self):
        self.state = ReaderState.SELECTING
        self._render_selection_screen()

    def _enter_reading(self, epub_path: str):
        self.state = ReaderState.READING
        self._show_message("Opening book...", detail="Parsing epub, please wait.")

        self.parser = EpubParser(epub_path)
        self.page_state, is_new = load_or_create_state(epub_path)
        self.parser.load()

        if is_new:
            self.page_state.total_chapters    = self.parser.total_chapters
            self.page_state.pages_per_chapter = self.parser.pages_per_chapter
            save_state(self.page_state)
        else:
            self.page_state.total_chapters    = self.parser.total_chapters
            self.page_state.pages_per_chapter = self.parser.pages_per_chapter

        self._render_current_page()

    def _enter_ai_loading(self):
        self.state = ReaderState.AI_LOADING
        self._show_message("AI", detail="Loading... (AI module coming soon)")
        time.sleep(1.5)
        self.state = ReaderState.READING
        self._render_current_page()

    # ------------------------------------------------------------------
    # Button handler
    # ------------------------------------------------------------------

    def _on_button(self, event: ButtonEvent):
        if self.state == ReaderState.SELECTING:
            self._handle_selecting(event)
        elif self.state == ReaderState.READING:
            self._handle_reading(event)
        elif self.state == ReaderState.AI_LOADING:
            pass
        elif self.state == ReaderState.AI_RESULT:
            self.state = ReaderState.READING
            self._render_current_page()

        if event == ButtonEvent.QUIT:
            self._running = False

    def _handle_selecting(self, event: ButtonEvent):
        if event == ButtonEvent.NEXT:
            self.selected_idx = (self.selected_idx + 1) % len(self.book_paths)
            self._render_selection_screen()
        elif event == ButtonEvent.PREV:
            self.selected_idx = (self.selected_idx - 1) % len(self.book_paths)
            self._render_selection_screen()
        elif event == ButtonEvent.AI:
            self._enter_reading(self.book_paths[self.selected_idx])

    def _handle_reading(self, event: ButtonEvent):
        if not self.page_state:
            return

        if event == ButtonEvent.NEXT:
            if not self.page_state.is_last_page():
                self.page_state.next_page()
                self._turns_since_save += 1
                if self._turns_since_save >= SAVE_INTERVAL:
                    save_state(self.page_state)
                    self._turns_since_save = 0
                self._render_current_page()

        elif event == ButtonEvent.PREV:
            if not self.page_state.is_first_page():
                self.page_state.prev_page()
                self._render_current_page()

        elif event == ButtonEvent.AI:
            self._enter_ai_loading()

        elif event == ButtonEvent.BACK:
            save_state(self.page_state)
            self.parser     = None
            self.page_state = None
            self._enter_selecting()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_current_page(self):
        if not self.parser or not self.page_state:
            return

        ch    = self.page_state.chapter_idx
        pg    = self.page_state.page_idx
        lines = self.parser.get_page(ch, pg)
        title = self.parser.get_chapter_title(ch) if pg == 0 else None
        total = self.page_state.total_pages_in_chapter
        status = f"Ch {ch + 1}  ·  Page {pg + 1}/{total}"

        print(f"[READING] {status}  ({len(lines)} lines)")
        self.display.show_page(lines, title=title, status=status)

    def _render_selection_screen(self):
        max_visible  = (DISPLAY_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM) // LINE_HEIGHT
        total        = len(self.book_paths)
        window_start = max(0, min(
            self.selected_idx - max_visible // 2,
            total - max_visible
        ))
        window_end = min(window_start + max_visible, total)

        lines = []
        for i in range(window_start, window_end):
            title, author = self.book_meta[i]
            prefix = ">> " if i == self.selected_idx else "   "
            lines.append(f"{prefix}{title}")
            lines.append(f"     {author}")
            lines.append("")

        print(f"[SELECTING] {total} books, selected={self.selected_idx}")
        self.display.show_page(lines, title="Select a Book")

    def _show_message(self, heading: str, detail: str = ""):
        lines = ["", heading, "", detail] if detail else ["", heading]
        self.display.show_page(lines)


if __name__ == "__main__":
    Reader().run()
