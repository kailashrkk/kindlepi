"""
layout.py -- Shared display constants for KindlePi.

Both epub_parser.py and display.py import from here so pagination
and rendering always use identical measurements.
"""

from PIL import ImageFont
import os

DISPLAY_WIDTH  = 825
DISPLAY_HEIGHT = 1200
MARGIN_LEFT    = 60
MARGIN_RIGHT   = 60
MARGIN_TOP     = 60
MARGIN_BOTTOM  = 60
FONT_SIZE      = 36
LINE_SPACING   = 1.4

# Derived
MAX_WIDTH  = DISPLAY_WIDTH - MARGIN_LEFT - MARGIN_RIGHT   # 705px
LINE_HEIGHT = int(FONT_SIZE * LINE_SPACING)               # 50px

# Title area: title font (28pt) + spacing + divider line + padding
TITLE_FONT_SIZE = 28
TITLE_BLOCK_HEIGHT = int(TITLE_FONT_SIZE * LINE_SPACING) + 10 + 1 + 15  # ~65px

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
]

def load_font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def max_lines_per_page(with_title: bool = False) -> int:
    """
    How many body text lines fit on a page, optionally reserving
    space for the chapter title block at the top.
    """
    usable_height = DISPLAY_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    if with_title:
        usable_height -= TITLE_BLOCK_HEIGHT
    return usable_height // LINE_HEIGHT
