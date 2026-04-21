#!/usr/bin/env python3
"""
Update menu_items.json to reference .png images instead of .svg.

Only updates entries where a corresponding .png file exists in data/images/.

Usage:
    python scripts/update_menu_image_refs.py
    python scripts/update_menu_image_refs.py --dry-run
"""

import argparse
import json
import os

MENU_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "menu_items.json")
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "images")


def main():
    parser = argparse.ArgumentParser(description="Update menu image references from .svg to .png")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    with open(MENU_FILE) as f:
        menu_data = json.load(f)

    updated = 0
    for item in menu_data:
        image_url = item.get("imageUrl", "")
        if not image_url or not image_url.endswith(".svg"):
            continue

        png_filename = os.path.splitext(os.path.basename(image_url))[0] + ".png"
        png_path = os.path.join(IMAGES_DIR, png_filename)

        if os.path.exists(png_path):
            new_url = image_url.rsplit(".", 1)[0] + ".png"
            if args.dry_run:
                print(f"  {item.get('name', 'unknown')}: {image_url} -> {new_url}")
            else:
                item["imageUrl"] = new_url
            updated += 1

    if not args.dry_run and updated > 0:
        with open(MENU_FILE, "w") as f:
            json.dump(menu_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {updated} image references.")


if __name__ == "__main__":
    main()
