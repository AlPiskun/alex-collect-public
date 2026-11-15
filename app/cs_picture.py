#!/usr/bin/env python3
"""A picture on this computer becomes a photo on one CanadianShopper listing.

Why this exists
---------------
The listing editor could only offer photos that were already *somewhere*: the
batch's staged uploads, the rows the gallery already holds, or an address
pasted by hand. A card whose back was photographed separately - or a picture
that is simply new - had no way in. The seller had to square it by hand, upload
it in the vendor dashboard, and then point the listing at it.

What happens here, in the order the app does it
-----------------------------------------------
1. **Square it.** The picked file is padded onto a white square with the same
   routine ``SquareImages.bat`` uses (``square_images``), so it fits the
   storefront's square box without the top and bottom of the card being cut
   off.
2. **Name it the way the plugin names a card's pair** - ``<pair>-front-1.jpg``
   and ``<pair>-back-1.jpg``, from the filename of the front the listing shows
   now. The plugin identifies the site's existing ``-back`` row by that name,
   so a back named anything else is *added beside* the old one instead of
   replacing it (or, worse, is not recognised at all).
3. **Hand both files to the plugin's replace mode**, which uploads them (hosts
   them at ``/api/file/`` on CanadianShopper) and puts the front on the main
   photo and the back on the second photo.

A back is only ever one half of a pair, so a back replacement sends the front
the listing shows now *as well* - unchanged, downloaded from the listing - for
the plugin to pair it with. The front's picture stays the same; only its
address on the site is renewed.

Nothing here uses Tkinter or the network by itself: the app does the asking,
the plugin does the writing, and every rule in this file is testable without a
window and without a site.
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

import photo_replace
import square_images

#: The two photos a card has, in the order the shop shows them.
SLOTS = ("front", "back")

#: Where each one sits in the listing's gallery.
POSITION = {"front": 1, "back": 2}

#: What each slot is called when the app is talking to the seller.
SLOT_WORDS = {
    "front": "the front (the card's main photo)",
    "back": "the back (the second photo)",
}

#: Long enough for a card's title, short enough to stay a filename.
NAME_LIMIT = 60


class PictureError(Exception):
    """A picture could not be prepared, said in words rather than a traceback."""


def slot_words(slot):
    """``"the back (the second photo)"`` - the slot as a sentence says it."""
    return SLOT_WORDS.get(str(slot or "").lower(), "a photo")


def position(slot):
    """The gallery position the slot occupies (1 front, 2 back)."""
    return POSITION.get(str(slot or "").lower(), 0)


def slot_of(value):
    """``"front"``/``"back"`` from anything that says so, else ``""``."""
    text = str(value or "").strip().lower()
    if text in SLOTS:
        return text
    return photo_replace.side_of(text)


def _slug(text):
    """A filename-safe stem: letters, digits and single hyphens."""
    out = []
    for char in str(text or "").lower():
        if char.isalnum() and char.isascii():
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    stem = "".join(out).strip("-")
    return stem[:NAME_LIMIT].strip("-")


def _filename(url):
    """The last piece of a photo's address, without the query string."""
    path = urllib.parse.urlparse(str(url or "")).path
    return Path(urllib.parse.unquote(path)).name


def pair_name(front_url="", title=""):
    """The stem both of a card's photos share.

    Taken from the front the listing shows now, because that name is the one
    the plugin put on the site: ``.../dallas-smith-front.webp`` gives
    ``dallas-smith``. A name the filesystem could not hold - or no front photo
    at all - falls back to the listing's title, which the plugin matches the
    listing by anyway.

    Returns ``""`` when neither exists, so the caller can refuse rather than
    invent a name and have the plugin add a second back beside the first.
    """
    stem = photo_replace.pair_stem(_filename(front_url))
    if stem and not any(char in stem for char in '<>:"/\\|?*'):
        return stem
    return _slug(title)


