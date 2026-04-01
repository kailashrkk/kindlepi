from PIL import Image, ImageDraw
import os
import subprocess

from layout import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT,
    MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM,
    FONT_SIZE, LINE_HEIGHT,
    TITLE_FONT_SIZE, TITLE_BLOCK_HEIGHT,
    load_font,
)

VCOM    = "-1.78"
MODE    = "0"
DRIVER  = "/home/kailash/IT8951-ePaper/Raspberry/epd"
TMP_BMP = "/tmp/kindlepi.bmp"

STATUS_FONT_SIZE  = 22
STATUS_BAR_HEIGHT = 36   # px reserved at the bottom for the status line


class EinkDisplay:
    def __init__(self):
        self.width  = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT

    def text_to_image(
        self,
        lines:  list[str],
        title:  str | None = None,
        status: str | None = None,
    ) -> Image.Image:
        """
        Render pre-wrapped lines onto a blank page.
        - title:  optional chapter heading with divider (first page of chapter)
        - status: optional footer string, e.g. "Ch 3 · Page 12/67"
        Lines come from epub_parser.get_page() -- do NOT re-wrap here.
        """
        img  = Image.new("L", (self.width, self.height), 255)
        draw = ImageDraw.Draw(img)
        font  = load_font(FONT_SIZE)
        tfont = load_font(TITLE_FONT_SIZE)
        sfont = load_font(STATUS_FONT_SIZE)

        x = MARGIN_LEFT
        y = MARGIN_TOP

        # Title block
        if title:
            draw.text((x, y), title, font=tfont, fill=0)
            y += int(TITLE_FONT_SIZE * 1.4) + 10
            draw.line([(x, y), (self.width - MARGIN_RIGHT, y)], fill=0, width=1)
            y += 15

        # Body -- bottom boundary shrinks if there's a status bar
        bottom = self.height - MARGIN_BOTTOM
        if status:
            bottom -= STATUS_BAR_HEIGHT

        for line in lines:
            if y + LINE_HEIGHT > bottom:
                break
            if line:
                draw.text((x, y), line, font=font, fill=0)
            y += LINE_HEIGHT

        # Status bar
        if status:
            sy = self.height - MARGIN_BOTTOM - STATUS_BAR_HEIGHT + 8
            draw.line(
                [(MARGIN_LEFT, sy - 6), (self.width - MARGIN_RIGHT, sy - 6)],
                fill=180, width=1
            )
            draw.text((x, sy), status, font=sfont, fill=80)

        return img

    def show_image(self, img: Image.Image) -> None:
        img = img.rotate(90, expand=True)
        img = img.convert("RGB").convert("L")
        img.save(TMP_BMP, format="BMP")
        import time; time.sleep(0.5)
        subprocess.run([DRIVER, VCOM, MODE, TMP_BMP], check=True)

    def show_page(
        self,
        lines:  list[str],
        title:  str | None = None,
        status: str | None = None,
    ) -> None:
        img = self.text_to_image(lines, title=title, status=status)
        self.show_image(img)

    def clear(self) -> None:
        img = Image.new("L", (self.width, self.height), 255)
        self.show_image(img)


if __name__ == "__main__":
    import sys
    from epub_parser import EpubParser

    epub_path = sys.argv[1] if len(sys.argv) > 1 else None
    d = EinkDisplay()

    if epub_path:
        parser = EpubParser(epub_path)
        parser.load()
        lines  = parser.get_page(0, 0)
        title  = parser.get_chapter_title(0)
        print(f"Rendering chapter 0, page 0 ({len(lines)} lines)...")
        d.show_page(lines, title=title, status="Ch 1  ·  Page 1/52")
    else:
        print("Rendering static test page...")
        d.show_page(
            ["The quick brown fox jumps over the lazy dog."] * 20,
            title="KindlePi Display Test",
            status="Ch 1  ·  Page 1/1"
        )
    print("Done")
