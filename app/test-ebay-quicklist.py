#!/usr/bin/env python3
"""Offline checks for the manual eBay Quick List pipeline stage."""
import builtins
import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("card_pipeline", HERE / "pipeline" / "card_pipeline.py")
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def main():
    assert pipeline._parse_ebay_card_selection("all", 3) == [0, 1, 2]
    assert pipeline._parse_ebay_card_selection("1,3", 3) == [0, 2]
    assert pipeline._parse_ebay_card_selection("2-3", 3) == [1, 2]
    assert pipeline._parse_ebay_card_selection("", 3) == []
    try:
        pipeline._parse_ebay_card_selection("4", 3)
        raise AssertionError("out-of-range selection should fail")
    except ValueError:
        pass

    old_settings = pipeline.USER_SETTINGS
    old_script_dir = pipeline.SCRIPT_DIR
    old_output_dir = pipeline.OUTPUT_DIR
    old_ebay_dir = pipeline.EBAY_QUICKLIST_DIR
    old_launch = pipeline.launch_urls
    old_open_folder = pipeline.open_folder
    opened = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "card-front.webp").write_bytes(b"image")
            (output_dir / "card-back.webp").write_bytes(b"image")
            pipeline.SCRIPT_DIR = root
            pipeline.OUTPUT_DIR = output_dir
            pipeline.EBAY_QUICKLIST_DIR = root / "ebay_quick_list"
            pipeline.EBAY_QUICKLIST_DIR.mkdir()
            legacy_page = pipeline.EBAY_QUICKLIST_DIR / "ebay_quick_list_legacy.html"
            legacy_page.write_text("<h2>Prior listing</h2>", encoding="utf-8")
            pipeline.USER_SETTINGS = {
                "ebay_quicklist_enabled": True,
                "browser_name": "system",
                "woo_site_url": "https://store.example",
                "ebay_image_base_url": "https://store.example/uploads/{year}/{month}",
                "ebay_template_hockey_url": "https://ebay.example/hockey-template",
                "ebay_template_default_url": "https://ebay.example/default-template",
                "ebay_default_condition": "Mint",
                "ebay_default_year": "Unknown",
                "ebay_default_manufacturer": "Unknown",
                "ebay_default_card_number": "N/A",
                "ebay_default_player": "Unknown",
                "ebay_default_set": "Vintage",
                "ebay_default_grade": "",
                "ebay_default_autographed": "No",
                "ebay_default_description": "Vintage card.",
            }
            card = {
                "seo_title": "1975 O-Pee-Chee Wayne Gretzky #1",
                "price": 12.2,
                "year": "1975", "brand": "O-Pee-Chee", "card_num": "1",
                "player": "Wayne Gretzky", "grade": "EX 5",
                "keyword": "Hockey card", "tags": "O-Pee-Chee, Hockey",
                "category": "Sports Card", "subcategory": "Hockey Card",
                "full_description": "Vintage trading card description.",
                "front_img": "card-front.webp", "back_img": "card-back.webp",
            }
            #  An image title that ends in anything but the pipeline's own
            #  format is named in that format: the tile is WebP whatever the
            #  title said, and a ".jpg" name would be a WebP file wearing a
            #  JPEG extension - which the eBay links then repeat.
            front, back = pipeline.parse_images(
                "1-Ken-Dryden-1971-72-O-Pee-Chee-front-EX-5.jpg\n"
                "1-Ken-Dryden-1971-72-O-Pee-Chee-back-EX-5.png")
            assert front.endswith("-EX-5.webp") and back.endswith("-EX-5.webp"), \
                (front, back)
            assert "front-EX-5.webp" in front and "back-EX-5.webp" in back
            plain, plain_back = pipeline.parse_images(
                "1-Card-front\n1-Card-back")
            assert plain.endswith("-front.webp") and plain_back.endswith(
                "-back.webp"), (plain, plain_back)
            already, _ = pipeline.parse_images("1-Card-front.webp\n1-Card-back.webp")
            assert already == "1-Card-front.webp", already

            #  A rename cannot leave a .jpg name on a WebP file any more.
            rename_dir = root / "rename"
            rename_dir.mkdir()
            for tile in range(1, 3):
                for side in ("scan_front", "scan_back"):
                    pipeline.save_webp_target_size(
                        pipeline.Image.new("RGB", (400, 560), (190, 160, 120)),
                        str(rename_dir / ("%s_%d.webp" % (side, tile))))
            rename_rows = [{"Images": front}]
            fronts, backs = pipeline.targets_from_rows(rename_rows)
            ops, missing = pipeline.plan_renames(
                str(rename_dir), fronts, backs, "scan_front", "scan_back",
                "webp")
            pipeline.apply_renames(ops)
            written = sorted(path.name for path in rename_dir.iterdir())
            assert front in written, written
            assert not any(name.endswith((".jpg", ".png")) for name in written), \
                written
            assert pipeline.looks_like_webp(rename_dir / front)

            #  A batch renamed before this fix is repaired, not re-rendered:
            #  only a file whose bytes are really WebP is touched.
            repair_dir = root / "repair"
            repair_dir.mkdir()
            for name, mode in (("old-front.jpg", "WEBP"),
                               ("old-back.jpg", "WEBP"),
                               ("photo.jpg", "JPEG"),
                               ("taken.jpg", "WEBP")):
                pipeline.Image.new("RGB", (120, 160), (120, 90, 60)).save(
                    repair_dir / name, mode)
            pipeline.Image.new("RGB", (120, 160), (120, 90, 60)).save(
                repair_dir / "taken.webp", "WEBP")
            fixed, kept = pipeline.repair_image_extensions(repair_dir)
            names = sorted(path.name for path in repair_dir.iterdir())
            assert ("old-front.jpg", "old-front.webp") in fixed, fixed
            assert "old-front.webp" in names and "old-front.jpg" not in names
            assert "photo.jpg" in names, names          # a real JPEG keeps its name
            assert "taken.jpg" in names and any(
                "already there" in why for _name, why in kept), kept

            values = pipeline._ebay_quicklist_values(card)
            assert values["price"] == "13.00"  # WooCommerce rounds the price up.
            assert values["sport"] == "Hockey"
            page, templates = pipeline._render_ebay_quicklist([card])
            assert templates == ["https://ebay.example/hockey-template"]
            assert "Wayne Gretzky" in page and "draggable=\"true\"" in page
            assert "Vintage trading card description." in page
            assert "https://store.example/uploads/" in page
            assert "card-front.webp" in page

            #  A card whose stored name still says .jpg is linked by the file
            #  that is really in the folder: the page never shows a .jpg for a
            #  WebP picture.
            stale = dict(card, front_img="card-front.jpg",
                         back_img="card-back.png")
            stale_page, _ = pipeline._render_ebay_quicklist([stale])
            assert "card-front.webp" in stale_page, stale_page[:400]
            assert "card-front.jpg" not in stale_page
            assert "card-back.webp" in stale_page
            assert "card-back.png" not in stale_page
            pipeline.launch_urls = lambda urls, browser: opened.append((list(urls), browser)) or "System default browser"
            pipeline.open_folder = lambda _path: True
            with patch.object(builtins, "input", side_effect=["y", "1", ""]):
                pipeline.maybe_run_ebay_quicklist([card])
            html_files = list((root / "ebay_quick_list").glob(
                "ebay_quick_list_*.html"))
            sidecars = [path for path in (root / "ebay_quick_list").glob(
                "ebay_quick_list_*.json")
                if path.name != "ebay_quick_list_history.json"]
            assert len(html_files) == 1 and len(sidecars) == 1
            history = pipeline.EBAY_QUICKLIST_DIR / "ebay_quick_list_history.json"
            assert history.is_file() and not legacy_page.exists()
            assert "Prior listing" in history.read_text(encoding="utf-8")
            assert opened[0][0][0].startswith("file:")
            assert opened[1][0] == ["https://ebay.example/hockey-template"]
            print("PASS eBay selection, mapped fields, image URLs, HTML drag/copy page, and template tabs")
    finally:
        pipeline.USER_SETTINGS = old_settings
        pipeline.SCRIPT_DIR = old_script_dir
        pipeline.OUTPUT_DIR = old_output_dir
        pipeline.EBAY_QUICKLIST_DIR = old_ebay_dir
        pipeline.launch_urls = old_launch
        pipeline.open_folder = old_open_folder


if __name__ == "__main__":
    main()