def _folder(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def square_file(source, folder, pair="", slot="", like=""):
    """The picked picture, padded to a square, written beside the pair.

    ``like`` is the photo this one has to sit beside - the front the listing
    shows now - and only decides the *format*: a pair is two files of one kind
    with one extension, so a JPEG back beside a WebP front is a pair the
    plugin cannot match up.

    Returns ``{"path", "before", "after", "padded"}``: the file the plugin is
    given, the two sizes, and whether anything had to be added (a picture that
    is already square keeps every pixel it had).
    """
    source = Path(str(source or ""))
    if not source.is_file():
        raise PictureError("That picture is not on this computer any more: %s"
                           % source)
    fmt = square_images.format_for(like)
    try:
        record = square_images.square_bytes(source, fmt=fmt)
    except square_images.SquareError as exc:
        raise PictureError(str(exc)) from exc
    stem = _slug(pair) or _slug(source.stem) or "picture"
    slot = slot_of(slot)
    name = "%s-%s-square%s" % (stem, slot or "picture", record["ext"])
    target = _folder(folder) / name
    try:
        target.write_bytes(record["data"])
    except OSError as exc:
        raise PictureError("The squared picture could not be saved: %s"
                           % exc) from exc
    record["path"] = target
    return record


def _fetch(url):
    """The bytes at ``url`` - the default for :func:`download`."""
    request = urllib.request.Request(url, headers={"User-Agent":
                                                   "AlexCollect"})
    with urllib.request.urlopen(request, timeout=30) as answer:   # noqa: S310
        return answer.read()


def download(url, folder, pair="", fetch=None):
    """The front photo the listing shows now, saved so it can be paired.

    A card's back is one half of a front/back pair, and the plugin only
    replaces the row it can pair: so a back replacement sends the front the
    listing already shows. Its bytes are copied as they are - the picture does
    not change, and nothing is squared or re-encoded.
    """
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise PictureError(
            "This listing does not say which photo it shows as its front, so "
            "the back has nothing to be paired with. Nothing was written - "
            "run the listing read again, or replace the front first.")
    try:
        data = (fetch or _fetch)(url)
    except Exception as exc:                       # noqa: BLE001 - any failure
        raise PictureError(
            "The front photo could not be downloaded (%s), so the back has "
            "nothing to be paired with. Nothing was written." % exc) from exc
    if not data:
        raise PictureError(
            "The front photo came back empty from %s, so the back has nothing "
            "to be paired with. Nothing was written." % url)
    suffix = Path(_filename(url)).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
                      ".tif", ".tiff"):
        suffix = ".jpg"
    stem = _slug(pair) or "front"
    target = _folder(folder) / ("%s-front%s" % (stem, suffix))
    try:
        target.write_bytes(bytes(data))
    except OSError as exc:
        raise PictureError("The front photo could not be saved beside the "
                           "back: %s" % exc) from exc
    return target


def prepare(folder, pair, slot, picture, front_picture=None):
    """Write the files the plugin is given, and say which is which.

    ``picture`` is the squared picture of the slot being replaced.
    ``front_picture`` is the front the listing shows now, and it is required
    when the slot is the back: the plugin verifies that the two names differ
    only by ``-front``/``-back`` and refuses a pair that does not, so a back
    with no front beside it can never be replaced.

    Returns ``{"front": Path, "back": Path or None, "pair": pair}``. Both
    sources are checked before either target is written, so a failure leaves
    no half pair behind.
    """
    slot = slot_of(slot)
    if slot not in SLOTS:
        raise PictureError("That is not one of a card's two photos: %r" % slot)
    pair = str(pair or "").strip()
    if not pair:
        raise PictureError(
            "There is no name to file this picture under, and a photo the "
            "plugin cannot name is a photo it cannot place. Nothing was "
            "written.")
    picture = Path(str(picture or ""))
    if slot == "back":
        if front_picture is None:
            raise PictureError(
                "The back is one half of the card's pair, and the front it is "
                "paired with was not given, so the plugin could not replace "
                "anything. Nothing was written.")
        front_picture = Path(str(front_picture))
        if front_picture.suffix.lower() != picture.suffix.lower():
            raise PictureError(
                "The new back is a %s file and the front it pairs with is a "
                "%s file, so the two names the plugin matches would not share "
                "one format. Nothing was written - choose the picture again."
                % (picture.suffix or "(nameless)", front_picture.suffix
                   or "(nameless)"))
    else:
        front_picture = None
    try:
        if slot == "back":
            written = photo_replace.save_pair(folder, pair, front_picture,
                                              picture)
        else:
            #  The front alone still has to *be* the front: the plugin reads
            #  the side off the name, and an unsided name is a photo it will
            #  not place at the main photo of a card it is replacing as a pair.
            written = photo_replace.save_pair(folder, pair + "-front", picture)
    except photo_replace.PhotoReplaceError as exc:
        raise PictureError(str(exc)) from exc
    return {"front": written.get("front"), "back": written.get("back"),
            "pair": pair}


