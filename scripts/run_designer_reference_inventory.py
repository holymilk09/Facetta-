"""Build an advisory, varied-workflow inventory of all founder references.

The script groups the 144 source files into labeled contact sheets and asks
Grok Vision only how each tile should be routed for evaluation.  It never asks
for dimensions, stone facts, specifications, or approval.  The original files
remain outside the repository; output contains hashes and advisory labels.

Usage:
    PYTHONPATH=src uv run python scripts/run_designer_reference_inventory.py RUN_NAME
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.image_agent.vision import vision_json  # noqa: E402
from facetta.reference_inventory import (  # noqa: E402
    ReferenceInventoryItem,
    summarize_reference_inventory,
    validate_inventory_page,
)


DEFAULT_SOURCE_DIR = Path(
    "/Users/mattfb/.codex/attachments/"
    "c2fd41d0-b236-43ef-ada9-e9479718c771"
)
PAGE_SIZE = 16
TILE_WIDTH = 300
TILE_HEIGHT = 350
GRID_COLUMNS = 4

SYSTEM = """\
You inventory founder-supplied jewelry reference images for a private product
evaluation corpus. The contact sheet contains labeled tiles. Classify workflow
fit only; do not infer measurements, specifications, stone identity, value,
authorship, approval, or manufacturability.

Return JSON exactly:
{"items":[{"filename":"image-1.jpg",
 "primary_category":"ring|earrings|necklace|pendant|brooch|bracelet|loose_stone|reference_chart|mixed|unknown",
 "input_kind":"hand_drawing|line_art|colored_design_plate|finished_jewelry_photo|inspiration_product_composite|technical_sheet|reference_chart|mixed|unknown",
 "workflow_fit":["one or more exact values from the allowed list below"],
 "multi_design":false,"watermark_or_branding":false,
 "complexity":"simple|moderate|complex","confidence":0.0,
 "notes":"brief routing evidence"}]}

Emit exactly one item for every requested filename and no others. A comparison
grid, taxonomy, sizing chart, social-media montage, or many unrelated designs
is not one clean design source; mark it multi_design and/or reference_chart and
include exclude_as_source when appropriate. A visible account mark, logo,
caption, signature, or platform watermark sets watermark_or_branding true.

ALLOWED WORKFLOW VALUES: plate_read, photo_read, lineart_color, beauty_render,
localized_edit, product_photography, factory_sheet, catalog_reference,
reference_chart, technical_benchmark, exclude_as_source.
"""


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _contact_sheet(paths: tuple[Path, ...]) -> bytes:
    rows = (len(paths) + GRID_COLUMNS - 1) // GRID_COLUMNS
    sheet = Image.new(
        "RGB",
        (GRID_COLUMNS * TILE_WIDTH, rows * TILE_HEIGHT),
        "#f4f1eb",
    )
    label_font = _font(24)
    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((TILE_WIDTH - 16, TILE_HEIGHT - 52))
        cell_x = (index % GRID_COLUMNS) * TILE_WIDTH
        cell_y = (index // GRID_COLUMNS) * TILE_HEIGHT
        x = cell_x + (TILE_WIDTH - image.width) // 2
        y = cell_y + 8 + (TILE_HEIGHT - 52 - image.height) // 2
        sheet.paste(image, (x, y))
        draw = ImageDraw.Draw(sheet)
        draw.text(
            (cell_x + 10, cell_y + TILE_HEIGHT - 36),
            path.name,
            fill="#111111",
            font=label_font,
        )
    output = BytesIO()
    sheet.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()


def _sources(source_dir: Path) -> tuple[Path, ...]:
    paths = tuple(source_dir / f"image-{number}.jpg" for number in range(1, 145))
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("missing founder references: " + ", ".join(missing))
    return paths


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _page_checkpoint(
    outdir: Path,
    page_number: int,
    expected: tuple[str, ...],
    source_hashes: tuple[str, ...],
) -> tuple[object | None, Path]:
    """Reuse only an exact-source, already validated page checkpoint."""

    path = outdir / f"page-{page_number:02d}.json"
    if not path.is_file():
        return None, path
    try:
        stored = json.loads(path.read_text())
        if (
            stored.get("filenames") != list(expected)
            or stored.get("source_hashes") != list(source_hashes)
        ):
            return None, path
        payload = stored.get("payload")
        validate_inventory_page(expected, payload)
        return payload, path
    except (OSError, AttributeError, ValueError, TypeError, json.JSONDecodeError):
        return None, path


def run(run_name: str, source_dir: Path) -> Path:
    load_env_file(ROOT / ".env")
    outdir = ROOT / "docs" / "evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    sources = _sources(source_dir)
    source_rows = [
        {
            "filename": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sources
    ]
    items: list[ReferenceInventoryItem] = []
    pages: list[dict[str, object]] = []
    for offset in range(0, len(sources), PAGE_SIZE):
        page_paths = sources[offset:offset + PAGE_SIZE]
        expected = tuple(path.name for path in page_paths)
        source_hashes = tuple(
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in page_paths
        )
        page_number = len(pages) + 1
        payload, checkpoint = _page_checkpoint(
            outdir, page_number, expected, source_hashes)
        cached = payload is not None
        started = time.perf_counter()
        if payload is None:
            payload = vision_json(
                SYSTEM,
                _contact_sheet(page_paths),
                "Classify exactly these labeled tiles: " + ", ".join(expected),
            )
        try:
            page = validate_inventory_page(expected, payload)
        except Exception:
            _write_json(
                outdir / f"page-{page_number:02d}-invalid.json",
                {
                    "filenames": list(expected),
                    "source_hashes": list(source_hashes),
                    "payload": payload,
                },
            )
            raise
        latency_ms = 0 if cached else round(
            (time.perf_counter() - started) * 1000)
        if not cached:
            _write_json(checkpoint, {
                "filenames": list(expected),
                "source_hashes": list(source_hashes),
                "payload": page.model_dump(mode="json"),
                "latency_ms": latency_ms,
            })
        items.extend(page.items)
        pages.append({
            "page": page_number,
            "filenames": list(expected),
            "latency_ms": latency_ms,
            "cached": cached,
        })
        print(f"OK inventory page {len(pages)}: {expected[0]}..{expected[-1]}", flush=True)

    inventory = tuple(items)
    result = {
        "run_name": run_name,
        "live": True,
        "provider_role": "advisory corpus routing only",
        "source_policy": (
            "Founder-supplied evaluation references only. Labels are advisory; "
            "they do not authorize publication, training, specifications, "
            "measurements, approval, or manufacturing."
        ),
        "sources": source_rows,
        "pages": pages,
        "items": [item.model_dump(mode="json") for item in inventory],
        "summary": summarize_reference_inventory(inventory),
    }
    _write_json(outdir / "results.json", result)
    (outdir / "README.md").write_text(
        f"# Founder reference workflow inventory — {run_name}\n\n"
        "This live Grok Vision run routes all 144 founder-supplied references "
        "into a varied evaluation matrix. It is advisory corpus triage only: "
        "no label is a specification, measurement, approval, training consent, "
        "or manufacturing fact. Original images are not copied into this result.\n"
    )
    return outdir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()
    outdir = run(args.run_name, args.source_dir)
    print(f">> artifacts: {outdir}", flush=True)


if __name__ == "__main__":
    main()
