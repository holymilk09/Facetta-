"""Collections organize families without owning or mutating Studio lineage."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from facetta.db import (
    Base,
    CollectionFamilyMembership,
    DesignFamily,
    ImageAsset,
    Project,
    ProjectRevisionRecord,
    StudioCreateDecisionRecord,
    StudioJobRecord,
    WorkspaceCollection,
    _apply_additive_migrations,
    get_db,
    utcnow,
)
from facetta.main import create_app


OWNER_TOKEN = "collections-owner-token-1234"
OTHER_TOKEN = "collections-other-token-1234"
EMPTY_TOKEN = "collections-empty-token-1234"


def _headers(token: str = OWNER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_lineage(Session) -> None:
    with Session() as db:
        owner_asset = ImageAsset(
            id="ast_collection_owner",
            root_id="ast_collection_owner",
            parent_asset_id=None,
            design_id=None,
            design_version=1,
            capability="SPEC_RENDER",
            instruction="Exact saved ring",
            image=b"owner-image",
            media_type="image/png",
            created_by="usr_owner",
        )
        other_asset = ImageAsset(
            id="ast_collection_other",
            root_id="ast_collection_other",
            parent_asset_id=None,
            design_id=None,
            design_version=1,
            capability="SPEC_RENDER",
            instruction="Other tenant ring",
            image=b"other-image",
            media_type="image/png",
            created_by="usr_other",
        )
        db.add_all([
            DesignFamily(
                id="fam_collection_owner",
                owner="usr_owner",
                title="Oval signet family",
            ),
            DesignFamily(
                id="fam_collection_other",
                owner="usr_other",
                title="Private other family",
            ),
            owner_asset,
            other_asset,
            Project(
                root_id=owner_asset.id,
                owner="usr_owner",
                collection=None,
                title="Oval signet original",
                tags=["signet"],
                family_id="fam_collection_owner",
                variation_index=1,
            ),
            Project(
                root_id=other_asset.id,
                owner="usr_other",
                collection=None,
                title="Other original",
                tags=[],
                family_id="fam_collection_other",
                variation_index=1,
            ),
            ProjectRevisionRecord(
                id="prr_collection_owner",
                asset_id=owner_asset.id,
                action="created",
                raw_intent={"text": "Exact saved ring"},
                interpretation={"preserved": True},
                change_summary="Created the exact saved ring.",
                created_by="usr_owner",
            ),
        ])
        db.commit()


def _client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_lineage(Session)
    monkeypatch.setenv("FACETTA_ENV", "test")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "opaque")
    monkeypatch.setenv(
        "FACETTA_AUTH_PRINCIPALS_JSON",
        json.dumps({
            OWNER_TOKEN: "usr_owner",
            OTHER_TOKEN: "usr_other",
            EMPTY_TOKEN: "usr_empty",
        }),
    )
    application = create_app()

    def override():
        with Session() as db:
            yield db

    application.dependency_overrides[get_db] = override
    return TestClient(application), Session


def test_collection_many_to_many_owner_isolation_and_safe_delete(monkeypatch):
    client, Session = _client(monkeypatch)
    with Session() as db:
        # Collection organization is metadata-only. Keep a settled generation
        # job in the same workspace so this end-to-end lifecycle proves that
        # create, membership, archive, and delete never add or alter charges.
        db.add(StudioJobRecord(
            id="job_collection_credit_invariant",
            owner="usr_owner",
            action_id="create",
            lane="fast_visual",
            status="succeeded",
            progress=1.0,
            active_design_id="ast_collection_owner",
            source_revision_id=None,
            requested_outputs=1,
            credits_per_output=20,
            completed_outputs=1,
            charged_outputs=1,
        ))
        db.commit()
    with client:
        client_collection = client.post(
            "/studio/collections",
            headers=_headers(),
            json={
                "name": "  Sarah K   engagement  ",
                "template": "client",
                "metadata": {"client_name": "Sarah K"},
            },
        )
        assert client_collection.status_code == 201, client_collection.text
        assert client_collection.json()["name"] == "Sarah K engagement"
        campaign = client.post(
            "/studio/collections",
            headers=_headers(),
            json={"name": "Spring campaign", "template": "campaign"},
        )
        assert campaign.status_code == 201, campaign.text
        collection_ids = [
            client_collection.json()["id"], campaign.json()["id"],
        ]

        for collection_id in collection_ids:
            added = client.put(
                "/studio/design-families/fam_collection_owner/collections/"
                + collection_id,
                headers=_headers(),
            )
            assert added.status_code == 204, added.text

        family_collections = client.get(
            "/studio/design-families/fam_collection_owner/collections",
            headers=_headers(),
        )
        assert family_collections.status_code == 200
        assert {item["id"] for item in family_collections.json()["collections"]} == set(
            collection_ids
        )
        search = client.get(
            "/studio/collections?q=spring", headers=_headers(),
        )
        assert [item["name"] for item in search.json()["collections"]] == [
            "Spring campaign"
        ]

        # Other tenants cannot discover Collections or attach private families.
        assert client.get(
            "/studio/collections", headers=_headers(OTHER_TOKEN),
        ).json() == {"collections": []}
        denied = client.put(
            "/studio/design-families/fam_collection_owner/collections/"
            + collection_ids[0],
            headers=_headers(OTHER_TOKEN),
        )
        assert denied.status_code == 404

        with Session() as db:
            lineage_before = {
                "families": list(db.scalars(select(DesignFamily.id))),
                "projects": list(db.scalars(select(Project.root_id))),
                "assets": list(db.scalars(select(ImageAsset.id))),
                "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
                "jobs": list(db.execute(select(
                    StudioJobRecord.id,
                    StudioJobRecord.status,
                    StudioJobRecord.requested_outputs,
                    StudioJobRecord.completed_outputs,
                    StudioJobRecord.charged_outputs,
                    StudioJobRecord.credits_per_output,
                ))),
            }

        archived = client.patch(
            f"/studio/collections/{collection_ids[0]}",
            headers=_headers(),
            json={"archived": True},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["family_count"] == 0
        deleted = client.delete(
            f"/studio/collections/{collection_ids[1]}", headers=_headers(),
        )
        assert deleted.status_code == 204, deleted.text
        assert client.get(
            "/studio/design-families/fam_collection_owner/collections",
            headers=_headers(),
        ).json() == {"collections": []}

        with Session() as db:
            lineage_after = {
                "families": list(db.scalars(select(DesignFamily.id))),
                "projects": list(db.scalars(select(Project.root_id))),
                "assets": list(db.scalars(select(ImageAsset.id))),
                "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
                "jobs": list(db.execute(select(
                    StudioJobRecord.id,
                    StudioJobRecord.status,
                    StudioJobRecord.requested_outputs,
                    StudioJobRecord.completed_outputs,
                    StudioJobRecord.charged_outputs,
                    StudioJobRecord.credits_per_output,
                ))),
            }
            memberships = list(db.scalars(
                select(CollectionFamilyMembership).where(
                    CollectionFamilyMembership.family_id
                    == "fam_collection_owner"
                )
            ))
            assert len(memberships) == 2
            assert all(item.removed_at is not None for item in memberships)
        assert lineage_after == lineage_before


def test_aggregate_membership_index_is_complete_visible_and_owner_scoped(
    monkeypatch,
):
    client, Session = _client(monkeypatch)
    now = utcnow()
    with Session() as db:
        db.add_all([
            DesignFamily(
                id="fam_collection_owner_empty",
                owner="usr_owner",
                title="Owner family without collections",
            ),
            WorkspaceCollection(
                id="col_index_active",
                owner="usr_owner",
                name="Active collection",
                name_key="active collection",
                template="generic",
                template_metadata={},
            ),
            WorkspaceCollection(
                id="col_index_removed",
                owner="usr_owner",
                name="Removed membership",
                name_key="removed membership",
                template="generic",
                template_metadata={},
            ),
            WorkspaceCollection(
                id="col_index_archived",
                owner="usr_owner",
                name="Archived collection",
                name_key=None,
                template="generic",
                template_metadata={},
                archived_at=now,
            ),
            WorkspaceCollection(
                id="col_index_deleted",
                owner="usr_owner",
                name="Deleted collection",
                name_key=None,
                template="generic",
                template_metadata={},
                archived_at=now,
                deleted_at=now,
            ),
            WorkspaceCollection(
                id="col_index_other",
                owner="usr_other",
                name="Other owner collection",
                name_key="other owner collection",
                template="generic",
                template_metadata={},
            ),
        ])
        db.flush()
        db.add_all([
            CollectionFamilyMembership(
                collection_id="col_index_active",
                family_id="fam_collection_owner",
                owner="usr_owner",
            ),
            CollectionFamilyMembership(
                collection_id="col_index_removed",
                family_id="fam_collection_owner",
                owner="usr_owner",
                removed_at=now,
            ),
            CollectionFamilyMembership(
                collection_id="col_index_archived",
                family_id="fam_collection_owner",
                owner="usr_owner",
            ),
            CollectionFamilyMembership(
                collection_id="col_index_deleted",
                family_id="fam_collection_owner",
                owner="usr_owner",
            ),
            CollectionFamilyMembership(
                collection_id="col_index_other",
                family_id="fam_collection_other",
                owner="usr_other",
            ),
            # Corrupt cross-owner evidence must never widen either workspace's
            # aggregate view even if the membership owner itself is spoofed.
            CollectionFamilyMembership(
                collection_id="col_index_other",
                family_id="fam_collection_owner",
                owner="usr_owner",
            ),
            # A malformed denormalized owner must not let another tenant's
            # family inflate the Collection summary shown to this workspace.
            CollectionFamilyMembership(
                collection_id="col_index_active",
                family_id="fam_collection_other",
                owner="usr_owner",
            ),
        ])
        db.commit()
        before = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "memberships": list(db.execute(select(
                CollectionFamilyMembership.collection_id,
                CollectionFamilyMembership.family_id,
                CollectionFamilyMembership.removed_at,
            ))),
        }

    with client:
        owner = client.get(
            "/studio/collection-memberships",
            headers=_headers(),
        )
        assert owner.status_code == 200, owner.text
        assert owner.json() == {
            "family_collection_ids": {
                "fam_collection_owner": ["col_index_active"],
                "fam_collection_owner_empty": [],
            },
        }
        other = client.get(
            "/studio/collection-memberships",
            headers=_headers(OTHER_TOKEN),
        )
        assert other.json() == {
            "family_collection_ids": {
                "fam_collection_other": ["col_index_other"],
            },
        }
        empty = client.get(
            "/studio/collection-memberships",
            headers=_headers(EMPTY_TOKEN),
        )
        assert empty.json() == {"family_collection_ids": {}}
        denied = client.get(
            "/studio/collection-memberships",
            params={"owner": "usr_other"},
            headers=_headers(),
        )
        assert denied.status_code == 404
        collections = client.get(
            "/studio/collections",
            headers=_headers(),
        )
        assert collections.status_code == 200, collections.text
        counts = {
            item["id"]: item["family_count"]
            for item in collections.json()["collections"]
        }
        assert counts["col_index_active"] == 1
        assert counts["col_index_removed"] == 0

    with Session() as db:
        after = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "memberships": list(db.execute(select(
                CollectionFamilyMembership.collection_id,
                CollectionFamilyMembership.family_id,
                CollectionFamilyMembership.removed_at,
            ))),
        }
    assert after == before


def test_family_favorite_is_persisted_idempotent_and_lineage_neutral(
    monkeypatch,
):
    client, Session = _client(monkeypatch)
    with Session() as db:
        db.add(StudioJobRecord(
            id="job_favorite_invariant",
            owner="usr_owner",
            action_id="create",
            lane="fast_visual",
            status="succeeded",
            progress=1.0,
            active_design_id="ast_collection_owner",
            source_revision_id=None,
            requested_outputs=1,
            credits_per_output=20,
            completed_outputs=1,
            charged_outputs=1,
        ))
        db.commit()
        family = db.get(DesignFamily, "fam_collection_owner")
        assert family is not None
        original_updated_at = family.updated_at
        original_state = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "job": tuple(db.execute(select(
                StudioJobRecord.status,
                StudioJobRecord.completed_outputs,
                StudioJobRecord.charged_outputs,
                StudioJobRecord.credits_per_output,
            )).one()),
        }

    with client:
        listing = client.get("/studio/families", headers=_headers())
        assert listing.status_code == 200, listing.text
        owner_family = next(
            item for item in listing.json()["families"]
            if item["family_id"] == "fam_collection_owner"
        )
        assert owner_family["is_favorite"] is False
        assert owner_family["favorited_at"] is None
        detail = client.get(
            "/studio/families/fam_collection_owner",
            headers=_headers(),
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["is_favorite"] is False

        first = client.put(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(),
        )
        assert first.status_code == 204 and first.content == b""
        first_detail = client.get(
            "/studio/families/fam_collection_owner",
            headers=_headers(),
        ).json()
        assert first_detail["is_favorite"] is True
        assert first_detail["favorited_at"] is not None
        favorited_at = first_detail["favorited_at"]

        second = client.put(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(),
        )
        assert second.status_code == 204 and second.content == b""
        assert client.get(
            "/studio/families/fam_collection_owner",
            headers=_headers(),
        ).json()["favorited_at"] == favorited_at

        denied_put = client.put(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(OTHER_TOKEN),
        )
        denied_delete = client.delete(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(OTHER_TOKEN),
        )
        assert denied_put.status_code == denied_delete.status_code == 404

        favorited_listing = client.get(
            "/studio/families", headers=_headers(),
        ).json()["families"]
        assert favorited_listing[0]["is_favorite"] is True
        assert favorited_listing[0]["favorited_at"] == favorited_at

        first_delete = client.delete(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(),
        )
        second_delete = client.delete(
            "/studio/design-families/fam_collection_owner/favorite",
            headers=_headers(),
        )
        assert first_delete.status_code == second_delete.status_code == 204
        final_detail = client.get(
            "/studio/families/fam_collection_owner",
            headers=_headers(),
        ).json()
        assert final_detail["is_favorite"] is False
        assert final_detail["favorited_at"] is None

    with Session() as db:
        family = db.get(DesignFamily, "fam_collection_owner")
        assert family is not None
        assert family.updated_at == original_updated_at
        assert family.favorited_at is None
        final_state = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "job": tuple(db.execute(select(
                StudioJobRecord.status,
                StudioJobRecord.completed_outputs,
                StudioJobRecord.charged_outputs,
                StudioJobRecord.credits_per_output,
            )).one()),
        }
    assert final_state == original_state


def test_family_tags_are_owner_scoped_persistent_and_lineage_neutral(monkeypatch):
    client, Session = _client(monkeypatch)
    with Session() as db:
        db.add(StudioJobRecord(
            id="job_tag_invariant",
            owner="usr_owner",
            action_id="create",
            lane="fast_visual",
            status="succeeded",
            progress=1.0,
            active_design_id="ast_collection_owner",
            source_revision_id=None,
            requested_outputs=2,
            credits_per_output=15,
            completed_outputs=2,
            charged_outputs=2,
        ))
        db.commit()
        family = db.get(DesignFamily, "fam_collection_owner")
        assert family is not None
        original_updated_at = family.updated_at
        before = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "job": tuple(db.execute(select(
                StudioJobRecord.status,
                StudioJobRecord.requested_outputs,
                StudioJobRecord.completed_outputs,
                StudioJobRecord.charged_outputs,
                StudioJobRecord.credits_per_output,
            )).one()),
        }

    with client:
        saved = client.put(
            "/studio/design-families/fam_collection_owner/tags",
            headers=_headers(),
            json={"tags": ["  Bridal ", "SAPPHIRE", "bridal"]},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json() == {
            "family_id": "fam_collection_owner",
            "tags": ["bridal", "sapphire"],
        }
        repeated = client.put(
            "/studio/design-families/fam_collection_owner/tags",
            headers=_headers(),
            json={"tags": ["sapphire", "bridal"]},
        )
        assert repeated.status_code == 200
        assert repeated.json() == saved.json()
        assert client.get(
            "/studio/families/fam_collection_owner", headers=_headers(),
        ).json()["tags"] == ["bridal", "sapphire"]
        listing = client.get("/studio/families", headers=_headers()).json()
        owner_family = next(
            item for item in listing["families"]
            if item["family_id"] == "fam_collection_owner"
        )
        assert owner_family["tags"] == ["bridal", "sapphire"]

        denied = client.put(
            "/studio/design-families/fam_collection_owner/tags",
            headers=_headers(OTHER_TOKEN),
            json={"tags": ["stolen"]},
        )
        assert denied.status_code == 404
        invalid = client.put(
            "/studio/design-families/fam_collection_owner/tags",
            headers=_headers(),
            json={"tags": ["bad\nvalue"]},
        )
        assert invalid.status_code == 422
        forbidden_lineage_payload = client.put(
            "/studio/design-families/fam_collection_owner/tags",
            headers=_headers(),
            json={"tags": ["bridal"], "asset_id": "ast_collection_owner"},
        )
        assert forbidden_lineage_payload.status_code == 422

    with Session() as db:
        family = db.get(DesignFamily, "fam_collection_owner")
        assert family is not None
        assert family.tags == ["bridal", "sapphire"]
        assert family.updated_at == original_updated_at
        after = {
            "projects": list(db.scalars(select(Project.root_id))),
            "assets": list(db.scalars(select(ImageAsset.id))),
            "revisions": list(db.scalars(select(ProjectRevisionRecord.id))),
            "job": tuple(db.execute(select(
                StudioJobRecord.status,
                StudioJobRecord.requested_outputs,
                StudioJobRecord.completed_outputs,
                StudioJobRecord.charged_outputs,
                StudioJobRecord.credits_per_output,
            )).one()),
        }
    assert after == before


def test_family_listing_and_detail_use_newest_child_project_activity(
    monkeypatch,
):
    client, Session = _client(monkeypatch)
    baseline = utcnow() - timedelta(days=7)
    owner_family_id = "fam_collection_owner"
    other_family_id = "fam_collection_recent_other"
    other_asset_id = "ast_collection_recent_other"
    with Session() as db:
        owner_family = db.get(DesignFamily, owner_family_id)
        owner_project = db.get(Project, "ast_collection_owner")
        assert owner_family is not None and owner_project is not None
        # A family row can be newer than its child for metadata reasons, but
        # Recent represents actual design activity whenever a child exists.
        owner_family.updated_at = baseline + timedelta(days=5)
        owner_project.updated_at = baseline
        db.add_all([
            DesignFamily(
                id=other_family_id,
                owner="usr_owner",
                title="More recently worked family",
                created_at=baseline,
                updated_at=baseline,
            ),
            ImageAsset(
                id=other_asset_id,
                root_id=other_asset_id,
                parent_asset_id=None,
                design_id=None,
                design_version=1,
                capability="SPEC_RENDER",
                instruction="Second exact saved ring",
                image=b"second-owner-image",
                media_type="image/png",
                created_by="usr_owner",
                created_at=baseline,
            ),
            Project(
                root_id=other_asset_id,
                owner="usr_owner",
                collection=None,
                title="Second owner original",
                tags=[],
                family_id=other_family_id,
                variation_index=1,
                created_at=baseline,
                updated_at=baseline + timedelta(days=2),
            ),
        ])
        db.commit()

    with client:
        initial = client.get("/studio/families", headers=_headers())
        assert initial.status_code == 200, initial.text
        assert [
            family["family_id"] for family in initial.json()["families"]
        ] == [other_family_id, owner_family_id]
        assert initial.json()["families"][1]["updated_at"] == (
            baseline.replace(tzinfo=None).isoformat()
        )

        newest_activity = baseline + timedelta(days=3)
        with Session() as db:
            owner_project = db.get(Project, "ast_collection_owner")
            assert owner_project is not None
            owner_project.updated_at = newest_activity
            db.commit()

        refreshed = client.get("/studio/families", headers=_headers())
        assert refreshed.status_code == 200, refreshed.text
        assert [
            family["family_id"] for family in refreshed.json()["families"]
        ] == [owner_family_id, other_family_id]
        assert refreshed.json()["families"][0]["updated_at"] == (
            newest_activity.replace(tzinfo=None).isoformat()
        )

        detail = client.get(
            f"/studio/families/{owner_family_id}",
            headers=_headers(),
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["updated_at"] == (
            newest_activity.replace(tzinfo=None).isoformat()
        )


def test_historical_atomic_create_reopens_selected_original_until_real_activity(
    monkeypatch,
):
    client, Session = _client(monkeypatch)
    family_id = "fam_historical_atomic"
    original_id = "ast_historical_original"
    selected_id = "ast_historical_selected"
    retained_id = "ast_historical_retained"
    candidate_id = original_id
    commit_side_effect_at = utcnow() - timedelta(days=2)
    committed_at = commit_side_effect_at + timedelta(microseconds=10)

    with Session() as db:
        other_family = db.get(DesignFamily, "fam_collection_owner")
        other_project = db.get(Project, "ast_collection_owner")
        assert other_family is not None and other_project is not None
        # Raw SQL activity puts this unrelated family between the atomic
        # branch rows and the decision. The compatibility projection must
        # therefore also repair cross-family Recent ordering.
        other_activity = commit_side_effect_at + timedelta(microseconds=5)
        other_family.updated_at = other_activity
        other_project.updated_at = other_activity
        db.add_all([
            DesignFamily(
                id=family_id,
                owner="usr_owner",
                title="Historical atomic Create family",
                created_at=commit_side_effect_at,
                updated_at=commit_side_effect_at,
            ),
            ImageAsset(
                id=original_id,
                root_id=original_id,
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="CREATIVE_RENDER",
                instruction="Retained first direction",
                image=b"historical-original-candidate",
                media_type="image/png",
                created_by="usr_owner",
                created_at=commit_side_effect_at,
            ),
            ImageAsset(
                id=selected_id,
                root_id=original_id,
                parent_asset_id=original_id,
                design_id=None,
                design_version=None,
                capability="CREATIVE_RENDER",
                instruction="Selected second direction",
                image=b"historical-selected-candidate",
                media_type="image/png",
                created_by="usr_owner",
                created_at=commit_side_effect_at,
            ),
            Project(
                root_id=original_id,
                owner="usr_owner",
                collection=None,
                title="Historical selected direction",
                tags=[],
                family_id=family_id,
                variation_index=1,
                variation_label="Original",
                selected_candidate_asset_id=selected_id,
                created_at=commit_side_effect_at,
                updated_at=commit_side_effect_at,
            ),
            ImageAsset(
                id=retained_id,
                root_id=retained_id,
                parent_asset_id=None,
                design_id=None,
                design_version=None,
                capability="VARIATION_BRANCH",
                instruction="Historical retained Create direction",
                image=b"historical-retained-image",
                media_type="image/png",
                created_by="usr_owner",
                created_at=commit_side_effect_at,
            ),
            Project(
                root_id=retained_id,
                owner="usr_owner",
                collection=None,
                title="Historical selected direction",
                tags=[],
                family_id=family_id,
                variation_index=2,
                variation_label="Direction 1",
                selected_candidate_asset_id=retained_id,
                branched_from_project_root_id=original_id,
                branched_from_asset_id=candidate_id,
                created_at=commit_side_effect_at,
                updated_at=commit_side_effect_at,
            ),
            StudioCreateDecisionRecord(
                project_root_id=original_id,
                owner="usr_owner",
                selected_candidate_asset_id=selected_id,
                retained_directions=[{
                    "candidate_id": candidate_id,
                    "label": "Direction 1",
                    "family_id": family_id,
                    "variation_index": 2,
                    "project_root_id": retained_id,
                    "asset_id": retained_id,
                }],
                studio_job_id=None,
                created_by="usr_owner",
                committed_at=committed_at,
            ),
            ProjectRevisionRecord(
                id="prr_historical_selected",
                asset_id=selected_id,
                action="created",
                raw_intent={
                    "kind": "create_direction_commit",
                    "create_decision_project_root_id": original_id,
                    "selected_candidate_asset_id": selected_id,
                    "source_asset_id": selected_id,
                },
                interpretation={"operation": "select_original_direction"},
                change_summary="Selected Direction 2 as Original.",
                created_by="usr_owner",
                created_at=commit_side_effect_at,
            ),
            ProjectRevisionRecord(
                id="prr_historical_retained",
                asset_id=retained_id,
                action="created",
                raw_intent={
                    "kind": "save_as_variation",
                    "source_project_id": original_id,
                    "source_asset_id": candidate_id,
                    "label": "Direction 1",
                },
                interpretation={"operation": "fork_variation"},
                change_summary="Saved Direction 1 as a variation.",
                created_by="usr_owner",
                created_at=commit_side_effect_at,
            ),
        ])
        db.commit()

    with client:
        listing = client.get("/studio/families", headers=_headers())
        assert listing.status_code == 200, listing.text
        listed_family = next(
            item for item in listing.json()["families"]
            if item["family_id"] == family_id
        )
        listed_recent = max(
            listed_family["variations"],
            key=lambda variation: variation["updated_at"],
        )
        assert listed_recent["root_id"] == original_id
        assert listed_recent["cover_asset_id"] == selected_id
        assert listing.json()["families"][0]["family_id"] == family_id

        historical = client.get(
            f"/studio/families/{family_id}", headers=_headers(),
        )
        assert historical.status_code == 200, historical.text
        variations = historical.json()["variations"]
        recently_active = max(
            variations, key=lambda variation: variation["updated_at"],
        )
        assert recently_active["root_id"] == original_id
        assert recently_active["cover_asset_id"] == selected_id
        assert recently_active["updated_at"] == (
            committed_at.replace(tzinfo=None).isoformat()
        )

        later_activity = committed_at + timedelta(seconds=1)
        with Session() as db:
            retained = db.get(Project, retained_id)
            assert retained is not None
            retained.updated_at = later_activity
            db.commit()

        refreshed = client.get(
            f"/studio/families/{family_id}", headers=_headers(),
        )
        assert refreshed.status_code == 200, refreshed.text
        genuinely_recent = max(
            refreshed.json()["variations"],
            key=lambda variation: variation["updated_at"],
        )
        assert genuinely_recent["root_id"] == retained_id
        assert genuinely_recent["updated_at"] == (
            later_activity.replace(tzinfo=None).isoformat()
        )

    # The compatibility view never rewrites canonical project history.
    with Session() as db:
        original = db.get(Project, original_id)
        retained = db.get(Project, retained_id)
        assert original is not None and retained is not None
        assert original.updated_at == commit_side_effect_at.replace(tzinfo=None)
        assert retained.updated_at == later_activity.replace(tzinfo=None)


def test_local_collection_listing_requires_unambiguous_owner(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_lineage(Session)
    with Session() as db:
        db.add_all([
            WorkspaceCollection(
                id="col_local_owner",
                owner="usr_owner",
                name="Owner private collection",
                name_key="owner private collection",
                template="generic",
                template_metadata={},
            ),
            WorkspaceCollection(
                id="col_local_other",
                owner="usr_other",
                name="Other private collection",
                name_key="other private collection",
                template="generic",
                template_metadata={},
            ),
        ])
        db.commit()
    monkeypatch.setenv("FACETTA_ENV", "test")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "test")
    application = create_app()

    def override():
        with Session() as db:
            yield db

    application.dependency_overrides[get_db] = override
    with TestClient(application) as client:
        omitted = client.get("/studio/collections")
        assert omitted.status_code == 422
        assert "exactly one owner" in omitted.json()["detail"]
        scoped = client.get(
            "/studio/collections", params={"owner": "usr_owner"},
        )
        assert scoped.status_code == 200, scoped.text
        assert [
            item["id"] for item in scoped.json()["collections"]
        ] == ["col_local_owner"]
        omitted_index = client.get("/studio/collection-memberships")
        assert omitted_index.status_code == 422
        scoped_index = client.get(
            "/studio/collection-memberships",
            params={"owner": "usr_owner"},
        )
        assert scoped_index.status_code == 200, scoped_index.text
        assert scoped_index.json() == {
            "family_collection_ids": {"fam_collection_owner": []},
        }

        # Resource-addressed local mutations derive scope from the exact row;
        # they do not require the whole database to have only one owner.
        favorite = client.put(
            "/studio/design-families/fam_collection_owner/favorite"
        )
        assert favorite.status_code == 204, favorite.text
        with Session() as db:
            family = db.get(DesignFamily, "fam_collection_owner")
            assert family is not None and family.favorited_at is not None
        wrong_owner = client.delete(
            "/studio/design-families/fam_collection_owner/favorite",
            params={"owner": "usr_other"},
        )
        assert wrong_owner.status_code == 404
        unfavorite = client.delete(
            "/studio/design-families/fam_collection_owner/favorite"
        )
        assert unfavorite.status_code == 204

        updated = client.patch(
            "/studio/collections/col_local_owner",
            json={"name": "Owner renamed collection"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Owner renamed collection"
        member = client.put(
            "/studio/design-families/fam_collection_owner/collections/"
            "col_local_owner"
        )
        assert member.status_code == 204, member.text
        cross_owner = client.put(
            "/studio/design-families/fam_collection_other/collections/"
            "col_local_owner"
        )
        assert cross_owner.status_code == 404

        ambiguous_create = client.post(
            "/studio/collections",
            json={"name": "Must choose an owner"},
        )
        assert ambiguous_create.status_code == 422
        scoped_create = client.post(
            "/studio/collections",
            params={"owner": "usr_owner"},
            json={"name": "Owner-scoped new collection"},
        )
        assert scoped_create.status_code == 201, scoped_create.text
        assert scoped_create.json()["name"] == "Owner-scoped new collection"


def test_favorited_at_migration_is_additive_and_preserves_legacy_family():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE design_families ("
            "id VARCHAR(32) PRIMARY KEY, owner VARCHAR(32), "
            "title VARCHAR(200), created_at DATETIME, updated_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO design_families "
            "(id, owner, title, created_at, updated_at) VALUES "
            "('fam_legacy_favorite', 'usr_legacy', 'Legacy favorite family', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    Base.metadata.create_all(engine)

    _apply_additive_migrations(engine)
    _apply_additive_migrations(engine)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("design_families")
    }
    assert "favorited_at" in columns
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT owner, title, favorited_at FROM design_families "
            "WHERE id = 'fam_legacy_favorite'"
        )).one()
    assert row == ("usr_legacy", "Legacy favorite family", None)


def test_family_tags_migration_unions_legacy_variations_once_without_rewriting_projects():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE design_families ("
            "id VARCHAR(32) PRIMARY KEY, owner VARCHAR(32), "
            "title VARCHAR(200), created_at DATETIME, updated_at DATETIME)"
        ))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO design_families "
            "(id, owner, title, created_at, updated_at) VALUES "
            "('fam_legacy_tags', 'usr_legacy', 'Legacy tagged family', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        for variation_index, (root_id, raw_tags) in enumerate((
            ("ast_legacy_tags_1", '[" Sapphire ", "Bridal"]'),
            ("ast_legacy_tags_2", '["sapphire", "CLIENT REVIEW"]'),
        ), start=1):
            connection.execute(text(
                "INSERT INTO projects "
                "(root_id, owner, collection, title, tags, family_id, "
                "variation_index, created_at, updated_at) VALUES "
                "(:root_id, 'usr_legacy', NULL, 'Legacy variation', :tags, "
                "'fam_legacy_tags', :variation_index, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {
                "root_id": root_id,
                "tags": raw_tags,
                "variation_index": variation_index,
            })

    _apply_additive_migrations(engine)
    _apply_additive_migrations(engine)
    with engine.connect() as connection:
        family_tags = connection.execute(text(
            "SELECT tags FROM design_families WHERE id = 'fam_legacy_tags'"
        )).scalar_one()
        project_tags = list(connection.execute(text(
            "SELECT tags FROM projects WHERE family_id = 'fam_legacy_tags' "
            "ORDER BY root_id"
        )).scalars())
    assert json.loads(family_tags) == ["bridal", "client review", "sapphire"]
    assert project_tags == [
        '[" Sapphire ", "Bridal"]',
        '["sapphire", "CLIENT REVIEW"]',
    ]

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE design_families SET tags = '[\"custom\"]' "
            "WHERE id = 'fam_legacy_tags'"
        ))
    _apply_additive_migrations(engine)
    with engine.connect() as connection:
        family_tags = connection.execute(text(
            "SELECT tags FROM design_families WHERE id = 'fam_legacy_tags'"
        )).scalar_one()
    assert json.loads(family_tags) == ["custom"]


def test_legacy_project_collection_bootstrap_is_additive_and_non_resurrecting():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        asset = ImageAsset(
            id="ast_legacy_collection",
            root_id="ast_legacy_collection",
            parent_asset_id=None,
            design_version=1,
            capability="SPEC_RENDER",
            image=b"legacy",
            media_type="image/png",
            created_by="usr_legacy",
        )
        db.add_all([
            DesignFamily(
                id="fam_legacy_collection",
                owner="usr_legacy",
                title="Legacy family",
            ),
            asset,
            Project(
                root_id=asset.id,
                owner="usr_legacy",
                collection="  Client Archive  ",
                title="Legacy ring",
                tags=[],
                family_id="fam_legacy_collection",
                variation_index=1,
            ),
        ])
        db.commit()

    _apply_additive_migrations(engine)
    with Session() as db:
        collection = db.scalar(select(WorkspaceCollection))
        assert collection is not None
        assert collection.name == "Client Archive"
        assert collection.template == "generic"
        membership = db.get(CollectionFamilyMembership, (
            collection.id, "fam_legacy_collection",
        ))
        assert membership is not None and membership.removed_at is None
        original_project = db.get(Project, "ast_legacy_collection")
        assert original_project is not None
        assert original_project.collection == "  Client Archive  "
        assert original_project.family_id == "fam_legacy_collection"
        membership.removed_at = utcnow()
        db.commit()

    _apply_additive_migrations(engine)
    with Session() as db:
        collection = db.scalar(select(WorkspaceCollection))
        assert collection is not None
        membership = db.get(CollectionFamilyMembership, (
            collection.id, "fam_legacy_collection",
        ))
        assert membership is not None and membership.removed_at is not None
        assert db.get(Project, "ast_legacy_collection").collection == (
            "  Client Archive  "
        )


def test_fresh_schema_and_production_surface_expose_collection_routes(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert {
        WorkspaceCollection.__tablename__,
        CollectionFamilyMembership.__tablename__,
    } <= set(inspector.get_table_names())

    monkeypatch.setenv("FACETTA_ENV", "production")
    monkeypatch.setenv("FACETTA_AUTH_MODE", "supabase")
    monkeypatch.setenv(
        "FACETTA_SUPABASE_URL", "https://facetta-test.supabase.co",
    )
    paths = create_app().openapi()["paths"]
    operations = {
        (method.upper(), path)
        for path, path_operations in paths.items()
        for method in path_operations
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }
    assert {
        ("GET", "/studio/collections"),
        ("GET", "/studio/collection-memberships"),
        ("POST", "/studio/collections"),
        ("PATCH", "/studio/collections/{collection_id}"),
        ("DELETE", "/studio/collections/{collection_id}"),
        ("PUT", "/studio/design-families/{family_id}/favorite"),
        ("DELETE", "/studio/design-families/{family_id}/favorite"),
        ("PUT", "/studio/design-families/{family_id}/tags"),
        ("GET", "/studio/design-families/{family_id}/collections"),
        (
            "PUT",
            "/studio/design-families/{family_id}/collections/{collection_id}",
        ),
        (
            "DELETE",
            "/studio/design-families/{family_id}/collections/{collection_id}",
        ),
    } <= operations
