"""Upload a replacement photo to WordPress and put it on the Woo product.

WooCommerce's own REST keys (``ck_`` / ``cs_``) cannot touch the media
library: media lives in the WordPress REST API, which authenticates with an
Application Password (Users > Profile > Application Passwords) instead. So two
credentials are used, each for the thing it can actually do:

  1. the Application Password uploads the image to ``/wp-json/wp/v2/media``
  2. the consumer key pair sets the product's ``images`` array through
     ``/wp-json/wc/v3/products/<id>``, which needs Read/Write keys
  3. the Application Password gives each upload the product as its parent,
     so the media library files it under the product instead of under
     "Unattached"

Keeping this in its own module means the panel can be exercised without a
network and without Tk, and the HTTP can be handed a fake opener in tests.

Nothing here logs, formats, or raises with a password in the text.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WP_MEDIA_PATH = "/wp-json/wp/v2/media"
WC_PRODUCTS_PATH = "/wp-json/wc/v3/products"
USER_AGENT = "Mozilla/5.0 (compatible; AlexCollectTools/1.0)"

#  mimetypes is unreliable for these on older Windows/Python installs.
_EXTRA_TYPES = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class MediaError(Exception):
    """A refused upload or product update, safe to show to the user.

    ``partial`` means the image did reach the media library but the product
    was not updated, so the caller can say exactly that instead of implying
    nothing happened.
    """

    def __init__(self, message, status=0, attachment_id=None, partial=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.attachment_id = attachment_id
        self.partial = partial


def site_root(site):
    """The site URL without a trailing slash, or "" when it is unusable."""
    value = str(site or "").strip().rstrip("/")
    if not value.lower().startswith(("http://", "https://")):
        return ""
    return value


def is_https(site):
    return site_root(site).lower().startswith("https://")


def basic_auth(username, app_password):
    """The Authorization header value for an Application Password."""
    token = ("%s:%s" % (username, app_password)).encode("utf-8")
    return "Basic " + base64.b64encode(token).decode("ascii")


def content_type_for(path):
    suffix = Path(path).suffix.lower()
    return (_EXTRA_TYPES.get(suffix) or
            mimetypes.guess_type(str(path))[0] or "application/octet-stream")


def safe_filename(name):
    """A header-safe attachment name, keeping the extension.

    Non-ASCII names are transliterated away rather than percent-encoded: a
    Content-Disposition header is not the place to negotiate encodings, and
    WordPress re-slugs the name anyway.
    """
    stem = Path(str(name)).name
    suffix = Path(stem).suffix
    base = stem[:len(stem) - len(suffix)] if suffix else stem
    cleaned = _SAFE_NAME.sub("_", base).strip("._-") or "replacement"
    safe_suffix = _SAFE_NAME.sub("", suffix) or ""
    return cleaned + safe_suffix


def _http(request, timeout, opener=None):
    """Send ``request``; return ``(status, body bytes)``.

    A connection problem is reported as a MediaError rather than escaping as a
    urllib exception, so callers only have one failure type to handle.
    """
    if opener is None:
        def opener(req, timeout):
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
    try:
        return opener(request, timeout)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return exc.code, body
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise MediaError("Could not reach the website (%s)." % reason)
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError("Could not reach the website (%s)." % exc)


def _json_or_text(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return body.decode("utf-8", "replace")[:300]


def _wp_message(payload):
    """WordPress's own explanation, when it sent one."""
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return ""


def _explain_upload(status, payload):
    wp = _wp_message(payload)
    if status == 401:
        base = ("Rejected the Application Password (HTTP 401). Check that the "
                "fourth and fifth lines of woo-keys.txt are your WordPress "
                "username and an Application Password, and that the site uses "
                "HTTPS.")
    elif status == 403:
        base = ("That WordPress user is not allowed to upload files "
                "(HTTP 403). An Administrator or Editor account can.")
    elif status in (406, 415):
        base = ("WordPress refused this file type (HTTP %d)." % status)
    elif status == 413:
        base = "The image is larger than the website allows (HTTP 413)."
    else:
        base = "WordPress refused the image (HTTP %s)." % status
    return base + (" WordPress said: %s" % wp if wp else "")


