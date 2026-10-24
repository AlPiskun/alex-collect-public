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
<<<<<<< HEAD
    old_ebay_dir = pipeline.EBAY_QUICKLIST_DIR
=======
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
<<<<<<< HEAD
            pipeline.EBAY_QUICKLIST_DIR = root / "ebay_quick_list"
            pipeline.EBAY_QUICKLIST_DIR.mkdir()
            legacy_page = pipeline.EBAY_QUICKLIST_DIR / "ebay_quick_list_legacy.html"
            legacy_page.write_text("<h2>Prior listing</h2>", encoding="utf-8")
=======
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
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
            values = pipeline._ebay_quicklist_values(card)
            assert values["price"] == "13.00"  # WooCommerce rounds the price up.
            assert values["sport"] == "Hockey"
            page, templates = pipeline._render_ebay_quicklist([card])
            assert templates == ["https://ebay.example/hockey-template"]
            assert "Wayne Gretzky" in page and "draggable=\"true\"" in page
            assert "Vintage trading card description." in page
            assert "https://store.example/uploads/" in page
            pipeline.launch_urls = lambda urls, browser: opened.append((list(urls), browser)) or "System default browser"
            pipeline.open_folder = lambda _path: True
            with patch.object(builtins, "input", side_effect=["y", "1", ""]):
                pipeline.maybe_run_ebay_quicklist([card])
<<<<<<< HEAD
            html_files = list((root / "ebay_quick_list").glob(
                "ebay_quick_list_*.html"))
            sidecars = [path for path in (root / "ebay_quick_list").glob(
                "ebay_quick_list_*.json")
                if path.name != "ebay_quick_list_history.json"]
            assert len(html_files) == 1 and len(sidecars) == 1
            history = pipeline.EBAY_QUICKLIST_DIR / "ebay_quick_list_history.json"
            assert history.is_file() and not legacy_page.exists()
            assert "Prior listing" in history.read_text(encoding="utf-8")
=======
            html_files = list(root.glob("ebay_quick_list_*.html"))
            assert len(html_files) == 1
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
            assert opened[0][0][0].startswith("file:")
            assert opened[1][0] == ["https://ebay.example/hockey-template"]
            print("PASS eBay selection, mapped fields, image URLs, HTML drag/copy page, and template tabs")
    finally:
        pipeline.USER_SETTINGS = old_settings
        pipeline.SCRIPT_DIR = old_script_dir
        pipeline.OUTPUT_DIR = old_output_dir
<<<<<<< HEAD
        pipeline.EBAY_QUICKLIST_DIR = old_ebay_dir
=======
>>>>>>> 2428534cd1664b6db43d60866dfb26d4d61f9b65
        pipeline.launch_urls = old_launch
        pipeline.open_folder = old_open_folder


if __name__ == "__main__":
    main()
