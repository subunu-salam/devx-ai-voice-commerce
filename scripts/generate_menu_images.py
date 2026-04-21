#!/usr/bin/env python3
"""
Generate realistic food images for each menu item using Stability AI SD 3.5 Large on Bedrock.

Reads menu_items.json, generates a PNG for each item, and saves to data/images/.
Existing PNGs are skipped unless --force is passed.

Usage:
    python scripts/generate_menu_images.py
    python scripts/generate_menu_images.py --force
    python scripts/generate_menu_images.py --region us-west-2
"""

import argparse
import base64
import json
import logging
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_ID = "stability.sd3-5-large-v1:0"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "images")
MENU_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "menu_items.json")

# Style prefix for consistent food photography look
STYLE_PREFIX = (
    "Professional food photography, top-down 45-degree angle, "
    "soft natural lighting, shallow depth of field, clean white background, "
    "appetizing and vibrant colors, high resolution, restaurant menu style. "
)

NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, text, watermark, logo, "
    "cartoon, illustration, drawing, painting, sketch, ugly, bad lighting"
)


def build_prompt(name: str, description: str) -> str:
    """Build an image generation prompt from a menu item."""
    return f"{STYLE_PREFIX}{name}: {description}"


def generate_image(client, prompt: str, seed: int = 0) -> bytes:
    """Call Bedrock Stability AI SD 3.5 Large to generate an image."""
    body = json.dumps({
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "aspect_ratio": "1:1",
        "seed": seed,
        "output_format": "png",
    })

    response = client.invoke_model(
        body=body,
        modelId=MODEL_ID,
        accept="application/json",
        contentType="application/json",
    )
    response_body = json.loads(response["body"].read())

    # Check for content filter
    finish_reasons = response_body.get("finish_reasons", [None])
    if finish_reasons and finish_reasons[0] is not None:
        raise RuntimeError(f"Generation filtered: {finish_reasons[0]}")

    base64_image = response_body["images"][0]
    return base64.b64decode(base64_image)


def main():
    parser = argparse.ArgumentParser(description="Generate menu item images via Bedrock Stability AI")
    parser.add_argument("--force", action="store_true", help="Regenerate all images even if they exist")
    parser.add_argument("--region", default="us-west-2", help="AWS region (default: us-west-2)")
    args = parser.parse_args()

    # Load menu items
    with open(MENU_FILE) as f:
        menu_data = json.load(f)

    # Filter to actual items (skip category metadata)
    items = [item for item in menu_data if item.get("SK", "").startswith("ITEM#")]
    logger.info("Found %d menu items to process", len(items))
    logger.info("Using model: %s in %s", MODEL_ID, args.region)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    client = boto3.client(
        service_name="bedrock-runtime",
        region_name=args.region,
        config=Config(read_timeout=300),
    )

    generated = 0
    skipped = 0
    failed = 0

    for item in items:
        # Derive filename from imageUrl field, replacing .svg with .png
        image_url = item.get("imageUrl", "")
        filename = os.path.basename(image_url)
        if not filename:
            logger.warning("Skipping item %s — no imageUrl", item.get("name"))
            continue

        png_filename = os.path.splitext(filename)[0] + ".png"
        output_path = os.path.join(OUTPUT_DIR, png_filename)

        if os.path.exists(output_path) and not args.force:
            logger.info("Skipping %s — already exists", png_filename)
            skipped += 1
            continue

        name = item["name"]
        description = item.get("description", name)
        prompt = build_prompt(name, description)

        logger.info("Generating image for: %s", name)
        logger.info("  Prompt: %s", prompt[:120] + "...")

        try:
            image_bytes = generate_image(client, prompt)
            with open(output_path, "wb") as out:
                out.write(image_bytes)
            logger.info("  Saved: %s (%d KB)", png_filename, len(image_bytes) // 1024)
            generated += 1
        except (ClientError, RuntimeError) as e:
            logger.error("  Failed to generate %s: %s", name, e)
            failed += 1

        # Small delay to avoid throttling
        time.sleep(2)

    logger.info("Done! Generated: %d, Skipped: %d, Failed: %d", generated, skipped, failed)

    if generated > 0:
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Review the generated images in data/images/")
        logger.info("  2. Run: python scripts/update_menu_image_refs.py")


if __name__ == "__main__":
    main()
