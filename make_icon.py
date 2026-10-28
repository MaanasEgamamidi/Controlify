"""Regenerate assets/controlify.png and assets/controlify.ico.

Run from the project folder:

    .venv\\Scripts\\python.exe make_icon.py

The PNG is used by the tray icon; the ICO is used for the settings window and
can be reused by shortcuts.  Both are committed so a fresh clone needs no
extra step.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

BG = (16, 20, 26, 255)          # near-black, matches the app's dark accent
BORDER = (47, 56, 72, 255)
FG = (245, 247, 250, 255)       # speaker
ACCENT = (108, 140, 255, 255)   # mute slash
SIZE = 1024


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded tile
    d.rounded_rectangle((28, 28, SIZE - 28, SIZE - 28), radius=230, fill=BG,
                        outline=BORDER, width=10)

    # Speaker body + cone (deliberately large: the tray renders this at 16 px)
    d.rounded_rectangle((240, 400, 350, 624), radius=30, fill=FG)
    d.polygon([(350, 452), (540, 320), (540, 704), (350, 572)], fill=FG)

    # Sound waves
    for r, w in ((110, 36), (200, 36)):
        d.arc((540 - r, 512 - r, 540 + r, 512 + r), start=-58, end=58,
              fill=FG, width=w)

    # Mute slash, with a dark gap so it reads at 16 px
    d.line((230, 750, 810, 274), fill=BG, width=130)
    d.line((230, 750, 810, 274), fill=ACCENT, width=76)
    return img


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    img = build()
    png = os.path.join(ASSETS, "controlify.png")
    ico = os.path.join(ASSETS, "controlify.ico")
    img.save(png)
    img.save(ico, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                         (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {png}")
    print(f"wrote {ico}")


if __name__ == "__main__":
    main()
