"""Write the drawn pages as a PDF, with the card names clickable.

Pillow can save a list of images as a PDF, and that is how this app started:
no new dependency, nothing to install. But an image has no links in it, and
"the card's name opens the card's page" is one of the few things a PDF can do
that a picture cannot - so the last step is done here instead.

The file this writes is a small, ordinary PDF: a catalogue, a page per sheet,
each page a full-bleed JPEG (the same picture Pillow would have saved, at the
same quality) and, where the page says so, a link annotation over a rectangle.
Nothing else - no fonts, no transparency, no compression of the structure -
so the file can be read by every viewer, and checked here without one.
"""
from __future__ import annotations

import io
import urllib.parse
from pathlib import Path

#: A4 in PostScript points, which is what a PDF page is measured in.
PAGE_POINTS = (595.276, 841.890)


def _pdf_uri(url):
    """A URL as an ASCII string a PDF can carry, with the characters that
    would end the string - or the PDF's own syntax - escaped."""
    text = str(url or "").strip()
    if not text:
        return ""
    safe = ":/?#[]@!$&'()*+,;=%~"
    text = urllib.parse.quote(text, safe=safe)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_text(text):
    """Text a PDF string can carry as it reads - only its own syntax escaped.

    A title is shown in the reader's window, not opened, so it is escaped
    rather than percent-encoded: spaces stay spaces.
    """
    return (str(text or "").replace("\\", "\\\\").replace("(", "\\(")
            .replace(")", "\\)"))


def _rect(pixels, page_size, dpi):
    """A rectangle given in pixels from the top-left, as PDF points.

    A PDF measures from the bottom-left corner of the page, so the two
    vertical edges swap over - which is the whole of the conversion.
    """
    x0, y0, x1, y1 = pixels
    width, height = page_size
    left = min(x0, x1) * 72.0 / dpi
    right = max(x0, x1) * 72.0 / dpi
    top = height - min(y0, y1) * 72.0 / dpi
    bottom = height - max(y0, y1) * 72.0 / dpi
    return (round(left, 2), round(bottom, 2), round(right, 2), round(top, 2))


def write(pages, path, links=None, quality=92, dpi=200, title=""):
    """Write ``pages`` (Pillow images) to ``path``; returns the page count.

    ``links`` maps a page index to ``(x0, y0, x1, y1, url)`` tuples in pixels
    at ``dpi``, measured from the top-left of that page.
    """
    links = links or {}
    if not pages:
        raise ValueError("a PDF needs at least one page")
    target = Path(str(path))

    #  The objects, in the order they are numbered. Object 1 is the catalogue
    #  and object 2 the page tree; every page then adds a page, its content
    #  stream, and the picture itself.
    objects = [None, None]           # 1-based; filled below

    def add(body):
        objects.append(body)
        return len(objects)

    page_ids = []
    for index, image in enumerate(pages):
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        width_pt = image.width * 72.0 / dpi
        height_pt = image.height * 72.0 / dpi
        size = (width_pt, height_pt)

        image_id = add((
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            b"/Length %d >>\nstream\n" % (image.width, image.height, len(data))
        ) + data + b"\nendstream")

        content = ("q %.3f 0 0 %.3f 0 0 cm /Im0 Do Q\n"
                   % (width_pt, height_pt)).encode("ascii")
        content_id = add(b"<< /Length %d >>\nstream\n" % len(content)
                         + content + b"endstream")

        annots = []
        for entry in links.get(index, []):
            x0, y0, x1, y1, url = entry
            uri = _pdf_uri(url)
            if not uri:
                continue
            box = _rect((x0, y0, x1, y1), size, dpi)
            annots.append(add(
                ("<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] "
                 "/Border [0 0 0] /A << /S /URI /URI (%s) >> >>"
                 % (box[0], box[1], box[2], box[3], uri)).encode("ascii")))

        parts = [
            b"<< /Type /Page /Parent 2 0 R",
            b" /MediaBox [0 0 %.3f %.3f]" % (width_pt, height_pt),
            b" /Resources << /XObject << /Im0 %d 0 R >> >>" % image_id,
            b" /Contents %d 0 R" % content_id,
        ]
        if annots:
            parts.append(b" /Annots ["
                         + b" ".join(b"%d 0 R" % number for number in annots)
                         + b"]")
        parts.append(b" >>")
        page_ids.append(add(b"".join(parts)))

    objects[0] = (b"<< /Type /Catalog /Pages 2 0 R >>")
    objects[1] = (b"<< /Type /Pages /Kids ["
                  + b" ".join(b"%d 0 R" % number for number in page_ids)
                  + b"] /Count %d >>" % len(page_ids))
    if title:
        info_id = add(("<< /Title (%s) /Producer (Alex Collect) >>"
                       % _pdf_text(title)).encode("latin-1", "replace"))
    else:
        info_id = 0

    #  The file: a header, the objects with their offsets remembered for the
    #  cross-reference table, that table, and the trailer pointing at the
    #  catalogue.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for number, body in enumerate(objects, 1):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number
        out += body
        out += b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for number in range(1, len(objects) + 1):
        out += b"%010d 00000 n \n" % offsets[number]
    trailer = b"trailer\n<< /Size %d /Root 1 0 R" % (len(objects) + 1)
    if info_id:
        trailer += b" /Info %d 0 R" % info_id
    out += trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % start
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(out))
    return len(page_ids)


def read_links(path):
    """Every link in a PDF this module wrote, as ``(page, url)`` pairs.

    Not a general PDF reader - it looks for the annotation dictionaries this
    writer emits, in the order they appear - which is exactly what a test
    needs to prove a card's name carries the card's address.
    """
    data = Path(str(path)).read_bytes()
    links = []
    for chunk in data.split(b"/Type /Annot")[1:]:
        start = chunk.find(b"/URI (")
        if start < 0:
            continue
        start += len(b"/URI (")
        end = chunk.find(b")", start)
        while end > 0 and chunk[end - 1:end] == b"\\":
            end = chunk.find(b")", end + 1)
        links.append(chunk[start:end].decode("latin-1")
                     .replace("\\(", "(").replace("\\)", ")")
                     .replace("\\\\", "\\"))
    return links