def _explain_attach(status, payload):
    wp = _wp_message(payload)
    if status == 401:
        base = ("Rejected the Application Password (HTTP 401), so the media "
                "library still calls the image unattached.")
    elif status == 403:
        base = ("That WordPress user is not allowed to edit this image "
                "(HTTP 403), so it stays unattached in the media library.")
    elif status == 404:
        base = ("WordPress no longer has that image (HTTP 404), so it cannot "
                "be attached.")
    else:
        base = ("WordPress would not link the image to the product "
                "(HTTP %s)." % status)
    return base + (" WordPress said: %s" % wp if wp else "")


def _explain_product(status, payload):
    wp = _wp_message(payload)
    if status == 401:
        base = ("The website rejected the WooCommerce keys (HTTP 401). "
                "Setting a product image needs Read/Write keys, not Read-only.")
    elif status == 403:
        base = ("Those WooCommerce keys cannot change products (HTTP 403). "
                "Re-create them with Read/Write access.")
    elif status == 404:
        base = "That product no longer exists on the website (HTTP 404)."
    else:
        base = "The website refused the product update (HTTP %s)." % status
    return base + (" WordPress said: %s" % wp if wp else "")


def upload_media(site, username, app_password, image_path, title=None,
                 timeout=60, opener=None):
    """Upload one image to the WordPress media library.

    Returns the attachment record: ``{"id": int, "source_url": str, ...}``.
    Raises MediaError with nothing uploaded when the site refuses.
    """
    root = site_root(site)
    if not root:
        raise MediaError("No website address is saved, so the image cannot be "
                         "uploaded.")
    if not (username and app_password):
        raise MediaError("Uploading needs a WordPress username and "
                         "Application Password in woo-keys.txt.")
    path = Path(image_path)
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise MediaError("Could not read %s (%s)." % (path.name, exc))

    filename = safe_filename(path.name)
    request = urllib.request.Request(
        root + WP_MEDIA_PATH, data=body, method="POST",
        headers={
            "Authorization": basic_auth(username, app_password),
            "Content-Type": content_type_for(path),
            "Content-Disposition": 'attachment; filename="%s"' % filename,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })
    status, raw = _http(request, timeout, opener)
    payload = _json_or_text(raw)
    if status not in (200, 201):
        raise MediaError(_explain_upload(status, payload), status=status)
    if not isinstance(payload, dict) or not payload.get("id"):
        raise MediaError("The website accepted the upload but sent no image "
                         "ID back, so the product cannot be pointed at it.")

    attachment = {"id": int(payload["id"]),
                  "source_url": payload.get("source_url") or "",
                  "filename": filename}
    if title:
        attachment["title"] = str(title)
    return attachment


def _media_matches(entry, filename):
    """Whether a media record is the file that was just uploaded."""
    name = Path(str(filename or "")).name.lower()
    if not name:
        return False
    source = str(entry.get("source_url") or "").replace("\\", "/")
    if source and Path(source).name.lower() == name:
        return True
    #  WordPress may re-slug a name (spaces, accents), so the extension-less
    #  stem is also compared - but only when it is long enough to mean
    #  something.
    stem = Path(name).stem
    if len(stem) >= 8:
        title = str(entry.get("slug") or "")
        if title.lower() == stem:
            return True
        rendered = str(((entry.get("title") or {}) if isinstance(
            entry.get("title"), dict) else {}).get("rendered") or "").lower()
        if rendered == stem:
            return True
    return False


