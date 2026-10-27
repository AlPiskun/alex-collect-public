"""Draw the proposed photo-replacement window as a PNG.

This is a design sketch, not the app: it renders the layout so the flow can
be agreed before any Tk code is written. Run it to regenerate the image:

    python docs/mockups/photo-replace-mockup.py

The 3x3 sheets and the card faces are drawn here, so no scan files are needed.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "photo-replace-flow.png"

W, H = 1200, 960

BG = (243, 244, 246)
PANEL = (255, 255, 255)
BORDER = (214, 219, 226)
SOFT = (249, 250, 252)
TEXT = (28, 33, 40)
MUTED = (108, 117, 129)
FAINT = (158, 166, 176)
ACCENT = (47, 111, 208)
ACCENT_DARK = (33, 86, 168)
ACCENT_SOFT = (232, 240, 252)
OK = (28, 138, 88)
OK_SOFT = (226, 244, 234)
DARK = (22, 22, 24)
DARK_LINE = (64, 64, 70)

FONTS = Path("/usr/share/fonts/truetype/dejavu")


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:                                    # pragma: no cover
        return ImageFont.load_default()


F_TITLE = font(21, True)
F_H = font(14, True)
F_STRONG = font(12, True)
F_BODY = font(11)
F_SMALL = font(10)
F_TINY = font(9)
F_BADGE = font(8, True)


def text(draw, xy, s, f, fill=TEXT, anchor="la"):
    draw.text(xy, s, font=f, fill=fill, anchor=anchor)


def wrap(draw, s, f, width):
    """Break a string into lines that fit ``width`` pixels."""
    words, lines, line = s.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def rr(draw, box, r=10, fill=PANEL, outline=BORDER, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline,
                           width=width)


def dashed(draw, box, color=BORDER, dash=6, gap=4, width=1):
    x0, y0, x1, y1 = box
    for x in range(int(x0), int(x1), dash + gap):
        draw.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        draw.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(int(y0), int(y1), dash + gap):
        draw.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        draw.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def pill(draw, xy, s, f=F_BADGE, fg=ACCENT, bg=ACCENT_SOFT):
    """A small rounded label sized to its text."""
    x, y = xy
    w = draw.textlength(s, font=f) + 12
    h = 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=bg)
    text(draw, (x + w / 2, y + h / 2), s, f, fg, anchor="mm")
    return w


def card_face(name, set_line, hue, size=(300, 400)):
    """A stand-in for a card photo, so the sketch needs no scan files."""
    image = Image.new("RGB", size, (238, 233, 222))
    d = ImageDraw.Draw(image)
    w, h = size
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=12, outline=(196, 186, 166),
                        width=3)
    d.rectangle((10, 10, w - 11, int(h * 0.24)), fill=hue)
    d.ellipse((w / 2 - 26, 26, w / 2 + 26, 78), fill=(250, 248, 242))
    d.ellipse((w / 2 - 14, 40, w / 2 + 14, 68), fill=hue)
    lines = wrap(d, name, font(30, True), w - 40)
    y = int(h * 0.42)
    for line in lines[:3]:
        d.text((w / 2, y), line, font=font(30, True), fill=(38, 34, 28),
               anchor="ma")
        y += 34
    y += 6
    for line in wrap(d, set_line, font(19), w - 40)[:3]:
        d.text((w / 2, y), line, font=font(19), fill=(88, 80, 68), anchor="ma")
        y += 24
    d.rectangle((10, h - 60, w - 11, h - 11), fill=hue)
    d.text((w / 2, h - 35), "CARD", font=font(18, True), fill=(250, 248, 242),
           anchor="mm")
    return image


def fit(image, box, radius=6):
    """Scale ``image`` into ``box`` (w, h) keeping its aspect, centred."""
    bw, bh = box
    copy = image.copy()
    copy.thumbnail((bw, bh), Image.LANCZOS)
    holder = Image.new("RGB", (bw, bh), BG)
    holder.paste(copy, ((bw - copy.width) // 2, (bh - copy.height) // 2))
    return holder


def blank_tile(box):
    tile = Image.new("RGB", box, DARK)
    d = ImageDraw.Draw(tile)
    d.rectangle((0, 0, box[0] - 1, box[1] - 1), outline=DARK_LINE)
    d.text((box[0] / 2, box[1] / 2), "empty", font=F_TINY, fill=(96, 96, 104),
           anchor="mm")
    return tile


FRONT_SHEET = {
    1: card_face("Gretzky", "1979-80 OPC #18", (37, 92, 168)),
    2: card_face("Lemieux", "1985-86 OPC #9", (176, 58, 48)),
    3: card_face("Roy", "1986-87 OPC #53", (34, 132, 96)),
    5: card_face("Yzerman", "1984-85 OPC #29", (128, 74, 158)),
    7: card_face("Hull", "1958-59 Topps #8", (188, 122, 38)),
    9: card_face("Orr", "1966-67 Topps #35", (44, 52, 72)),
}
BACK_SHEET = {
    1: card_face("Gretzky", "back", (37, 92, 168)),
    2: card_face("Lemieux", "back", (176, 58, 48)),
    3: card_face("Roy", "back", (34, 132, 96)),
    5: card_face("Yzerman", "back", (128, 74, 158)),
    7: card_face("Hull", "back", (188, 122, 38)),
    9: card_face("Orr", "back", (44, 52, 72)),
}


def sheet_grid(canvas, origin, tiles, thumb=(74, 98), gap=8):
    """Draw one 3x3 sheet in reading order; empty slots stay black."""
    x0, y0 = origin
    for position in range(1, 10):
        row, col = divmod(position - 1, 3)
        x = x0 + col * (thumb[0] + gap)
        y = y0 + row * (thumb[1] + gap)
        art = tiles.get(position)
        if art is None:
            canvas.paste(blank_tile(thumb), (x, y))
        else:
            canvas.paste(fit(art, thumb), (x, y))


def main():
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)

    # ---------------------------------------------------------------- header
    text(draw, (24, 20), "Replace card photos", F_TITLE)
    text(draw, (24, 48), "Start from the sheets you scanned - not from a card "
         "name.", F_SMALL, MUTED)
    for label, box, fill, fg, outline in (
            ("Open replacements folder", (830, 22, 1000, 54), PANEL, TEXT, BORDER),
            ("Add sheets...", (1016, 22, 1176, 54), ACCENT, PANEL, ACCENT)):
        rr(draw, box, 8, fill, outline)
        text(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), label,
             F_STRONG, fg, anchor="mm")

    # ----------------------------------------------------------- left panel
    rr(draw, (20, 84, 470, 936), 12)
    text(draw, (40, 102), "Your sheets", F_H)
    text(draw, (450, 106), "2 sheets \u00b7 12 images", F_SMALL, MUTED, "ra")

    dashed(draw, (40, 132, 450, 208), (188, 196, 206), 7, 5)
    text(draw, (245, 158), "Drop the scans here", F_STRONG, TEXT, "mm")
    text(draw, (245, 178), "or click to choose - front and back, any order",
         F_SMALL, MUTED, "mm")

    for label, badge, count, top, tiles, badge_fg, badge_bg in (
            ("Scan-01.jpg", "FRONT", "6 of 9 slots", 226, FRONT_SHEET,
             ACCENT, ACCENT_SOFT),
            ("Scan-02.jpg", "BACK", "6 of 9 slots", 580, BACK_SHEET,
             OK, OK_SOFT)):
        text(draw, (40, top), label, F_STRONG)
        used = pill(draw, (40 + draw.textlength(label, font=F_STRONG) + 10,
                           top + 1), badge, F_BADGE, badge_fg, badge_bg)
        text(draw, (450, top + 3), count, F_SMALL, MUTED, "ra")
        sheet_grid(canvas, (40, top + 24), tiles)
        text(draw, (int(40 + 3 * 82 - 8), top + 24 + 3 * 98 + 16 - 98),
             "", F_TINY)
        # right-hand notes beside the grid
        note_x = 40 + 3 * 74 + 2 * 8 + 18
        notes = ("Drag a slot onto another card to correct the order."
                 if badge == "FRONT" else
                 "Backs pair with fronts by slot until you change it.")
        y = top + 30
        for line in wrap(draw, notes, F_TINY, 450 - note_x - 6)[:5]:
            text(draw, (note_x, y), line, F_TINY, FAINT)
            y += 14

    # ---------------------------------------------------------- right panel
    rr(draw, (490, 84, 1180, 936), 12)
    text(draw, (510, 102), "Assign each image to a card", F_H)
    for i, line in enumerate(wrap(
            draw, "The photo beside each card is its current photo on your "
            "website, so a card is matched by eye - a filename is never the "
            "thing you have to read.", F_SMALL, 640)):
        text(draw, (510, 124 + i * 15), line, F_SMALL, MUTED)

    # -- row 1: assigned, front and back both in hand
    rr(draw, (510, 158, 1160, 292), 10, PANEL, BORDER)
    canvas.paste(fit(FRONT_SHEET[1], (74, 98)), (526, 176))
    text(draw, (526, 280), "Slot 1 \u00b7 front", F_TINY, MUTED)
    text(draw, (614, 222), "\u2192", font(20), FAINT, "mm")
    canvas.paste(fit(card_face("Gretzky", "1979-80 OPC #18",
                               (37, 92, 168)), (74, 98)), (648, 176))
    text(draw, (740, 180), "Wayne Gretzky 1979-80 O-Pee-Chee #18", F_STRONG)
    text(draw, (740, 200), "now: gretzky-front.webp + gretzky-back.webp",
         F_SMALL, MUTED)
    pill(draw, (740, 218), "front + back ready", F_BADGE, OK, OK_SOFT)
    pill(draw, (852, 218), "matches its own photo", F_BADGE, ACCENT, ACCENT_SOFT)
    rr(draw, (1040, 176, 1144, 204), 8, PANEL, BORDER)
    text(draw, (1092, 190), "Change", F_SMALL, TEXT, "mm")
    rr(draw, (1040, 210, 1144, 238), 8, PANEL, BORDER)
    text(draw, (1092, 224), "Skip", F_SMALL, MUTED, "mm")

    # -- row 2: searching, candidates carry their own photo
    rr(draw, (510, 302, 1160, 512), 10, PANEL, BORDER)
    canvas.paste(fit(FRONT_SHEET[7], (74, 98)), (526, 320))
    text(draw, (526, 424), "Slot 7 \u00b7 front", F_TINY, MUTED)
    rr(draw, (648, 320, 1006, 352), 8, SOFT, ACCENT, 2)
    text(draw, (660, 336), "hull", F_BODY, TEXT, "lm")
    text(draw, (1006, 336), "your card list", F_TINY, FAINT, "rm")
    rr(draw, (1016, 320, 1104, 352), 8, ACCENT, ACCENT)
    text(draw, (1060, 336), "Search", F_SMALL, PANEL, "mm")
    candidates = (
        ("Bobby Hull 1958-59 Topps #8", "1 in stock", (188, 122, 38)),
        ("Bobby Hull 1962-63 Topps #33", "1 in stock", (150, 96, 30)),
        ("Dennis Hull 1965-66 Topps #72", "1 in stock", (120, 110, 40)),
    )
    for i, (title, stock, hue) in enumerate(candidates):
        x = 648 + i * 174
        rr(draw, (x, 364, x + 162, 496), 8, SOFT, BORDER)
        canvas.paste(fit(card_face(title.split()[0] + " " + title.split()[1],
                                   "current photo", hue), (58, 78)), (x + 8, 374))
        text(draw, (x + 74, 380), "current", F_TINY, FAINT)
        text(draw, (x + 74, 394), "photo", F_TINY, FAINT)
        y = 428
        for line in wrap(draw, title, F_TINY, 148)[:3]:
            text(draw, (x + 8, y), line, F_TINY, TEXT)
            y += 12
        text(draw, (x + 8, 482), stock, F_TINY, MUTED)

    # -- row 3: waiting
    rr(draw, (510, 522, 1160, 660), 10, SOFT, BORDER)
    canvas.paste(fit(FRONT_SHEET[9], (74, 94)), (526, 534))
    text(draw, (526, 638), "Slot 9 \u00b7 front", F_TINY, MUTED)
    text(draw, (648, 556), "Not assigned yet", F_STRONG)
    text(draw, (648, 576), "Search a card, or leave it - an image you skip is "
         "not replaced.", F_SMALL, MUTED)
    rr(draw, (1016, 540, 1144, 568), 8, ACCENT, ACCENT)
    text(draw, (1080, 554), "Search a card...", F_SMALL, PANEL,
         "mm")

    # ------------------------------------------------------------- bottom
    text(draw, (510, 678), "Ready to replace", F_H)
    text(draw, (1160, 682), "3 cards ready \u00b7 5 of 12 images assigned",
         F_SMALL, MUTED, "ra")
    ready = (
        ("Gretzky 1979-80 O-Pee-Chee #18", "front + back", (37, 92, 168)),
        ("Lemieux 1985-86 O-Pee-Chee #9", "front + back", (176, 58, 48)),
        ("Roy 1986-87 O-Pee-Chee #53", "front only", (34, 132, 96)),
    )
    for i, (title, sides, hue) in enumerate(ready):
        x = 510 + i * 220
        rr(draw, (x, 700, x + 210, 772), 8, SOFT, BORDER)
        canvas.paste(fit(card_face(title.split()[0], "ready", hue), (44, 58)),
                     (x + 8, 707))
        y = 710
        for line in wrap(draw, title, F_TINY, 140)[:3]:
            text(draw, (x + 62, y), line, F_TINY, TEXT)
            y += 12
        text(draw, (x + 62, 752), sides, F_TINY, OK)
    rr(draw, (510, 786, 1160, 854), 8, ACCENT_SOFT, (206, 222, 246))
    text(draw, (528, 802), "Applying saves each pair in replacements/ under the "
         "card's own photo names,", F_SMALL, TEXT)
    text(draw, (528, 820), "then uploads it to the website and updates the "
         "CanadianShopper listing. One card at a time,", F_SMALL, TEXT)
    text(draw, (528, 838), "with a result line per card - a failure stops that "
         "card, not the batch.", F_SMALL, TEXT)

    rr(draw, (1000, 864, 1160, 900), 8, PANEL, BORDER)
    text(draw, (1080, 882), "Cancel", F_SMALL, TEXT, "mm")
    rr(draw, (910, 864, 986, 900), 8, ACCENT, ACCENT)
    text(draw, (948, 882), "Replace 3", F_SMALL, PANEL, "mm")

    # scroll hint
    rr(draw, (1152, 528, 1160, 640), 4, (228, 232, 238))
    rr(draw, (1152, 528, 1160, 576), 4, (188, 196, 206))

    canvas.save(OUT)
    print("wrote", OUT, canvas.size)


if __name__ == "__main__":
    main()
