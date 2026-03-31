from PIL import Image, ImageDraw, ImageFont
import os
import subprocess

DISPLAY_WIDTH  = 825
DISPLAY_HEIGHT = 1200
MARGIN_LEFT    = 60
MARGIN_RIGHT   = 60
MARGIN_TOP     = 60
MARGIN_BOTTOM  = 60
FONT_SIZE      = 36
LINE_SPACING   = 1.4
VCOM           = "-1.78"
MODE           = "0"
DRIVER = "/home/kailash/IT8951-ePaper/Raspberry/epd"
TMP_BMP        = "/tmp/kindlepi.bmp"

class EinkDisplay:
    def __init__(self):
        self.width  = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT

    def _get_font(self, size):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
        ]
        for p in paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    def text_to_image(self, text, title=None):
        img   = Image.new("L", (self.width, self.height), 255)
        draw  = ImageDraw.Draw(img)
        font  = self._get_font(FONT_SIZE)
        tfont = self._get_font(28)

        x         = MARGIN_LEFT
        y         = MARGIN_TOP
        max_width = self.width - MARGIN_LEFT - MARGIN_RIGHT
        lh        = int(FONT_SIZE * LINE_SPACING)

        if title:
            draw.text((x, y), title, font=tfont, fill=0)
            y += int(28 * LINE_SPACING) + 10
            draw.line([(x, y), (self.width - MARGIN_RIGHT, y)], fill=0, width=1)
            y += 15

        words = text.split()
        line  = []
        for word in words:
            test = " ".join(line + [word])
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] <= max_width:
                line.append(word)
            else:
                if line:
                    draw.text((x, y), " ".join(line), font=font, fill=0)
                    y += lh
                    if y > self.height - MARGIN_BOTTOM:
                        break
                line = [word]
        if line and y <= self.height - MARGIN_BOTTOM:
            draw.text((x, y), " ".join(line), font=font, fill=0)

        return img

    def show_image(self, img):
        img = img.rotate(90, expand=True)
        img = img.convert("RGB").convert("L")
        img.save(TMP_BMP, format="BMP")
        subprocess.run(
            [DRIVER, VCOM, MODE, TMP_BMP],
            check=True
        )

    def show_text(self, text, title=None):
        img = self.text_to_image(text, title)
        self.show_image(img)

    def clear(self):
        img = Image.new("L", (self.width, self.height), 255)
        self.show_image(img)

if __name__ == "__main__":
    d = EinkDisplay()
    print("Rendering test page...")
    d.show_text(
        "The quick brown fox jumps over the lazy dog. " * 20,
        title="KindlePi Display Test"
    )
    print("Done")
