"""Regenerate docs/how-it-works.png (a simple architecture overview).

Run from the project folder:

    .venv\\Scripts\\python.exe docs\\make_diagram.py

Pillow is already a runtime dependency for the tray icon.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "how-it-works.png")

W, H = 1600, 820
BG = (246, 248, 251)
INK = (15, 23, 42)
MUTED = (71, 85, 105)
LINE = (203, 213, 225)
CARD = (255, 255, 255)
BLUE = (59, 130, 246)
BLUE_SOFT = (219, 234, 254)
GREEN = (22, 163, 74)
GREEN_SOFT = (220, 252, 231)
AMBER = (217, 119, 6)
AMBER_SOFT = (254, 243, 199)


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def card(d, box, fill=CARD, outline=LINE, radius=22, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow(d, start, end, color=BLUE, width=4):
    d.line((start, end), fill=color, width=width)
    # arrow head
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        pts = [(x2, y2), (x2 - 16 * direction, y2 - 9),
               (x2 - 16 * direction, y2 + 9)]
    else:
        direction = 1 if y2 > y1 else -1
        pts = [(x2, y2), (x2 - 9, y2 - 16 * direction),
               (x2 + 9, y2 - 16 * direction)]
    d.polygon(pts, fill=color)


def label(d, xy, text, size=22, fill=INK, bold=False, anchor="la"):
    d.text(xy, text, font=font(size, bold), fill=fill, anchor=anchor)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    label(d, (70, 54), "How Controlify works", 52, INK, True)
    label(d, (72, 122), "Two local signals, two gentle actions. Nothing leaves your PC.",
          24, MUTED)

    # -- input cards --------------------------------------------------------
    card(d, (70, 230, 470, 370))
    d.ellipse((100, 258, 150, 308), fill=GREEN)
    d.ellipse((117, 275, 133, 291), fill=(255, 255, 255))
    label(d, (168, 256), "Spotify", 28, INK, True)
    label(d, (168, 292), "Media session + window title", 20, MUTED)
    label(d, (100, 330), "Is this an ad, or a track?", 20, MUTED)

    card(d, (70, 450, 470, 590))
    d.rounded_rectangle((100, 478, 150, 528), radius=12, fill=AMBER)
    label(d, (168, 476), "Wispr Flow", 28, INK, True)
    label(d, (168, 512), "config.json (read-only)", 20, MUTED)
    label(d, (100, 550), "Is dictation active right now?", 20, MUTED)

    # -- centre -------------------------------------------------------------
    card(d, (650, 300, 980, 520), fill=BLUE_SOFT, outline=BLUE, width=3)
    label(d, (815, 336), "Controlify", 34, INK, True, anchor="ma")
    label(d, (815, 380), "decides, then acts", 20, MUTED, anchor="ma")
    # a tiny speaker mark
    d.rounded_rectangle((770, 420, 796, 466), radius=6, fill=BLUE)
    d.polygon([(796, 432), (824, 414), (824, 472), (796, 454)], fill=BLUE)
    for r in (18, 30):
        d.arc((824 - r, 443 - r, 824 + r, 443 + r), start=-55, end=55,
              fill=BLUE, width=4)
    label(d, (882, 443), "local only", 20, BLUE, True, anchor="lm")

    # -- output cards -------------------------------------------------------
    card(d, (1160, 230, 1530, 370))
    d.ellipse((1190, 258, 1240, 308), fill=GREEN_SOFT)
    d.ellipse((1208, 276, 1222, 290), fill=GREEN)
    label(d, (1258, 256), "Ad mute", 28, INK, True)
    label(d, (1258, 292), "Spotify session volume = 0", 20, MUTED)
    label(d, (1190, 330), "Restored when the break ends", 20, MUTED)

    card(d, (1160, 450, 1530, 590))
    d.ellipse((1190, 478, 1240, 528), fill=BLUE_SOFT)
    d.polygon([(1205, 490), (1226, 503), (1205, 516)], fill=BLUE)
    label(d, (1258, 476), "Dictation pause", 28, INK, True)
    label(d, (1258, 512), "Spotify's own pause call", 20, MUTED)
    label(d, (1190, 550), "Resumed only if we paused it", 20, MUTED)

    # -- arrows -------------------------------------------------------------
    arrow(d, (470, 300), (650, 360))
    arrow(d, (470, 520), (650, 460))
    arrow(d, (980, 360), (1160, 300))
    arrow(d, (980, 460), (1160, 520))

    # -- bottom strip -------------------------------------------------------
    d.rounded_rectangle((70, 660, 1530, 760), radius=20, fill=(255, 255, 255),
                        outline=LINE, width=2)
    label(d, (100, 682), "Tray icon & settings window", 22, INK, True)
    label(d, (100, 716),
          "Toggle ads, dictation pause, cue and notification; settings live in settings.json",
          19, MUTED)
    label(d, (1500, 700), "No network  ·  No telemetry  ·  No account",
          20, GREEN, True, anchor="ra")

    img.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
