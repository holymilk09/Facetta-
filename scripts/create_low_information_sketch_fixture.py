"""Create a deterministic low-information jewelry sketch for live regression.

This is synthetic evaluation evidence, never represented as founder/customer
artwork. It deliberately supplies uneven lines and incomplete construction so
the image agent must combine visible evidence with an explicit designer brief.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw


def _jittered_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    *,
    rng: random.Random,
    fill: tuple[int, int, int],
    width: int,
) -> None:
    jittered = [
        (round(x + rng.uniform(-2.5, 2.5)), round(y + rng.uniform(-2.5, 2.5)))
        for x, y in points
    ]
    draw.line(jittered, fill=fill, width=width, joint="curve")


def render_fixture() -> Image.Image:
    rng = random.Random(1947)
    image = Image.new("RGB", (768, 768), (244, 238, 224))
    draw = ImageDraw.Draw(image)
    pencil = (75, 72, 67)
    faint = (142, 132, 116)

    # One front/three-quarter idea: the imperfect double loop is the shank.
    for inset in (0, 12):
        box = (154 + inset, 224 + inset, 614 - inset, 690 - inset)
        draw.ellipse(box, outline=pencil if inset == 0 else faint, width=5)
    # Open shoulders climbing toward the head.
    _jittered_line(draw, [(175, 390), (226, 300), (292, 230), (335, 196)],
                   rng=rng, fill=pencil, width=7)
    _jittered_line(draw, [(593, 392), (548, 302), (480, 230), (435, 198)],
                   rng=rng, fill=pencil, width=7)

    # Oval green center with a loose inner facet scribble.
    draw.ellipse((304, 95, 464, 265), fill=(103, 174, 132),
                 outline=pencil, width=7)
    _jittered_line(draw, [(384, 106), (327, 179), (384, 251), (447, 179),
                          (384, 106)], rng=rng, fill=(44, 109, 76), width=4)
    _jittered_line(draw, [(327, 179), (447, 179)], rng=rng,
                   fill=(44, 109, 76), width=3)

    # Four indicated claws, intentionally without basket/gallery construction.
    for start, end in [
        ((313, 116), (340, 142)), ((455, 116), (428, 142)),
        ((313, 243), (340, 218)), ((455, 243), (428, 218)),
    ]:
        _jittered_line(draw, [start, end], rng=rng, fill=pencil, width=8)

    # Three small shoulder stones per side; placement is visible, settings are not.
    for x, y in [(276, 239), (246, 272), (219, 309),
                 (492, 239), (522, 272), (549, 309)]:
        draw.ellipse((x - 12, y - 12, x + 12, y + 12),
                     fill=(234, 234, 229), outline=pencil, width=4)

    # Loose designer arrows/notes communicate intent without exact dimensions.
    _jittered_line(draw, [(116, 116), (271, 157), (300, 168)],
                   rng=rng, fill=faint, width=3)
    draw.text((42, 76), "green oval", fill=pencil, stroke_width=0)
    _jittered_line(draw, [(610, 194), (535, 232), (505, 246)],
                   rng=rng, fill=faint, width=3)
    draw.text((588, 153), "3 small stones", fill=pencil, stroke_width=0)
    draw.text((42, 710), "yellow gold / simple band", fill=pencil)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    render_fixture().save(args.output, format="PNG")


if __name__ == "__main__":
    main()
