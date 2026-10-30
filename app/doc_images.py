"""The pictures a document prints: fetch them once, keep them, draw them.

A quote used to be a list of card names; an order sheet has a picture of each
card so the right card goes in the box. Both documents now print the
photographs, and both get them the same way - which is what this file is for:

  * every picture is a URL on the document, so a document can be saved and
    printed again weeks later;
  * a picture is downloaded once and kept in a cache folder keyed by its
    address, so reprinting reads no shop at all;
  * a picture that cannot be fetched costs that row its photograph and
    nothing else - a broken image must never stop a thirty-card sheet.

Nothing here talks about quotes or orders: it takes URLs and gives back files,
draws a box, and says whether the picture was there.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from PIL import Image

#: What the shop is told when a picture is fetched. A browser's own string
#: would be a lie; the shops that matter serve these to anything.
USER_AGENT = "AlexCollect document sheet"

#: Where the pictures are kept between prints, inside the documents folder.
CACHE_DIRNAME = ".images"

#: The shape of a trading card, so a drawn picture is the shape of the thing
#: being packed.
CARD_RATIO = 1.4


def picture_urls(items):
    """Every picture the document needs, once each, in the order of the rows.

    ``items`` is a list of rows that may carry ``image`` - a URL, or the
    ``{"src": ...}`` shape a shop answers with.
    """
    urls = []
    for item in items or []:
        url = url_of(item)
        if url and url not in urls:
            urls.append(url)
    return urls


def url_of(item):
    """The picture address on one row, whichever shape it arrived in."""
    item = item or {}
    image = item.get("image")
    if isinstance(image, dict) and str(image.get("src") or "").strip():
        return str(image["src"]).strip()
    if isinstance(image, str):
        return image.strip()
    return ""


def cache_name(url):
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()[:20] + ".img"


def _download(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_images(urls, folder, timeout=20, progress=None, opener=None):
    """Download the pictures into ``folder``'s cache; returns ``{url: path}``.

    A picture that cannot be fetched is simply not in the answer; the caller
    draws a "no photo" box in its place and counts it.
    """
    cache = Path(str(folder)) / CACHE_DIRNAME
    opener = opener or _download
    found = {}
    urls = [url for url in (urls or []) if str(url or "").strip()]
    for index, url in enumerate(urls, 1):
        target = cache / cache_name(url)
        if target.is_file() and target.stat().st_size:
            found[url] = target
        else:
            try:
                cache.mkdir(parents=True, exist_ok=True)
                data = opener(url, timeout)
                if data:
                    #  Written beside the name and moved into place, so a
                    #  download cut off halfway is never read back as a
                    #  complete picture.
                    partial = target.with_suffix(".part")
                    partial.write_bytes(data)
                    partial.replace(target)
                    found[url] = target
            except Exception:            # noqa: BLE001 - one bad picture
                pass
        if progress is not None:
            try:
                progress(index, len(urls))
            except Exception:            # noqa: BLE001 - a progress bar
                pass
    return found


def load_picture(value):
    """A picture file, or an already-open image, as an image or ``None``."""
    if value is None:
        return None
    if isinstance(value, Image.Image):
        return value.convert("RGBA")
    try:
        picture = Image.open(str(value))
        picture.load()
    except (OSError, ValueError):
        return None
    return picture.convert("RGBA")


def draw_picture(page, x, y, width, height, picture, background, border,
                 note="no photo", note_colour=None):
    """Draw one card picture in its box; ``False`` when there is none.

    The picture is fitted inside the box rather than stretched, so a photograph
    of the wrong shape is not squashed - and the box is always drawn, so a
    missing picture looks like a missing picture instead of a gap.
    """
    box = [x, y, x + width, y + height]
    page.draw.rectangle(box, fill=background, outline=border)
    if picture is None:
        font = page.font(6.4)
        page.draw.text((x + (width - page.text_width(note, font)) / 2,
                        y + height / 2 - page.pt(4)), note, font=font,
                       fill=note_colour or border)
        return False
    copy = picture.copy()
    copy.thumbnail((max(1, width - page.pt(3)), max(1, height - page.pt(3))),
                   Image.LANCZOS)
    page.image.paste(copy, (int(x + (width - copy.width) / 2),
                            int(y + (height - copy.height) / 2)),
                     copy if copy.mode == "RGBA" else None)
    return True