def args(title, front, back=None, cookie_file=""):
    """The plugin's CSV-free replace command, exactly as it documents it."""
    argv = ["--mode", "replace", "--title", str(title or ""),
            "--front", str(front)]
    if back:
        argv += ["--back", str(back)]
    argv += ["--cookie-file", str(cookie_file or "")]
    return argv


def back_url(rows, current=""):
    """The photo the listing shows as its back, or ``""``.

    Found by the name the plugin gives it (``-back``), and by position 2 when
    a gallery predates that naming. The front the record states is never
    returned: it is one of the two photos, but it is not the back.
    """
    wanted = str(current or "")
    by_position = ""
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        photo = str(row.get("imageUrl") or "")
        if not photo or photo == wanted:
            continue
        if photo_replace.side_of(_filename(photo)) == "back":
            return photo
        if not by_position and str(row.get("sortOrder") or "").strip() == "2":
            by_position = photo
    return by_position


def review_lines(title, slot, rows=(), current=""):
    """What the one pictured window says before anything is written."""
    slot = slot_of(slot)
    named = str(title or "this listing")
    now = back_url(rows, current)
    lines = [
        "The picture replaces %s of: %s" % (slot_words(slot), named),
        "",
        "It is padded onto a white square first, so the storefront's square "
        "box has nothing left to crop. Then the CanadianShopper plugin uploads "
        "it and puts it at position %d of this listing's photos."
        % position(slot),
        "",
    ]
    if slot == "back":
        if now:
            lines.append("The back shown now is replaced, not doubled - you do "
                         "not have to take it off first.")
        else:
            lines.append("The listing shows no back yet, so this one is added "
                         "as the second photo.")
        lines.append("The front shown now is sent with it, unchanged, because "
                     "a back is only replaced as one half of the card's pair. "
                     "The front's picture stays the same.")
    else:
        lines.append("The back is left exactly as it is: only the main photo "
                     "changes.")
    lines += ["", "Nothing else on the listing is touched - not its title, "
                  "price, stock or state."]
    return lines


def done_words(returncode, slot, title):
    """What the console says once the plugin has had its turn."""
    slot = slot_of(slot)
    named = str(title or "the listing")
    if returncode == 0:
        return ("The plugin reported the replacement done: %s of \"%s\" is now "
                "the picture you chose. Its own account of the upload is above."
                % (slot_words(slot), named))
    return ("The plugin did not finish (exit code %s), so the listing is "
            "unchanged unless its own report above says otherwise. Nothing "
            "else was written." % returncode)


def words_or_nothing(failure):
    """A failure said in words, with the one promise the caller makes.

    Every refusal in this module already ends by saying nothing was written,
    and an error from somewhere else (a full disk, a picture Tk cannot read)
    does not - so the sentence is added only when it is missing, rather than
    printed twice.
    """
    words = str(failure or "").strip() or "The picture could not be prepared."
    if "nothing was written" in words.lower():
        return words
    return words + " Nothing was written."


def missing_plugin(slot, version="", needs=""):
    """Why a picture cannot be placed with the plugin that is installed."""
    slot = slot_of(slot)
    if slot == "back":
        return ("Replacing a card's back needs CanadianShopper %s or newer - "
                "an older plugin adds a second back beside the old one instead "
                "of replacing it, which is worse than doing nothing. The "
                "installed plugin is %s. Nothing was written."
                % (needs or "1.0.16", version or "of an unknown version"))
    return ("Placing a picture on a listing needs CanadianShopper 1.0.15 or "
            "newer, which replaces one card's photos without a staged CSV. "
            "The installed plugin is %s, so nothing was written. One card's "
            "photos can still be replaced from Edit stock entry, which writes "
            "the staged batch the older plugin reads."
            % (version or "of an unknown version"))
