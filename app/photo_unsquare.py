"""Take the square padding back off a card photo.

CanadianShopper renders every product photo in a square box with
``object-cover``, so the photos it is given are padded onto a white square
first (``make-square.py``, and the batch's staging step): the card sits in the
middle of a square with bands of background above and below it. That is right
for the storefront and wrong everywhere else - the website's product page
shows the picture as it is, so a square with white bands looks like a scan of
a card rather than the card.

This is the rule that undoes it, and it is deliberately conservative:

  * the background is read from the picture's own border, not assumed to be
    white, because a card photographed on black gets the same treatment;
  * the card is the bounding box of everything that differs from that
    background, so a white band *inside* the card does not end the crop -
    only the padding around the card does;
  * a margin is left around the card, a fraction of its shorter side, so the
    card's own edge is never shaved off;
  * a picture with no padding, or one that is nothing but background, comes
    back unchanged and says so - the caller reports it rather than inventing
    a crop.

Nothing here writes a file or talks to a site: it takes a PIL image and gives
back an image, so it can be tested with a drawn square.
"""
from __future__ import annotations

try:
    from PIL import Image, ImageChops
except ImportError:                                   # pragma: no cover
    Image = ImageChops = None

#: How different a pixel has to be from the background to count as the card.
#: High enough that JPEG noise in a white band is not the card, low enough that
#: a card's own pale border still is.
TOLERANCE = 18

#: How much room to leave around the card, as a fraction of its shorter side.
#: Two percent of a 600-pixel card is twelve pixels - enough that a sliver of
#: the card's edge is not cut off, small enough to look cropped.
MARGIN = 0.02

#: The smallest crop worth making. A box smaller than this is one stray pixel
#: (a speck of dust on a white sheet), and cropping to it would throw the card
#: away.
MIN_SIDE = 24

#: How much of the border has to be the background before the picture is
#: called padded. A padded photo's border is padding all the way round; a photo
#: of a card with no padding has the card's own printed edge there, which is
#: not uniform - and cropping that would cut the card's border off.
BORDER_UNIFORM = 0.75

#: How square a picture has to be before there is any padding to undo. The
#: storefront's square is what this takes off, so a picture that is already the
#: shape of a card has nothing to take off - and cropping it would be guessing.
SQUARE_TOLERANCE = 0.06

#: The shapes a trading card comes in (tall side over short side), portrait or
#: landscape. What is left inside the padding has to be one of them: a square
#: or a wide letterbox inside a square is something else in the picture - a
#: glare, a sleeve, a second card - and the crop would be wrong.
CARD_RATIOS = (1.15, 1.95)


class SquareError(Exception):
    """An image that cannot be measured at all."""


