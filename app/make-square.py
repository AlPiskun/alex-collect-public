#!/usr/bin/env python3
"""
make-square.py — square up a few photos for manual upload to CanadianShopper
============================================================================

WHY
    The storefront renders every product photo in a square box with
    `object-cover`, so a portrait photo gets its top and bottom cut off (a
    600x702 card loses ~50px at each end, a 600x837 one loses ~120px). The fix
    is to hand it a SQUARE file: the card is centred on a white square, so
    `object-cover` has nothing left to crop. This is the same padding the bulk
    tool does — just for one card at a time, with no cookie and no API calls.

HOW TO USE IT (Windows — easiest)
    1. Drag the photo(s) onto  SquareImages.bat
       (or put the files in a folder and drag that folder on instead)
    2. The square versions land in a  square/  subfolder next to the originals.
    3. In the CanadianShopper dashboard, open the product, and upload:
            <name>-square.jpg      <- as the MAIN product image
            <name>-back-square.jpg <- added as a second image (the gallery /
                                      "back" slot), if you have a back photo
       Do not upload the originals: they are the ones that get cropped.

HOW TO USE IT (command line, any OS)
    python3 make-square.py front.webp back.webp
    python3 make-square.py "C:\\...\\Scan\\output"          # a whole folder
    python3 make-square.py *.jpg --out "C:\\...\\square"    # explicit output
    python3 make-square.py card.jpg --size 1000             # force 1000x1000
    python3 make-square.py card.png --format png --keep-alpha
    python3 make-square.py card.jpg --dry-run               # just report

WHAT THE OPTIONS DO
    --out DIR       where to write (default: a "square" folder beside each source)
    --size N        force NxN; default 0 = native square (longest side, no
                    resampling, so nothing is blurred or sharpened)
    --format jpeg   jpeg (small, white background) or png (supports transparency)
    --quality 88    JPEG quality
    --bg white      white / black / #RRGGBB
    --keep-alpha    keep transparency (use with --format png)
    --suffix -square   text added to the filename before the new extension
    --open          open the output folder when done
"""

import argparse
import glob
import io
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    sys.exit("Pillow is required.   Install it with:   python -m pip install Pillow")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")
DEFAULT_SUFFIX = "-square"


# ----------------------------------------------------------------- image work
def parse_bg(text):
    text = (text or "white").strip()
    if text.lower() in ("white", "w", "#fff", "#ffffff"):
        return (255, 255, 255)
    if text.lower() in ("black", "#000", "#000000"):
        return (0, 0, 0)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))
    raise SystemExit("! --bg must be 'white', 'black' or '#RRGGBB'")