def find_media(site, username, app_password, filename, timeout=60,
               opener=None):
    """The media library's copy of ``filename``, or ``None``.

    Only used after an upload failed in a way that might have landed: a slow
    site can create the attachment, spend seconds on thumbnails, and lose the
    answer on the way back. Asking first is what stops the retry leaving a
    duplicate in the library. Never raises - a library that cannot be read is
    simply a library with nothing found, and the caller retries the upload.
    """
    root = site_root(site)
    filename = Path(str(filename or "")).name
    if not (root and filename and username and app_password):
        return None
    stem = Path(filename).stem
    query = urllib.parse.urlencode({"search": stem, "per_page": 50,
                                    "orderby": "date", "order": "desc"})
    request = urllib.request.Request(
        "%s%s?%s" % (root, WP_MEDIA_PATH, query),
        headers={"Authorization": basic_auth(username, app_password),
                 "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        status, raw = _http(request, timeout, opener)
    except MediaError:
        return None
    if status != 200:
        return None
    payload = _json_or_text(raw)
    for entry in payload if isinstance(payload, list) else []:
        if isinstance(entry, dict) and entry.get("id") and \
                _media_matches(entry, filename):
            return {"id": int(entry["id"]),
                    "source_url": entry.get("source_url") or "",
                    "filename": filename,
                    "found": True}
    return None


def attach_media(site, username, app_password, attachment_ids, post_id,
                 timeout=60, opener=None):
    """Say which product each uploaded image belongs to.

    An upload arrives with no parent post, and WordPress shows every
    parentless attachment as "Unattached" in the media library - even while a
    product's gallery already points at it. The parent belongs to the
    attachment, not to the product, so it is set with one small PUT per file
    once the product exists.

    Nothing here raises. The photos are on the product by the time this runs,
    so a library that keeps calling them unattached is a tidiness problem,
    never a reason to report the upload as failed. The answer says which files
    were attached and, for the rest, why not.
    """
    ids = [int(i) for i in (attachment_ids or [])
           if str(i).strip().isdigit()]
    if not ids:
        return {"attached": [], "failed": []}
    parent = int(post_id or 0)
    if not parent:
        why = "no product was named, so there is nothing to attach them to."
        return {"attached": [], "failed": [{"id": i, "why": why} for i in ids]}
    root = site_root(site)
    if not (root and username and app_password):
        why = ("the WordPress username and Application Password are needed to "
               "attach an image (lines 4 and 5 of woo-keys.txt)."
               if root else "no website address is saved.")
        return {"attached": [], "failed": [{"id": i, "why": why} for i in ids]}

    attached, failed = [], []
    for attachment_id in ids:
        request = urllib.request.Request(
            "%s%s/%d" % (root, WP_MEDIA_PATH, attachment_id),
            data=json.dumps({"post": parent}).encode("utf-8"), method="PUT",
            headers={
                "Authorization": basic_auth(username, app_password),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            })
        try:
            status, raw = _http(request, timeout, opener)
        except MediaError as exc:
            failed.append({"id": attachment_id, "why": exc.message})
            continue
        if status in (200, 201):
            attached.append(attachment_id)
        else:
            failed.append({"id": attachment_id,
                           "why": _explain_attach(status, _json_or_text(raw))})
    return {"attached": attached, "failed": failed}


def set_product_images(site, key, secret, product_id, image_ids, timeout=60,
                       retries=2, opener=None):
    """Point a product's gallery at ``image_ids``, first one being the main.

    The keys travel as query parameters because some hosts strip the
    Authorization header before PHP sees it - the same reason the existing
    read-only calls do it this way. This is idempotent, so it is safe to retry.
    """
    root = site_root(site)
    if not root:
        raise MediaError("No website address is saved, so the product cannot "
                         "be updated.")
    ids = [int(i) for i in (image_ids or []) if str(i).strip().isdigit()]
    if not ids:
        raise MediaError("There is no uploaded image to put on the product.")
    query = urllib.parse.urlencode({"consumer_key": key,
                                    "consumer_secret": secret})
    url = "%s%s/%s?%s" % (root, WC_PRODUCTS_PATH, product_id, query)
    data = json.dumps({"images": [{"id": i} for i in ids]}).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="PUT",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": USER_AGENT})

    last = ""
    for _attempt in range(max(1, retries)):
        try:
            status, raw = _http(request, timeout, opener)
        except MediaError as exc:
            last = exc.message
            continue
        payload = _json_or_text(raw)
        if status in (200, 201):
            if not isinstance(payload, dict) or not payload.get("id"):
                #  A 200 with no product in it is not proof of anything, and
                #  claiming success would leave the shop unchanged while the
                #  app says otherwise.
                raise MediaError("The website answered but did not return the "
                                 "product, so the change could not be "
                                 "confirmed.")
            if "images" in payload:
                landed = {int(i["id"]) for i in payload["images"]
                          if isinstance(i, dict) and
                          str(i.get("id", "")).isdigit()}
                if ids[0] not in landed:
                    raise MediaError("The website answered, but the new image "
                                     "is not on the product.")
            return payload
        if status >= 500:
            last = _explain_product(status, payload)
            continue
        raise MediaError(_explain_product(status, payload), status=status)
    raise MediaError(last or "The product update did not complete.")


def image_name_from_url(src):
    """The bare filename of a gallery row's URL."""
    return str(src or "").strip().rstrip("/").rsplit("/", 1)[-1]


def existing_images(product):
    """``[{"id": int, "name": str}]`` for the product's gallery, in order."""
    rows = []
    for image in (product or {}).get("images") or []:
        if not isinstance(image, dict):
            continue
        if not str(image.get("id", "")).isdigit():
            continue
        rows.append({"id": int(image["id"]),
                     "name": image_name_from_url(image.get("src"))})
    return rows


def existing_image_ids(product):
    """The attachment IDs already on a product, in display order."""
    return [row["id"] for row in existing_images(product)]


def replace_product_photos(site, key, secret, username, app_password, product,
                           front_path, back_path=None, keep_ids=None,
                           timeout=60, opener=None):
    """Upload the card's photos and make them the product's images.

    The front becomes the main photo and the back follows it. ``keep_ids`` are
    the gallery rows to leave behind the new pair; passing an empty list drops
    every existing photo, while ``None`` keeps them all. Both images are
    uploaded before the product is touched, so a failed upload changes nothing.
    """
    product_id = (product or {}).get("id")
    if not product_id:
        raise MediaError("No product was selected, so there is nothing to "
                         "update.")
    uploads = [("front", front_path)]
    if back_path is not None:
        uploads.append(("back", back_path))
    attachments = {}
    for label, path in uploads:
        try:
            attachments[label] = upload_media(
                site, username, app_password, path,
                title=(product or {}).get("name"), timeout=timeout,
                opener=opener)
        except MediaError as exc:
            done = (" The %s image is already in the media library, but the "
                    "product was not changed." % "front"
                    if attachments else "")
            raise MediaError("The %s image could not be uploaded. %s%s"
                             % (label, exc.message, done),
                             status=exc.status,
                             attachment_id=(attachments.get("front") or {}
                                            ).get("id"),
                             partial=bool(attachments))
    ids = [attachments["front"]["id"]]
    if "back" in attachments:
        ids.append(attachments["back"]["id"])
    if keep_ids is None:
        ids += [i for i in existing_image_ids(product) if i not in ids]
    else:
        ids += [int(i) for i in keep_ids
                if str(i).strip().isdigit() and int(i) not in ids]
    try:
        updated = set_product_images(site, key, secret, product_id, ids,
                                     timeout=timeout, opener=opener)
    except MediaError as exc:
        raise MediaError(
            "The photos reached the media library, but the product was NOT "
            "updated. %s" % exc.message,
            status=exc.status,
            attachment_id=attachments["front"]["id"], partial=True)
    #  The product now shows the new pair, and this is what stops the media
    #  library from filing those same files under "Unattached". Only the new
    #  uploads are re-parented: the photos that were already there keep the
    #  product they were attached to.
    attached = attach_media(site, username, app_password,
                            [attachments["front"]["id"]] +
                            ([attachments["back"]["id"]]
                             if "back" in attachments else []),
                            product_id, timeout=timeout, opener=opener)
    return {"front": attachments["front"],
            "back": attachments.get("back"),
            "product": updated, "image_ids": ids, "attached": attached}
