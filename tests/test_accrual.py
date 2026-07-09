"""The accrual pipeline: real designer approvals -> a style training set.

is_style_worthy filters the obvious wrong shapes (technical drawings, worn
shots, too-small) and REPORTS every drop; export_approved_training_set pulls
pinned or accepted assets, filters them, and writes a manifest. Approval is
the primary signal; nothing is dropped silently.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import Base, FeedbackEvent, ImageAsset, new_id, utcnow
from facetta.tuning import export_approved_training_set, is_style_worthy


def _png(color, size=(640, 640)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


RENDER = _png((185, 170, 150))          # a product render on a light studio bg
DRAWING = _png((252, 252, 252))         # near-white, desaturated: a drawing
WORN = _png((150, 90, 70))              # skin-toned, dim: a hand shot
TINY = _png((185, 170, 150), size=(200, 200))


@pytest.fixture
def db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _asset(db, image, *, capability="JEWELRY_RENDER", pinned=False,
           media_type="image/png"):
    a = ImageAsset(id=new_id("ast"), root_id="r", capability=capability,
                   image=image, media_type=media_type,
                   pinned_at=utcnow() if pinned else None)
    a.root_id = a.id
    db.add(a)
    db.commit()
    return a


class TestIsStyleWorthy:
    def test_a_product_render_passes(self):
        ok, reason = is_style_worthy(RENDER)
        assert ok and reason == ""

    def test_a_technical_drawing_is_rejected(self):
        ok, reason = is_style_worthy(DRAWING)
        assert not ok and "drawing" in reason

    def test_a_worn_shot_is_rejected_when_product_only(self):
        ok, reason = is_style_worthy(WORN, product_only=True)
        assert not ok and "worn" in reason
        # but kept when the caller explicitly wants worn shots
        assert is_style_worthy(WORN, product_only=False)[0] is True

    def test_too_small_is_rejected(self):
        ok, reason = is_style_worthy(TINY)
        assert not ok and "too small" in reason


class TestExportApprovedTrainingSet:
    def test_only_approved_renders_export_with_reasons(self, db, tmp_path):
        _asset(db, RENDER, pinned=True)
        accepted = _asset(db, RENDER)
        db.add(FeedbackEvent(asset_id=accepted.id, action="accepted"))
        drawing = _asset(db, DRAWING, capability="MANUFACTURING_TECHNICAL_DRAWING",
                         pinned=True)
        worn = _asset(db, WORN, pinned=True)
        _asset(db, RENDER)                            # not approved -> ignored
        regen = _asset(db, RENDER)
        db.add(FeedbackEvent(asset_id=regen.id, action="regenerated"))
        db.commit()

        manifest = export_approved_training_set(db, tmp_path / "out")

        assert manifest["kept"] == 2                  # pinned + accepted renders
        dropped = {d["id"]: d["reason"] for d in manifest["dropped"]}
        assert "technical drawing" in dropped[drawing.id]
        assert "worn" in dropped[worn.id]
        assert regen.id not in dropped                # not approved: never seen
        files = list((tmp_path / "out").glob("*.jpg"))
        assert len(files) == 2

    def test_empty_when_nothing_approved(self, db, tmp_path):
        _asset(db, RENDER)                            # exists, not approved
        manifest = export_approved_training_set(db, tmp_path / "out")
        assert manifest["kept"] == 0 and manifest["dropped"] == []

    def test_include_worn_keeps_hand_shots(self, db, tmp_path):
        _asset(db, WORN, pinned=True)
        manifest = export_approved_training_set(db, tmp_path / "out",
                                                product_only=False)
        assert manifest["kept"] == 1
