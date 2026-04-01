"""
reader.py -- Main loop and state machine for KindlePi.

States:
    SELECTING   -- book selection screen
    READING     -- normal page display
    AI_MENU     -- AI feature menu (long press Button 1)
    AI_LOADING  -- waiting for llama.cpp response
    AI_RESULT   -- showing AI response
    QUITTING    -- clean shutdown

Button behaviour:
    READING:
        NEXT (short)     -- next page
        PREV (short)     -- prev page
        AI   (long)      -- open AI menu
        BACK (long)      -- back to book selection

    AI_MENU:
        NEXT (short)     -- move highlight down
        PREV (short)     -- move highlight up
        AI   (short)     -- confirm selection
        BACK (any)       -- dismiss menu

    AI_RESULT:
        any              -- dismiss, return to reading
"""

import os
import glob
import time
import threading
from enum import Enum, auto

from display     import EinkDisplay
from epub_parser import EpubParser
from state       import PageState, load_or_create_state, save_state
from buttons     import ButtonHandler, ButtonEvent
from ai          import AIClient, AIError
from summary_db  import SummaryDB
from layout      import DISPLAY_HEIGHT, MARGIN_TOP, MARGIN_BOTTOM, LINE_HEIGHT

BOOKS_DIR     = "/home/kailash/books"
SAVE_INTERVAL = 5
QUESTION_PIPE = "/tmp/kindlepi_question"

AI_MENU_ITEMS = [
    "Chapter Summary",
    "Ask a Question",
    "Cancel",
]