def pad_to_square(im, bg=(255, 255, 255), keep_alpha=False, size=None):
    """Centre the image on a square canvas (same routine as pad-and-upload.py)."""
    w, h = im.size
    side = max(w, h)
    if keep_alpha:
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        src = im.convert("RGBA")
    else:
        canvas = Image.new("RGB", (side, side), bg)
        src = im.convert("RGBA")
        flat = Image.new("RGBA", src.size, bg + (255,))
        src = Image.alpha_composite(flat, src).convert("RGB")
    canvas.paste(src, ((side - w) // 2, (side - h) // 2))
    if size and size != side:
        canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def encode(img, fmt, quality):
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", ".png"
    img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue(), "image/jpeg", ".jpg"


def expand_inputs(values):
    """Files, folders and globs all welcome; folders are searched one level."""
    out = []
    for value in values:
        if os.path.isdir(value):
            found = [p for p in sorted(glob.glob(os.path.join(value, "*")))
                     if p.lower().endswith(IMAGE_EXTS)]
            if not found:
                print("  ! no image files inside %s" % value)
            out.extend(found)
        elif any(ch in value for ch in "*?["):
            hits = sorted(glob.glob(value))
            out.extend(hits or [value])
        else:
            out.append(value)
    seen, uniq = set(), []
    for path in out:
        key = os.path.abspath(path)
        if key not in seen:
            seen.add(key)
            uniq.append(path)
    return uniq


def output_path(src, out_dir, suffix, ext, in_place_dir):
    stem = Path(src).stem
    name = "%s%s%s" % (stem, suffix, ext)
    target_dir = Path(out_dir) if out_dir else Path(in_place_dir)
    return target_dir / name


def normalise_argv(argv):
    """argparse reads a value that starts with '-' as another option, so
    `--suffix -back` would fail. Join those into `--suffix=-back`."""
    out, i = [], 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--suffix", "--out", "--bg") and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append("%s=%s" % (arg, argv[i + 1]))
            i += 2
            continue
        out.append(arg)
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Pad card photos to a square for CanadianShopper manual upload.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples
--------
  python3 make-square.py front.webp back.webp
  python3 make-square.py "C:/Users/Owner/Pictures/ControlCenter4/Scan/output"
  python3 make-square.py card.jpg --size 1000 --format jpeg
  python3 make-square.py card.png --format png --keep-alpha
""")
    ap.add_argument("paths", nargs="*", help="image files, folders or globs")
    ap.add_argument("--out", default="", help="output folder (default: square/ beside each file)")
    ap.add_argument("--size", type=int, default=0, help="force NxN (0 = native square)")
    ap.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument("--bg", default="white", help="white, black or #RRGGBB")
    ap.add_argument("--keep-alpha", action="store_true", help="keep transparency (png)")
    ap.add_argument("--suffix", default=DEFAULT_SUFFIX, help="filename suffix (default -square)")
    ap.add_argument("--open", action="store_true", help="open the output folder when done")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args(normalise_argv(sys.argv[1:]))

    if not args.paths:
        ap.print_help()
        print("\n! Give me at least one image (or drag files onto SquareImages.bat).")
        return 2

    if args.keep_alpha and args.format != "png":
        print("  ! --keep-alpha needs --format png; switching to png.")
        args.format = "png"

    bg = parse_bg(args.bg)
    sources = expand_inputs(args.paths)
    if not sources:
        raise SystemExit("! No images found to process.")

    print("=" * 72)
    print(" Square card photos for CanadianShopper manual upload")
    print("=" * 72)
    print("  source(s) : %d file(s)" % len(sources))
    print("  output    : %s%s" % (args.out or "square/ beside each source",
                                  "   %dx%d" % (args.size, args.size) if args.size else
                                  "   (native square, no resampling)"))
    print("  format    : %s   background: %s%s"
          % (args.format, args.bg, "   alpha kept" if args.keep_alpha else ""))
    print("-" * 72)

    written, errors = [], 0
    out_dirs = set()
    for src in sources:
        if not os.path.isfile(src):
            print("  ! not found: %s" % src)
            errors += 1
            continue
        try:
            with Image.open(src) as im:
                im.load()
                before = im.size
                square = pad_to_square(im, bg=bg, keep_alpha=args.keep_alpha,
                                       size=args.size or None)
            data, mime, ext = encode(square, args.format, args.quality)
            base_dir = Path(src).parent / "square"
            dest = output_path(src, args.out, args.suffix, ext, base_dir)
            src_kb, out_kb = os.path.getsize(src) / 1024, len(data) / 1024
            if before[0] == before[1]:
                flag = ""
            elif before[1] > before[0]:
                flag = "  (portrait -> squared)"
            else:
                flag = "  (landscape -> squared)"
            print("  %-42s %sx%s -> %dx%d  %4d -> %4d KB%s"
                  % (Path(src).name[:42], before[0], before[1],
                     square.size[0], square.size[1], src_kb, out_kb, flag))
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
                written.append(str(dest))
                out_dirs.add(str(dest.parent))
        except Exception as exc:
            print("  ! %s: %s" % (Path(src).name, exc))
            errors += 1

    print("-" * 72)
    if args.dry_run:
        print("  Dry run - nothing written.")
    else:
        print("  %d file(s) written, %d error(s)" % (len(written), errors))
        for path in written[:12]:
            print("      %s" % path)
        if len(written) > 12:
            print("      ... and %d more" % (len(written) - 12))
        print("")
        print("  NOW, in the CanadianShopper dashboard (Products -> that card -> Edit):")
        print("     * front file  -> main product image")
        print("     * back file   -> add as a second image (the gallery row)")
        print("     * set Inventory to the number you actually have left")
        if args.open and out_dirs:
            folder = sorted(out_dirs)[0]
            try:
                if os.name == "nt":
                    os.startfile(folder)                      # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.run(["open", folder], check=False)
                else:
                    subprocess.run(["xdg-open", folder], check=False)
            except Exception:
                pass
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
