"""Atomic, provider-free Studio fact revision behavior."""

from __future__ import annotations

import copy
import hashlib
from datetime import timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from conftest import EXAMPLE_SPEC

from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    utcnow,
)
from facetta.studio_fact_revision import (
    StudioFactRevisionError,
    apply_studio_fact_revision,
)


def _utc(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@pytest.fixture()
def fact_store():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    spec = copy.deepcopy(EXAMPLE_SPEC)
    spec.update({
        "design_id": "dsn_facts",
        "version": 1,
        "created_by": "usr_designer",
    })
    image = b"exact-studio-fact-source"
    with sessions() as db:
        db.add_all([
            Design(id="dsn_facts", created_by="usr_designer", created_at=now),
            DesignVersion(
                design_id="dsn_facts",
                version=1,
                spec=spec,
                created_by="usr_designer",
                created_at=now,
            ),
            ImageAsset(
                id="ast_facts_v1",
                root_id="ast_facts_v1",
                parent_asset_id=None,
                design_id="dsn_facts",
                design_version=1,
                capability="JEWELRY_RENDER",
                image=image,
                media_type="image/png",
                created_by="usr_designer",
                created_at=now,
            ),
            Project(
                root_id="ast_facts_v1",
                owner="usr_designer",
                title="Fact revision ring",
                tags=[],
                selected_candidate_asset_id="ast_facts_v1",
                created_at=now,
                updated_at=now,
            ),
        ])
        db.commit()
    return sessions, spec, image, now


def test_fact_revision_appends_spec_image_and_hash_evidence_in_one_commit(
    fact_store,
    monkeypatch,
):
    sessions, original_spec, image, original_updated_at = fact_store
    with sessions() as db:
        commits = 0
        real_commit = db.commit

        def counted_commit():
            nonlocal commits
            commits += 1
            real_commit()

        monkeypatch.setattr(db, "commit", counted_commit)
        result = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes={
                "band.width_mm": 2.2,
                "metal.finish": "satin",
            },
            created_by="usr_designer",
        )

    assert commits == 1
    assert result.status == "applied"
    assert result.source_asset_id == "ast_facts_v1"
    assert result.asset_id != result.source_asset_id
    assert result.previous_design_version == 1
    assert result.design_version == 2
    assert {change["path"] for change in result.spec_change} >= {
        "band.width_mm", "metal.finish",
    }

    with sessions() as db:
        v1 = db.get(DesignVersion, ("dsn_facts", 1))
        v2 = db.get(DesignVersion, ("dsn_facts", 2))
        child = db.get(ImageAsset, result.asset_id)
        project = db.get(Project, "ast_facts_v1")
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == result.asset_id
        ))
        assert v1 is not None and v1.spec == original_spec
        assert v2 is not None
        assert v2.spec["band"]["width_mm"] == 2.2
        assert v2.spec["metal"]["finish"] == "satin"
        assert v2.spec["dimension_provenance"]["band.width_mm"][
            "status"
        ] == "designer_confirmed"
        assert child is not None
        assert child.parent_asset_id == "ast_facts_v1"
        assert child.design_version == 2
        assert bytes(child.image) == image
        assert project is not None
        assert project.selected_candidate_asset_id == child.id
        assert _utc(project.updated_at) > _utc(original_updated_at)
        assert record is not None
        expected_hash = hashlib.sha256(image).hexdigest()
        assert record.raw_intent["facts"] == {
            "band.width_mm": 2.2,
            "metal.finish": "satin",
        }
        assert record.interpretation["source_sha256"] == expected_hash
        assert record.interpretation["output_sha256"] == expected_hash
        assert record.interpretation["image_generation"] is False
        assert record.interpretation["provider_used"] is False
        assert record.interpretation["factory_authority"] is False
        assert record.interpretation["credits_charged"] == 0


def test_no_op_fact_revision_writes_nothing(fact_store):
    sessions, _spec, _image, original_updated_at = fact_store
    with sessions() as db:
        result = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes={"band.width_mm": 1.8},
            created_by="usr_designer",
        )
    assert result.status == "no_change"
    assert result.asset_id == "ast_facts_v1"
    assert result.design_version == 1
    assert result.spec_change == ()
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0
        project = db.get(Project, "ast_facts_v1")
        assert project is not None
        assert _utc(project.updated_at) == _utc(original_updated_at)


def test_ring_size_fact_rederives_consistent_confirmed_inner_diameter(
    fact_store,
):
    sessions, _spec, _image, _updated_at = fact_store
    with sessions() as db:
        result = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes={"ring_size.value": 7.0},
            created_by="usr_designer",
        )
    assert result.status == "applied"
    with sessions() as db:
        stored = db.get(DesignVersion, ("dsn_facts", 2))
        assert stored is not None
        assert stored.spec["ring_size"]["value"] == 7.0
        assert stored.spec["ring_size"]["inner_diameter_mm"] != 16.9
        assert stored.spec["dimension_provenance"]["ring_size.value"][
            "status"
        ] == "designer_confirmed"
        assert stored.spec["dimension_provenance"][
            "ring_size.inner_diameter_mm"
        ]["status"] == "designer_confirmed"