class ReaderState(Enum):
    SELECTING  = auto()
    READING    = auto()
    AI_MENU    = auto()
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
        self.display    = EinkDisplay()
        self.buttons    = ButtonHandler()
        self.ai         = AIClient()
        self.summary_db = SummaryDB()
        self.state      = ReaderState.SELECTING

        self.book_paths:   list[str]             = []
        self.book_meta:    list[tuple[str, str]]  = []
        self.selected_idx: int                   = 0

        self.parser:     EpubParser | None = None
        self.page_state: PageState  | None = None
        self._turns_since_save: int        = 0

        # AI menu state
        self.ai_menu_idx:    int        = 0
        self._ai_result_text: str       = ""

        self.buttons.set_callback(self._on_button)
        self._running = True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        os.makedirs(BOOKS_DIR, exist_ok=True)
        self.summary_db.init()

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
        pass

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

    def _enter_ai_menu(self):
        self.state       = ReaderState.AI_MENU
        self.ai_menu_idx = 0
        self._render_ai_menu()

    def _enter_ai_loading(self, mode: str):
        self.state = ReaderState.AI_LOADING
        self._show_message("AI", detail="Thinking... please wait.")
        # Run in thread so the main loop stays responsive
        threading.Thread(
            target=self._run_ai, args=(mode,), daemon=True
        ).start()

    def _run_ai(self, mode: str):
        """Called in a background thread. Updates display when done."""
        if not self.parser or not self.page_state:
            self._finish_ai("No book open.")
            return

        ch           = self.page_state.chapter_idx
        epub_path    = self.page_state.epub_path
        chapter_text = self.parser.get_chapter_text(ch)
        prev_summary = self.summary_db.get_previous_summary(epub_path, ch)

        try:
            if mode == "summary":
                # Check cache first
                cached = self.summary_db.get_summary(epub_path, ch)
                if cached:
                    self._finish_ai(cached)
                    return
                result = self.ai.chapter_summary(
                    chapter_text, previous_summary=prev_summary
                )
                self.summary_db.save_summary(epub_path, ch, result)
                self._finish_ai(result)

            elif mode == "question":
                question = self._read_question_from_pipe()
                if not question:
                    self._finish_ai("No question received.\nSend via:\necho 'your question' > /tmp/kindlepi_question")
                    return
                result = self.ai.ask_question(
                    chapter_text, question, previous_summary=prev_summary
                )
                self._finish_ai(result)

        except AIError as e:
            self._finish_ai(f"AI error:\n{str(e)}")

    def _finish_ai(self, text: str):
        self._ai_result_text = text
        self.state           = ReaderState.AI_RESULT
        self._render_ai_result(text)

    # ------------------------------------------------------------------
    # Button handler
    # ------------------------------------------------------------------

    def _on_button(self, event: ButtonEvent):
        if self.state == ReaderState.SELECTING:
            self._handle_selecting(event)
        elif self.state == ReaderState.READING:
            self._handle_reading(event)
        elif self.state == ReaderState.AI_MENU:
            self._handle_ai_menu(event)
        elif self.state == ReaderState.AI_LOADING:
            pass  # ignore all input while loading
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
            self._enter_ai_menu()
        elif event == ButtonEvent.BACK:
            save_state(self.page_state)
            self.parser     = None
            self.page_state = None
            self._enter_selecting()

    def _handle_ai_menu(self, event: ButtonEvent):
        if event == ButtonEvent.NEXT:
            self.ai_menu_idx = (self.ai_menu_idx + 1) % len(AI_MENU_ITEMS)
            self._render_ai_menu()
        elif event == ButtonEvent.PREV:
            self.ai_menu_idx = (self.ai_menu_idx - 1) % len(AI_MENU_ITEMS)
            self._render_ai_menu()
        elif event == ButtonEvent.AI:
            selected = AI_MENU_ITEMS[self.ai_menu_idx]
            if selected == "Chapter Summary":
                self._enter_ai_loading("summary")
            elif selected == "Ask a Question":
                self._show_message(
                    "Ask a Question",
                    detail="Send your question via:\necho 'question' > /tmp/kindlepi_question"
                )
                self._enter_ai_loading("question")
            elif selected == "Cancel":
                self.state = ReaderState.READING
                self._render_current_page()
        elif event == ButtonEvent.BACK:
            self.state = ReaderState.READING
            self._render_current_page()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_current_page(self):
        if not self.parser or not self.page_state:
            return
        ch     = self.page_state.chapter_idx
        pg     = self.page_state.page_idx
        lines  = self.parser.get_page(ch, pg)
        title  = self.parser.get_chapter_title(ch) if pg == 0 else None
        total  = self.page_state.total_pages_in_chapter
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

    def _render_ai_menu(self):
        lines = [""]
        for i, item in enumerate(AI_MENU_ITEMS):
            prefix = ">> " if i == self.ai_menu_idx else "   "
            lines.append(f"{prefix}{item}")
            lines.append("")
        print(f"[AI_MENU] selected={self.ai_menu_idx}")
        self.display.show_page(lines, title="AI Assistant")

    def _render_ai_result(self, text: str):
        from epub_parser import EpubParser as _EP
        # Word-wrap the AI response using the same pixel-aware logic
        from PIL import ImageDraw, Image
        from layout import MAX_WIDTH, FONT_SIZE, load_font
        font  = load_font(FONT_SIZE)
        _img  = Image.new("L", (1, 1))
        _draw = ImageDraw.Draw(_img)

        lines = []
        for para in text.split("\n"):
            para = para.strip()
            if not para:
                lines.append("")
                continue
            words   = para.split()
            current = []
            for word in words:
                candidate = " ".join(current + [word])
                bbox = _draw.textbbox((0, 0), candidate, font=font)
                if bbox[2] <= MAX_WIDTH:
                    current.append(word)
                else:
                    if current:
                        lines.append(" ".join(current))
                    current = [word]
            if current:
                lines.append(" ".join(current))

        print(f"[AI_RESULT] {len(lines)} lines")
        self.display.show_page(lines, title="AI Response", status="Any button to return")

    def _show_message(self, heading: str, detail: str = ""):
        lines = ["", heading, "", detail] if detail else ["", heading]
        self.display.show_page(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_question_from_pipe(self, timeout: int = 60) -> str | None:
        """
        Wait up to timeout seconds for a question via the named pipe.
        Returns the question string or None if nothing arrives.
        """
        import select
        if not os.path.exists(QUESTION_PIPE):
            os.mkfifo(QUESTION_PIPE)
            os.chmod(QUESTION_PIPE, 0o666)

        try:
            fd = os.open(QUESTION_PIPE, os.O_RDONLY | os.O_NONBLOCK)
            ready, _, _ = select.select([fd], [], [], timeout)
            if ready:
                data = os.read(fd, 1024).decode("utf-8").strip()
                os.close(fd)
                return data if data else None
            os.close(fd)
            return None
        except Exception:
            return None


if __name__ == "__main__":
    Reader().run()