def background(image):
    """The colour of the picture's border, as ``(r, g, b)``.

    Taken as the median of a thin strip all the way round rather than a single
    corner: a corner can be the card itself (a picture with no padding at all),
    while the median of the whole border is the padding whenever there is any.
    """
    if Image is None:                                 # pragma: no cover
        raise SquareError("Pillow is required to crop the square off a photo.")
    image = image.convert("RGB")
    width, height = image.size
    strip = max(1, min(6, width // 50 or 1, height // 50 or 1))
    pixels = []
    for box in ((0, 0, width, strip), (0, height - strip, width, height),
                (0, 0, strip, height), (width - strip, 0, width, height)):
        pixels.extend(image.crop(box).getdata())
    if not pixels:
        return (0, 0, 0)
    return tuple(int(sorted(pixel[band] for pixel in pixels)[len(pixels) // 2])
                 for band in range(3))


def border_share(image, colour, tolerance=TOLERANCE):
    """How much of the picture's border is ``colour``, as a fraction.

    The number that tells padding from the card itself: a padded photo is
    uniform background all the way round, while the border of an unpadded card
    is the card's own printed edge - which is what must not be cropped.
    """
    image = image.convert("RGB")
    width, height = image.size
    strip = max(1, min(6, width // 50 or 1, height // 50 or 1))
    total = matching = 0
    for box in ((0, 0, width, strip), (0, height - strip, width, height),
                (0, 0, strip, height), (width - strip, 0, width, height)):
        for pixel in image.crop(box).getdata():
            total += 1
            if max(abs(pixel[band] - colour[band]) for band in range(3)) \
                    <= tolerance:
                matching += 1
    return (matching / total) if total else 0.0


def card_box(image, tolerance=TOLERANCE):
    """Where the card is: ``(left, top, right, bottom)``, or ``None``.

    ``None`` means the whole picture is background - there is no card in it -
    which is a thing the caller has to be able to say rather than crop to
    nothing.
    """
    if Image is None:                                 # pragma: no cover
        raise SquareError("Pillow is required to crop the square off a photo.")
    image = image.convert("RGB")
    pad = Image.new("RGB", image.size, background(image))
    difference = ImageChops.difference(image, pad).convert("L")
    mask = difference.point(lambda value: 255 if value > tolerance else 0)
    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    if (right - left) < MIN_SIDE or (bottom - top) < MIN_SIDE:
        #  A speck, not a card: the padding is the picture.
        return None
    return box


def de_square(image, tolerance=TOLERANCE, margin=MARGIN):
    """``(image, measure)`` - the card without its square padding.

    ``measure`` says what was done, so a caller can report it honestly:

        {"padded": True, "box": (l, t, r, b), "before": (w, h),
         "after": (w, h), "why": ""}

    ``padded`` is False when the picture was already the card's own shape (or
    was thrown back unchanged), and ``why`` says which of the two it was.
    """
    if Image is None:                                 # pragma: no cover
        raise SquareError("Pillow is required to crop the square off a photo.")
    image = image.convert("RGB")
    before = image.size
    measure = {"padded": False, "box": None, "before": before,
               "after": before, "why": ""}
    width, height = before
    if abs(width - height) > SQUARE_TOLERANCE * max(width, height):
        measure["why"] = ("it is not square, so there is no padding to undo - "
                          "it is already the shape of the picture")
        return image, measure
    colour = background(image)
    if border_share(image, colour, tolerance) < BORDER_UNIFORM:
        #  The edge is the card's own, not a padded margin: cropping to what
        #  differs from it would cut into the card.
        measure["why"] = ("its edge is the card itself - there is no padding "
                          "to take off")
        return image, measure
    box = card_box(image, tolerance=tolerance)
    if box is None:
        measure["why"] = "there is no card on it - every pixel is background"
        return image, measure
    card_w, card_h = box[2] - box[0], box[3] - box[1]
    long_side, short_side = max(card_w, card_h), max(1, min(card_w, card_h))
    ratio = long_side / float(short_side)
    if not (CARD_RATIOS[0] <= ratio <= CARD_RATIOS[1]):
        measure["why"] = ("the shape inside the padding is %dx%d, which is not "
                          "a card's shape - left as it is" % (card_w, card_h))
        return image, measure
    left, top, right, bottom = box
    if left <= 1 and top <= 1 and right >= width - 1 and bottom >= height - 1:
        measure["why"] = "it had no padding - it is already the card's shape"
        return image, measure
    #  Room to breathe around the card, clamped to the picture.
    pad = max(2, int(round(min(right - left, bottom - top) * margin)))
    box = (max(0, left - pad), max(0, top - pad),
           min(width, right + pad), min(height, bottom + pad))
    cropped = image.crop(box)
    measure.update({"padded": True, "box": box, "after": cropped.size,
                    "why": ""})
    return cropped, measure


def shape_text(size):
    """``600x700`` in the words a person reads a picture size in."""
    try:
        width, height = size
    except (TypeError, ValueError):
        return "unknown size"
    return "%dx%d" % (int(width), int(height))
