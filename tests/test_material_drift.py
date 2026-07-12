from __future__ import annotations

import io

from PIL import Image, ImageDraw

from facetta.image_agent.material_drift import white_stone_to_gold_drift


def _leaf_cluster(*, stones_gold: bool) -> bytes:
    image = Image.new("RGB", (500, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 120, 430, 330), outline=(185, 125, 35), width=18)
    for row in range(4):
        for col in range(7):
            x = 105 + col * 45
            y = 90 + row * 44
            fill = (205, 145, 45) if stones_gold else (238, 241, 246)
            draw.ellipse((x, y, x + 30, y + 30), fill=fill,
                         outline=(70, 70, 75), width=3)
            draw.line((x + 4, y + 15, x + 26, y + 15), fill=(120, 120, 125), width=2)
            draw.line((x + 15, y + 4, x + 15, y + 26), fill=(120, 120, 125), width=2)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_large_white_stone_to_gold_reassignment_fails_deterministically():
    source = _leaf_cluster(stones_gold=False)
    changed = _leaf_cluster(stones_gold=True)
    result = white_stone_to_gold_drift(source, changed)
    assert result["checked"] is True
    assert result["failed"] is True
    assert result["white_to_gold_ratio"] > 0.18


def test_unchanged_white_stones_do_not_fail():
    source = _leaf_cluster(stones_gold=False)
    result = white_stone_to_gold_drift(source, source)
    assert result["checked"] is True
    assert result["failed"] is False