def test_coupled_component_facts_clear_only_their_required_dependents(
    fact_store,
):
    sessions, _spec, _image, _updated_at = fact_store
    with sessions() as db:
        result = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes={
                "metal.material": "platinum",
                "setting.style": "bezel",
            },
            created_by="usr_designer",
        )
    assert result.status == "applied"
    with sessions() as db:
        stored = db.get(DesignVersion, ("dsn_facts", 2))
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == result.asset_id
        ))
        assert stored is not None and record is not None
        assert stored.spec["metal"] == {
            "material": "platinum",
            "karat": None,
            "color": None,
            "finish": "high_polish",
        }
        assert stored.spec["setting"]["style"] == "bezel"
        assert stored.spec["setting"]["prong_count"] is None
        assert stored.spec["setting"]["prong_tip_mm"] is None
        assert record.raw_intent["facts"] == {
            "metal.material": "platinum",
            "setting.style": "bezel",
        }
        assert set(record.interpretation["derived_fact_adjustments"]) == {
            "metal.karat",
            "metal.color",
            "setting.prong_count",
            "setting.prong_tip_mm",
        }


def test_coupled_component_facts_restore_with_explicit_dependencies(
    fact_store,
):
    sessions, _spec, _image, _updated_at = fact_store
    with sessions() as db:
        simplified = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes={
                "metal.material": "platinum",
                "setting.style": "bezel",
            },
            created_by="usr_designer",
        )
    with sessions() as db:
        restored = apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id=simplified.asset_id,
            expected_design_version=2,
            changes={
                "metal.material": "gold",
                "metal.karat": 18,
                "metal.color": "yellow",
                "setting.style": "4_prong_basket",
                "setting.prong_tip_mm": 0.9,
            },
            created_by="usr_designer",
        )
    assert restored.status == "applied"
    with sessions() as db:
        stored = db.get(DesignVersion, ("dsn_facts", 3))
        record = db.scalar(select(ProjectRevisionRecord).where(
            ProjectRevisionRecord.asset_id == restored.asset_id
        ))
        assert stored is not None and record is not None
        assert stored.spec["metal"] == {
            "material": "gold",
            "karat": 18,
            "color": "yellow",
            "finish": "high_polish",
        }
        assert stored.spec["setting"]["style"] == "4_prong_basket"
        assert stored.spec["setting"]["prong_count"] == 4
        assert stored.spec["setting"]["prong_tip_mm"] == 0.9
        assert record.raw_intent["facts"] == {
            "metal.material": "gold",
            "metal.karat": 18,
            "metal.color": "yellow",
            "setting.style": "4_prong_basket",
            "setting.prong_tip_mm": 0.9,
        }
        assert set(record.interpretation["derived_fact_adjustments"]) == {
            "setting.prong_count",
        }


@pytest.mark.parametrize(("changes", "code"), [
    ({"notes_to_factory": "skip review"}, "fact_path_not_allowed"),
    ({
        "stone.color": {
            "trade": "Royal Blue",
            "gia": "vivid blue",
            "hue_code": None,
            "tone": None,
            "saturation": None,
        },
        "stone.color.trade": "Cornflower Blue",
    }, "fact_path_conflict"),
    ({"setting.prong_count": 6}, "fact_dependency_conflict"),
    ({"band.width_mm": "wide"}, "fact_value_invalid"),
    ({"band.width_mm": -2.0}, "fact_value_invalid"),
    ({"stone.species": "unobtainium"}, "fact_revision_invalid"),
])
def test_unsafe_or_invalid_fact_change_fails_without_writes(
    fact_store,
    changes,
    code,
):
    sessions, _spec, _image, _updated_at = fact_store
    with sessions() as db, pytest.raises(StudioFactRevisionError) as exc:
        apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id="ast_facts_v1",
            expected_design_version=1,
            changes=changes,
            created_by="usr_designer",
        )
    assert exc.value.code == code
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1


@pytest.mark.parametrize(("asset_id", "version", "actor", "code"), [
    ("ast_stale", 1, "usr_designer", "stale_fact_revision"),
    ("ast_facts_v1", 2, "usr_designer", "stale_fact_revision"),
    ("ast_facts_v1", 1, "usr_other", "fact_revision_unavailable"),
])
def test_stale_or_foreign_fact_revision_fails_closed(
    fact_store,
    asset_id,
    version,
    actor,
    code,
):
    sessions, _spec, _image, _updated_at = fact_store
    with sessions() as db, pytest.raises(StudioFactRevisionError) as exc:
        apply_studio_fact_revision(
            db,
            project_root_id="ast_facts_v1",
            expected_active_asset_id=asset_id,
            expected_design_version=version,
            changes={"band.width_mm": 2.2},
            created_by=actor,
        )
    assert exc.value.code == code


def test_commit_fault_rolls_back_every_fact_revision_row(
    fact_store,
    monkeypatch,
):
    sessions, original_spec, _image, original_updated_at = fact_store
    with sessions() as db:
        def fail_after_flush():
            db.flush()
            raise RuntimeError("injected commit fault")

        monkeypatch.setattr(db, "commit", fail_after_flush)
        with pytest.raises(RuntimeError, match="injected commit fault"):
            apply_studio_fact_revision(
                db,
                project_root_id="ast_facts_v1",
                expected_active_asset_id="ast_facts_v1",
                expected_design_version=1,
                changes={"band.width_mm": 2.2},
                created_by="usr_designer",
            )

    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(DesignVersion)) == 1
        assert db.scalar(select(func.count()).select_from(ImageAsset)) == 1
        assert db.scalar(
            select(func.count()).select_from(ProjectRevisionRecord)
        ) == 0
        assert db.get(DesignVersion, ("dsn_facts", 1)).spec == original_spec
        project = db.get(Project, "ast_facts_v1")
        assert project is not None
        assert project.selected_candidate_asset_id == "ast_facts_v1"
        assert _utc(project.updated_at) == _utc(original_updated_at)
