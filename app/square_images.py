#!/usr/bin/env python3
"""The square padding every photo of a card gets, in one place.

CanadianShopper's storefront draws each product photo in a square box with
``object-cover``, so a portrait photo has its top and bottom cut off. A file
padded onto a white square has nothing left for that box to crop - which is why
the picture has to be squared *before* it is uploaded, not after.

Three things do that padding, and they have to agree to the pixel:

* the bulk stage the plugin runs (``pad-and-upload.py``),
* ``make-square.py`` - the one behind ``SquareImages.bat`` and the panel's
  "Square up a photo..." button,
* this app's "use a picture from this computer" path, which squares the file
  the seller picked before the plugin hosts it.

They used to hold two copies of the routine; this is the one copy they share,
so a picture squared by the button is the same file a hand-run through
``SquareImages.bat`` would produce.

Nothing here decides *when* to square anything, opens a window, or touches the
site: it takes an open picture (or the bytes of a file) and gives one back.
"""
from __future__ import annotations

import io

try:
    from PIL import Image
except ImportError:  # pragma: no cover - reported by the callers that need it
    Image = None

#: What the manual route writes: JPEG on white. A PNG is available for a card
#: photographed with something behind it, but the shop's own photos are opaque.
DEFAULT_FORMAT = "jpeg"
DEFAULT_QUALITY = 88
WHITE = (255, 255, 255)


class SquareError(Exception):
    """A picture could not be squared, said in words rather than a traceback."""


def pad_to_square(im, bg=WHITE, keep_alpha=False, size=None):
    """Centre ``im`` on a square canvas of its own longest side.

    No resampling happens unless ``size`` asks for one: a 600x702 card becomes
    702x702 and the card keeps every pixel it had. The strips added at the top
    and bottom are ``bg`` (white, unless the caller wants a card that was cut
    out of a light background to keep its own transparency).
    """
    if Image is None:
        raise SquareError("Pillow is required to square a picture.")
    w, h = im.size
    side = max(w, h)
    if keep_alpha:
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        src = im.convert("RGBA")
    else:
        canvas = Image.new("RGB", (side, side), bg)
        src = im.convert("RGBA")
        flat = Image.new("RGBA", src.size, tuple(bg) + (255,))
        src = Image.alpha_composite(flat, src).convert("RGB")
    canvas.paste(src, ((side - w) // 2, (side - h) // 2))
    if size and size != side:
        canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def encode(img, fmt=DEFAULT_FORMAT, quality=DEFAULT_QUALITY):
    """``(bytes, mime type, extension)`` for a squared picture.

    ``webp`` matters as much as the other two: a card's photos on
    CanadianShopper are WebP, and a replacement is written *beside* the front
    it pairs with - two files that must share one extension and one format, or
    the pairing the plugin looks for is two names and two different pictures.
    """
    buf = io.BytesIO()
    kind = str(fmt or DEFAULT_FORMAT).lower()
    if kind == "png":
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", ".png"
    if kind == "webp":
        img.convert("RGB").save(buf, "WEBP", quality=quality, method=6,
                                optimize=True)
        return buf.getvalue(), "image/webp", ".webp"
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True,
                            progressive=True)
    return buf.getvalue(), "image/jpeg", ".jpg"


def format_for(name):
    """The format to write a replacement in, taken from the name it joins.

    ``.webp`` and ``.png`` are kept; anything else - a JPEG, a name with no
    suffix, a photo whose address says nothing - becomes a JPEG.
    """
    suffix = ""
    text = str(name or "")
    if "." in text.rsplit("/", 1)[-1]:
        suffix = "." + text.rsplit(".", 1)[-1].split("?")[0].lower()
    if suffix == ".webp":
        return "webp"
    if suffix == ".png":
        return "png"
    return DEFAULT_FORMAT


def square_bytes(source, fmt=DEFAULT_FORMAT, quality=DEFAULT_QUALITY,
                 bg=WHITE, keep_alpha=False, size=None):
    """One picture file, padded to a square, as bytes.

    Returns a small record rather than a bare blob, because the caller has to
    be able to say what it did: ``{"data", "mime", "ext", "before", "after",
    "padded"}`` - where ``before``/``after`` are the two sizes and ``padded``
    says whether anything was added at all (a picture that is already square
    keeps its pixels untouched).
    """
    if Image is None:
        raise SquareError("Pillow is required to square a picture.")
    try:
        with Image.open(source) as im:
            im.load()
            before = im.size
            square = pad_to_square(im, bg=bg, keep_alpha=keep_alpha,
                                   size=size or None)
            data, mime, ext = encode(square, fmt, quality)
            after = square.size
    except SquareError:
        raise
    except (OSError, ValueError) as exc:
        raise SquareError("That file could not be read as a picture: %s"
                          % exc) from exc
    return {"data": data, "mime": mime, "ext": ext, "before": before,
            "after": after, "padded": tuple(before) != tuple(after)}
