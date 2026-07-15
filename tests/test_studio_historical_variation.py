"""A saved Studio Revision can branch without first becoming active."""

from __future__ import annotations

import copy
import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import HALO_SPEC
from facetta.api.studio import studio_history
from facetta.db import (
    Base,
    Design,
    DesignFamily,
    DesignVersion,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    RevisionComponentMapRecord,
    StudioVariationDecisionRecord,
    get_db,
    utcnow,
)
from facetta.design_form import NormalizedPoint, NormalizedPolygon
from facetta.main import app
from facetta.revision_component_map import (
    RevisionComponent,
    RevisionComponentMap,
    polygon_hash,
)
from facetta.revision_component_map_store import (
    add_revision_component_map,
    load_revision_component_map,
)
from facetta.studio_history import (
    StudioHistoryError,
    fork_project_revision_variation,
)


REQUIRED_COMPONENTS = (
    ("center", "center_stone"),
    ("prongs", "prongs"),
    ("setting", "setting"),
    ("shank", "shank"),
    ("shoulders", "shoulders"),
    ("gallery", "gallery"),
    ("metal", "metal_zone"),
    ("background", "background"),
)


def _png(color: tuple[int, int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (120, 120), color).save(output, format="PNG")
    return output.getvalue()


def _component_map(asset_id: str, image: bytes) -> RevisionComponentMap:
    components: list[RevisionComponent] = []
    for index, (component_id, kind) in enumerate(REQUIRED_COMPONENTS):
        offset = min(index, 4) * 0.01
        polygons = (NormalizedPolygon(points=(
            NormalizedPoint(x=0.2 + offset, y=0.2),
            NormalizedPoint(x=0.5 + offset, y=0.2),
            NormalizedPoint(x=0.5 + offset, y=0.5),
            NormalizedPoint(x=0.2 + offset, y=0.5),
        )),)
        components.append(RevisionComponent(
            component_id=component_id,
            kind=kind,
            label=component_id.title(),
            resolution="resolved",
            polygons=polygons,
            polygon_sha256=polygon_hash(polygons),
        ))
    return RevisionComponentMap(
        asset_id=asset_id,
        asset_sha256=hashlib.sha256(image).hexdigest(),
        raster_width=120,
        raster_height=120,
        jewelry_type="ring",
        mapper_contract="test.historical-vary.v1",
        components=tuple(components),
    )


def _spec(design_id: str, version: int, *, metal_color: str) -> dict:
    payload = copy.deepcopy(HALO_SPEC)
    payload.update({
        "design_id": design_id,
        "version": version,
        "created_by": "usr_history",
        "created_at": f"2026-07-0{version}T00:00:00Z",
    })
    payload["metal"]["color"] = metal_color
    return payload


def _revision_record(asset: ImageAsset, *, action: str) -> ProjectRevisionRecord:
    digest = hashlib.sha256(bytes(asset.image)).hexdigest()
    return ProjectRevisionRecord(
        id=f"prr_{asset.id}",
        asset_id=asset.id,
        action=action,
        raw_intent={"kind": "historical_vary_test"},
        interpretation={
            "operation": "test_revision",
            "output_sha256": digest,
        },
        change_summary=f"Saved {asset.id}.",
        created_by="usr_history",
    )


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_spec_history(Session):
    source_image = _png((210, 190, 150))
    active_image = _png((180, 160, 140))
    now = utcnow()
    with Session() as db:
        family = DesignFamily(
            id="fam_history",
            owner="usr_history",
            title="Historical family",
            created_at=now,
            updated_at=now,
        )
        source = ImageAsset(
            id="ast_history_source",
            root_id="ast_history_source",
            parent_asset_id=None,
            design_id="dsn_history",
            design_version=1,
            capability="IMPORTED_REFERENCE",
            image=source_image,
            media_type="image/png",
            created_by="usr_history",
            created_at=now,
        )
        active = ImageAsset(
            id="ast_history_active",
            root_id=source.id,
            parent_asset_id=source.id,
            design_id=None,
            design_version=2,
            capability="LOCALIZED_EDIT",
            image=active_image,
            media_type="image/png",
            created_by="usr_history",
            created_at=now,
        )
        project = Project(
            root_id=source.id,
            owner="usr_history",
            title="Historical ring",
            tags=["ring"],
            family_id=family.id,
            variation_index=1,
            variation_label="Original",
            created_at=now,
            updated_at=now,
        )
        db.add_all([
            family,
            Design(
                id="dsn_history",
                created_by="usr_history",
                created_at=now,
                collection=None,
            ),
            DesignVersion(
                design_id="dsn_history",
                version=1,
                spec=_spec("dsn_history", 1, metal_color="yellow"),
                created_by="usr_history",
                created_at=now,
            ),
            DesignVersion(
                design_id="dsn_history",
                version=2,
                spec=_spec("dsn_history", 2, metal_color="white"),
                created_by="usr_history",
                created_at=now,
            ),
            source,
            active,
            project,
            _revision_record(source, action="created"),
            _revision_record(active, action="edit"),
        ])
        db.flush()
        add_revision_component_map(
            db,
            _component_map(source.id, source_image),
            image_bytes=source_image,
            parent_asset_id=None,
        )
        db.commit()
    return {
        "project_id": "ast_history_source",
        "source_id": "ast_history_source",
        "active_id": "ast_history_active",
        "source_image": source_image,
        "active_image": active_image,
        "source_sha256": hashlib.sha256(source_image).hexdigest(),
        "project_updated_at": now,
    }


def _counts(db: Session) -> tuple[int, ...]:
    models = (
        Design,
        DesignVersion,
        ImageAsset,
        Project,
        ProjectRevisionRecord,
        RevisionComponentMapRecord,
        StudioVariationDecisionRecord,
    )
    return tuple(
        db.scalar(select(func.count()).select_from(model)) or 0
        for model in models
    )


def _truth(spec: dict) -> dict:
    return {
        key: value
        for key, value in spec.items()
        if key not in {"design_id", "version", "created_by", "created_at"}
    }


def test_revision_route_branches_historical_spec_and_map_without_restore():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        request = {
            "created_by": "usr_history",
            "expected_active_asset_id": seeded["active_id"],
            "expected_active_design_version": 2,
            "expected_source_design_version": 1,
            "expected_source_sha256": seeded["source_sha256"],
            "label": "Original yellow-gold direction",
            "operation_id": "vary:history-yellow-0001",
        }
        before = client.get(
            f"/studio/projects/{seeded['project_id']}/history"
        ).json()
        response = client.post(
            f"/studio/projects/{seeded['project_id']}/revisions/"
            f"{seeded['source_id']}/variations",
            json=request,
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["source_asset_id"] == seeded["source_id"]
        assert payload["source_design_version"] == 1
        assert payload["source_sha256"] == seeded["source_sha256"]
        assert payload["guarded_active_asset_id"] == seeded["active_id"]
        assert payload["guarded_active_design_version"] == 2
        assert payload["child_sha256"] == seeded["source_sha256"]
        assert payload["component_map_status"] == "mapped"
        assert len(payload["component_map_sha256"]) == 64
        assert payload["variation"] == {
            "project_root_id": payload["child_project_root_id"],
            "asset_id": payload["child_asset_id"],
            "design_id": payload["child_design_id"],
            "design_version": 1,
            "family_id": "fam_history",
            "variation_index": 2,
            "branched_from_project_root_id": seeded["project_id"],
            "branched_from_asset_id": seeded["source_id"],
            "component_map_status": "mapped",
            "component_map_sha256": payload["component_map_sha256"],
        }

        with Session() as db:
            child = db.get(ImageAsset, payload["child_asset_id"])
            child_project = db.get(Project, payload["child_project_root_id"])
            source_project = db.get(Project, seeded["project_id"])
            child_spec = db.get(
                DesignVersion,
                (payload["child_design_id"], payload["child_design_version"]),
            )
            source_spec = db.get(DesignVersion, ("dsn_history", 1))
            active_spec = db.get(DesignVersion, ("dsn_history", 2))
            child_map = load_revision_component_map(db, payload["child_asset_id"])
            assert child is not None and bytes(child.image) == seeded["source_image"]
            assert child_project is not None
            assert child_project.branched_from_asset_id == seeded["source_id"]
            assert child_spec is not None and source_spec is not None
            assert active_spec is not None
            assert _truth(child_spec.spec) == _truth(source_spec.spec)
            assert _truth(child_spec.spec) != _truth(active_spec.spec)
            assert child_map is not None
            assert source_project is not None
            assert source_project.updated_at == seeded[
                "project_updated_at"
            ].replace(tzinfo=None)
            assert source_project.selected_candidate_asset_id is None
            assert list(db.scalars(select(ImageAsset.id).where(
                ImageAsset.root_id == seeded["project_id"]
            ))) == [seeded["source_id"], seeded["active_id"]]

        after = client.get(
            f"/studio/projects/{seeded['project_id']}/history"
        ).json()
        assert after == before
        assert after["active_asset_id"] == seeded["active_id"]
        assert [item["sha256"] for item in after["revisions"]] == [
            seeded["source_sha256"],
            hashlib.sha256(seeded["active_image"]).hexdigest(),
        ]
        assert all(
            item["capability"] != "RESTORED_REVISION"
            for item in after["revisions"]
        )

        replay = client.post(
            f"/studio/projects/{seeded['project_id']}/revisions/"
            f"{seeded['source_id']}/variations",
            json=request,
        )
        assert replay.status_code == 201, replay.text
        assert replay.json() == payload
        mismatch = client.post(
            f"/studio/projects/{seeded['project_id']}/revisions/"
            f"{seeded['source_id']}/variations",
            json={**request, "label": "Reused for another label"},
        )
        assert mismatch.status_code == 409, mismatch.text
        assert mismatch.json()["code"] == "variation_operation_conflict"
        with Session() as db:
            assert db.query(StudioVariationDecisionRecord).count() == 1
            assert db.query(Project).count() == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("request_overrides", "created_by", "expected_code"),
    (
        ({"expected_active_asset_id": "ast_wrong"}, "usr_history",
         "stale_asset_revision"),
        ({"expected_active_design_version": 1}, "usr_history",
         "stale_design_version"),
        ({"expected_source_design_version": 2}, "usr_history",
         "stale_source_design_version"),
        ({"expected_source_sha256": "0" * 64}, "usr_history",
         "stale_source_revision"),
        ({}, "usr_foreign", "variation_source_unavailable"),
    ),
)
def test_revision_branch_rejects_stale_or_foreign_source_without_rows(
    request_overrides,
    created_by,
    expected_code,
):
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    with Session() as db:
        before = _counts(db)
        request = {
            "project_root_id": seeded["project_id"],
            "source_asset_id": seeded["source_id"],
            "expected_source_design_version": 1,
            "expected_source_sha256": seeded["source_sha256"],
            "expected_active_asset_id": seeded["active_id"],
            "expected_active_design_version": 2,
            "variation_label": "Rejected branch",
            "created_by": created_by,
            "operation_id": f"vary:rejected-{expected_code}",
        }
        request.update(request_overrides)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(db, **request)
        assert error.value.code == expected_code
        assert _counts(db) == before


def test_corrupt_component_map_rolls_back_the_whole_revision_branch():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    with Session() as db:
        db.execute(text(
            "UPDATE revision_component_maps SET map_sha256 = :hash "
            "WHERE asset_id = :asset_id"
        ), {"hash": "0" * 64, "asset_id": seeded["source_id"]})
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(
                db,
                project_root_id=seeded["project_id"],
                source_asset_id=seeded["source_id"],
                expected_source_design_version=1,
                expected_source_sha256=seeded["source_sha256"],
                expected_active_asset_id=seeded["active_id"],
                expected_active_design_version=2,
                variation_label="Must roll back",
                created_by="usr_history",
                operation_id="vary:corrupt-map-0001",
            )
        assert error.value.code == "variation_component_map_invalid"
        assert _counts(db) == before
        assert db.get(Project, seeded["project_id"]).updated_at == seeded[
            "project_updated_at"
        ].replace(tzinfo=None)


def test_missing_source_spec_creates_no_partial_variation_rows():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    with Session() as db:
        db.execute(text(
            "DELETE FROM design_versions "
            "WHERE design_id = 'dsn_history' AND version = 1"
        ))
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(
                db,
                project_root_id=seeded["project_id"],
                source_asset_id=seeded["source_id"],
                expected_source_design_version=1,
                expected_source_sha256=seeded["source_sha256"],
                expected_active_asset_id=seeded["active_id"],
                expected_active_design_version=2,
                variation_label="Missing source truth",
                created_by="usr_history",
                operation_id="vary:missing-spec-0001",
            )
        assert error.value.code == "variation_spec_unavailable"
        assert _counts(db) == before


def test_idempotent_replay_revalidates_committed_child_bytes():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    request = {
        "project_root_id": seeded["project_id"],
        "source_asset_id": seeded["source_id"],
        "expected_source_design_version": 1,
        "expected_source_sha256": seeded["source_sha256"],
        "expected_active_asset_id": seeded["active_id"],
        "expected_active_design_version": 2,
        "variation_label": "Replay evidence",
        "created_by": "usr_history",
        "operation_id": "vary:replay-evidence-0001",
    }
    with Session() as db:
        first = fork_project_revision_variation(db, **request)
        db.execute(
            text("UPDATE image_assets SET image = :image WHERE id = :id"),
            {"image": b"corrupt committed child", "id": first.asset_id},
        )
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(db, **request)
        assert error.value.code == "variation_result_hash_mismatch"
        assert _counts(db) == before


def test_idempotent_replay_rejects_detached_child_component_map():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    request = {
        "project_root_id": seeded["project_id"],
        "source_asset_id": seeded["source_id"],
        "expected_source_design_version": 1,
        "expected_source_sha256": seeded["source_sha256"],
        "expected_active_asset_id": seeded["active_id"],
        "expected_active_design_version": 2,
        "variation_label": "Replay map evidence",
        "created_by": "usr_history",
        "operation_id": "vary:replay-map-0001",
    }
    with Session() as db:
        first = fork_project_revision_variation(db, **request)
        db.execute(text(
            "UPDATE revision_component_maps SET parent_asset_id = NULL "
            "WHERE asset_id = :asset_id"
        ), {"asset_id": first.asset_id})
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(db, **request)
        assert error.value.code == "variation_component_map_invalid"
        assert error.value.status_code == 500
        assert _counts(db) == before


def test_idempotent_replay_rejects_child_that_is_no_longer_a_chain_root():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    request = {
        "project_root_id": seeded["project_id"],
        "source_asset_id": seeded["source_id"],
        "expected_source_design_version": 1,
        "expected_source_sha256": seeded["source_sha256"],
        "expected_active_asset_id": seeded["active_id"],
        "expected_active_design_version": 2,
        "variation_label": "Replay root evidence",
        "created_by": "usr_history",
        "operation_id": "vary:replay-root-0001",
    }
    with Session() as db:
        first = fork_project_revision_variation(db, **request)
        db.execute(text(
            "UPDATE image_assets SET parent_asset_id = :parent "
            "WHERE id = :asset_id"
        ), {
            "parent": seeded["source_id"],
            "asset_id": first.asset_id,
        })
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(db, **request)
        assert error.value.code == "variation_decision_corrupt"
        assert error.value.status_code == 500
        assert _counts(db) == before


def test_idempotent_replay_rejects_child_rebound_from_design_v1():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    request = {
        "project_root_id": seeded["project_id"],
        "source_asset_id": seeded["source_id"],
        "expected_source_design_version": 1,
        "expected_source_sha256": seeded["source_sha256"],
        "expected_active_asset_id": seeded["active_id"],
        "expected_active_design_version": 2,
        "variation_label": "Replay design binding",
        "created_by": "usr_history",
        "operation_id": "vary:replay-design-binding-0001",
    }
    with Session() as db:
        first = fork_project_revision_variation(db, **request)
        child_v1 = db.get(DesignVersion, (first.design_id, 1))
        assert child_v1 is not None
        db.add(DesignVersion(
            design_id=first.design_id,
            version=2,
            spec=dict(child_v1.spec),
            created_by="usr_history",
        ))
        db.flush()
        db.execute(text(
            "UPDATE image_assets SET design_version = 2 WHERE id = :asset_id"
        ), {"asset_id": first.asset_id})
        db.commit()
        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(db, **request)
        assert error.value.code == "variation_decision_corrupt"
        assert error.value.status_code == 500
        assert _counts(db) == before


def test_mapped_variation_root_can_branch_again_with_immediate_map_lineage():
    Session = _session_factory()
    seeded = _seed_spec_history(Session)
    with Session() as db:
        first = fork_project_revision_variation(
            db,
            project_root_id=seeded["project_id"],
            source_asset_id=seeded["source_id"],
            expected_source_design_version=1,
            expected_source_sha256=seeded["source_sha256"],
            expected_active_asset_id=seeded["active_id"],
            expected_active_design_version=2,
            variation_label="First mapped branch",
            created_by="usr_history",
            operation_id="vary:mapped-branch-first-0001",
        )
        second = fork_project_revision_variation(
            db,
            project_root_id=first.project_root_id,
            source_asset_id=first.asset_id,
            expected_source_design_version=1,
            expected_source_sha256=first.output_sha256,
            expected_active_asset_id=first.asset_id,
            expected_active_design_version=1,
            variation_label="Second mapped branch",
            created_by="usr_history",
            operation_id="vary:mapped-branch-second-0001",
        )

        assert second.source_project_id == first.project_root_id
        assert second.source_asset_id == first.asset_id
        assert second.component_map_status == "mapped"
        second_map = db.get(RevisionComponentMapRecord, second.asset_id)
        assert second_map is not None
        assert second_map.parent_asset_id == first.asset_id
        assert load_revision_component_map(db, second.asset_id) is not None


def test_selected_pre_spec_revision_can_branch_but_unselected_candidate_cannot():
    Session = _session_factory()
    selected_bytes = _png((80, 120, 180))
    active_bytes = _png((90, 130, 190))
    with Session() as db:
        selected = ImageAsset(
            id="ast_prespec_selected",
            root_id="ast_prespec_selected",
            parent_asset_id=None,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=selected_bytes,
            media_type="image/png",
            created_by="usr_prespec",
        )
        unselected = ImageAsset(
            id="ast_prespec_unselected",
            root_id=selected.id,
            parent_asset_id=selected.id,
            design_version=None,
            capability="CREATIVE_RENDER",
            image=_png((200, 80, 80)),
            media_type="image/png",
            created_by="usr_prespec",
        )
        active = ImageAsset(
            id="ast_prespec_active",
            root_id=selected.id,
            parent_asset_id=selected.id,
            design_version=None,
            capability="GLOBAL_RESTYLE",
            image=active_bytes,
            media_type="image/png",
            created_by="usr_prespec",
        )
        project = Project(
            root_id=selected.id,
            owner="usr_prespec",
            title="Pre-spec direction",
            tags=[],
            selected_candidate_asset_id=active.id,
        )
        db.add_all([selected, unselected, active, project])
        db.commit()

        result = fork_project_revision_variation(
            db,
            project_root_id=project.root_id,
            source_asset_id=selected.id,
            expected_source_design_version=None,
            expected_source_sha256=hashlib.sha256(selected_bytes).hexdigest(),
            expected_active_asset_id=active.id,
            expected_active_design_version=None,
            variation_label="Selected first direction",
            created_by="usr_prespec",
            operation_id="vary:prespec-selected-0001",
        )
        assert result.source_design_version is None
        assert result.design_id is None and result.design_version is None
        assert result.component_map_status == "unmapped"
        assert result.component_map_sha256 is None
        assert bytes(db.get(ImageAsset, result.asset_id).image) == selected_bytes
        history = studio_history(project.root_id, db)
        assert history["active_asset_id"] == active.id
        assert [item["asset_id"] for item in history["revisions"]] == [
            selected.id,
            active.id,
        ]

        before = _counts(db)
        with pytest.raises(StudioHistoryError) as error:
            fork_project_revision_variation(
                db,
                project_root_id=project.root_id,
                source_asset_id=unselected.id,
                expected_source_design_version=None,
                expected_source_sha256=hashlib.sha256(
                    bytes(unselected.image)
                ).hexdigest(),
                expected_active_asset_id=active.id,
                expected_active_design_version=None,
                variation_label="Abandoned candidate",
                created_by="usr_prespec",
                operation_id="vary:prespec-unselected-0001",
            )
        assert error.value.code == "variation_source_not_revision"
        assert _counts(db) == before
