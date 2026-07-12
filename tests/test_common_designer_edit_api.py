"""Trusted API coverage for common designer-directed structural edits.

The language/image providers are seams in these tests.  Target resolution,
scope guarding, physical validation, optimistic concurrency, immutable spec
versioning, image-revision persistence, and transaction rollback all run for
real.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from facetta.agent import (
    Annotation,
    ScopedEditResult,
    resolve_target,
    scope_guard,
)
from facetta.db import Base, get_db
from facetta.image_agent import (
    CheckSeverity,
    ImageQualityReport,
    JewelryImageAgent,
    ProviderImage,
    QualityCheck,
    QualityVerdict,
)
from facetta.main import app
from facetta.spec import Spec

from conftest import HALO_SPEC


Planner = Callable[[Annotation, Spec], ScopedEditResult]


def _png(color: tuple[int, int, int] = (200, 200, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(
        assets_mod,
        "jewelry_render",
        lambda *args, **kwargs: (_png(), False),
    )
    monkeypatch.setattr(
        assets_mod,
        "check_design_consistency",
        lambda reference, candidate: {
            "consistent": True,
            "differences": [],
            "severity": "none",
            "checked": True,
        },
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _linked_asset(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/designs",
        json={"created_by": "usr_designer", "spec": HALO_SPEC},
    )
    assert created.status_code == 201, created.text
    design_id = created.json()["design_id"]
    rendered = client.post(
        "/assets/render",
        json={"piece_description": "a halo ring", "design_id": design_id},
    )
    assert rendered.status_code == 201, rendered.text
    return rendered.json()["asset_id"], design_id


def _install_passing_image_agent(monkeypatch) -> list:
    plans = []

    class Provider:
        def execute(
            self,
            plan,
            route,
            prompt,
            *,
            source_image,
            mask_bytes,
        ):
            plans.append(plan)
            return ProviderImage(image_bytes=_png((80, 70, 60)))

    class Evaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            return ImageQualityReport(
                verdict=QualityVerdict.PASS,
                checks=(QualityCheck(
                    code="requested_change",
                    passed=True,
                    severity=CheckSeverity.HARD,
                    message="the scoped edit was applied",
                ),),
                score=98,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), Evaluator()),
    )
    return plans


def _install_planner(monkeypatch, planner: Planner) -> None:
    import facetta.grokedit as grokedit

    monkeypatch.setattr(grokedit, "grok_plan_scoped_edit", planner)


def _shoulder_group() -> dict:
    return {
        "species": "diamond",
        "cut": "round_brilliant",
        "carat": 0.01,
        "dimensions_mm": {"length": 1.3, "width": 1.3, "depth": 0.85},
        "color": {"trade": "F", "gia": "colorless"},
        "clarity": {"system": "gia_diamond", "grade": "VS2"},
        "count": 6,
        "position": "shoulder",
        "phenomena": [],
    }


def _inventory_planner(action: str) -> Planner:
    def planner(annotation: Annotation, current: Spec) -> ScopedEditResult:
        target = resolve_target(current, annotation)
        assert target == ("side_stones", None)
        proposed = current.model_dump(mode="json")
        if action == "add":
            proposed["side_stones"].append(_shoulder_group())
        elif action == "remove":
            proposed["side_stones"] = [
                group for group in proposed["side_stones"]
                if group.get("position") != "shoulder"
            ]
        elif action == "impossible":
            proposed["side_stones"][0]["count"] = 64
        else:  # pragma: no cover - test helper misuse
            raise AssertionError(f"unknown inventory action: {action}")

        # Simulate a model trying to be over-helpful.  The real structural
        # guard must discard both changes because only the inventory was named.
        proposed["metal"]["color"] = "yellow"
        proposed["band"]["width_mm"] = 7.0
        guarded, changed, ignored = scope_guard(
            current,
            target,
            Spec.model_validate(proposed),
        )
        return ScopedEditResult(
            spec=guarded,
            target="side_stones inventory",
            changed_fields=changed,
            ignored_fields=ignored,
            message=f"side-stone inventory {action}",
        )

    return planner


def _shape_planner(annotation: Annotation, current: Spec) -> ScopedEditResult:
    target = resolve_target(current, annotation)
    assert target == ("stone_assembly", None)
    proposed = current.model_dump(mode="json")
    proposed["stone"]["cut"] = "marquise"
    proposed["stone"]["carat"] = 1.1
    proposed["setting"]["style"] = "6_prong_basket"
    proposed["setting"]["prong_count"] = 6

    # These are deliberately out of scope.  A coupled stone/setting edit must
    # not become permission to redesign the shank or alloy.
    proposed["metal"]["color"] = "yellow"
    proposed["band"]["width_mm"] = 7.0
    guarded, changed, ignored = scope_guard(
        current,
        target,
        Spec.model_validate(proposed),
    )
    return ScopedEditResult(
        spec=guarded,
        target="center stone shape and its setting",
        isolate_ref="A",
        changed_fields=changed,
        ignored_fields=ignored,
        message="oval center changed to a marquise with adapted prongs",
    )


def _apply_inventory(
    client: TestClient,
    asset_id: str,
    *,
    expected_version: int,
    instruction: str,
):
    return client.post(
        f"/assets/{asset_id}/markup/apply",
        json={
            "expected_design_version": expected_version,
            "created_by": "usr_designer",
            "annotations": [{
                "region_description": "the side-stone layout",
                "change_instruction": instruction,
                "target_section": "side_stones",
            }],
        },
    )


def test_whole_side_stone_inventory_add_remove_is_atomic_and_version_guarded(
    client,
    monkeypatch,
):
    plans = _install_passing_image_agent(monkeypatch)
    asset_v1, design_id = _linked_asset(client)

    _install_planner(monkeypatch, _inventory_planner("add"))
    added = _apply_inventory(
        client,
        asset_v1,
        expected_version=1,
        instruction="add six round diamonds to the shoulders",
    )
    assert added.status_code == 201, added.text
    added_body = added.json()
    asset_v2 = added_body["final_asset_id"]
    assert added_body["revision"]["asset"]["design_version"] == 2
    assert added_body["spec_version"] == 2
    assert added_body["qa"]["verdict"] == "pass"
    assert {change["kind"] for change in added_body["spec_change"]} == {"added"}
    assert all(change["path"].startswith("side_stones.1.")
               for change in added_body["spec_change"])
    assert any("spec.metal.color" in field
               for field in added_body["ignored_fields"])
    assert any("spec.band.width_mm" in field
               for field in added_body["ignored_fields"])

    v1 = client.get(f"/designs/{design_id}/versions/1").json()
    v2 = client.get(f"/designs/{design_id}/versions/2").json()
    assert [group["position"] for group in v1["side_stones"]] == ["halo"]
    assert [group["position"] for group in v2["side_stones"]] == [
        "halo", "shoulder",
    ]
    assert v2["metal"] == v1["metal"]
    assert v2["band"] == v1["band"]
    assert client.get(f"/assets/{asset_v2}").json()["design_version"] == 2
    assert len(client.get(f"/assets/{asset_v1}/history").json()["history"]) == 2

    # A stale removal must be rejected before either the planner or image agent
    # can execute, leaving the accepted v2 pair untouched.
    _install_planner(
        monkeypatch,
        lambda annotation, current: pytest.fail(
            "stale inventory request must not reach the planner"
        ),
    )
    stale = _apply_inventory(
        client,
        asset_v2,
        expected_version=1,
        instruction="remove the shoulder diamonds",
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_design_version"
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 2
    assert len(client.get(f"/assets/{asset_v1}/history").json()["history"]) == 2

    _install_planner(monkeypatch, _inventory_planner("remove"))
    removed = _apply_inventory(
        client,
        asset_v2,
        expected_version=2,
        instruction="remove the shoulder diamonds",
    )
    assert removed.status_code == 201, removed.text
    removed_body = removed.json()
    asset_v3 = removed_body["final_asset_id"]
    assert removed_body["revision"]["asset"]["design_version"] == 3
    assert removed_body["spec_version"] == 3
    assert {change["kind"] for change in removed_body["spec_change"]} == {
        "removed",
    }
    v3 = client.get(f"/designs/{design_id}/versions/3").json()
    assert [group["position"] for group in v3["side_stones"]] == ["halo"]
    assert client.get(f"/assets/{asset_v3}").json()["design_version"] == 3
    assert len(client.get(f"/assets/{asset_v1}/history").json()["history"]) == 3
    assert [plan.operation.value for plan in plans] == ["LOCAL_EDIT", "LOCAL_EDIT"]


def test_center_shape_change_couples_setting_and_freezes_band_and_metal(
    client,
    monkeypatch,
):
    plans = _install_passing_image_agent(monkeypatch)
    _install_planner(monkeypatch, _shape_planner)
    asset_v1, design_id = _linked_asset(client)

    response = client.post(
        f"/assets/{asset_v1}/markup/apply",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
            "annotations": [{
                "region_description": "the center stone and its prong seats",
                "change_instruction": (
                    "change the oval center to a marquise and adapt only the "
                    "prongs needed to hold it"
                ),
                "target_ref": "A",
            }],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    asset_v2 = body["final_asset_id"]
    assert body["spec_version"] == 2
    assert body["revision"]["asset"]["design_version"] == 2
    assert body["qa"]["verdict"] == "pass"
    assert {change["path"] for change in body["spec_change"]} >= {
        "stone.cut",
        "stone.carat",
        "setting.style",
        "setting.prong_count",
    }
    assert any("spec.metal.color" in field for field in body["ignored_fields"])
    assert any("spec.band.width_mm" in field for field in body["ignored_fields"])

    v1 = client.get(f"/designs/{design_id}/versions/1").json()
    v2 = client.get(f"/designs/{design_id}/versions/2").json()
    assert (v1["stone"]["cut"], v1["setting"]["prong_count"]) == (
        "oval_brilliant", 4,
    )
    assert (v2["stone"]["cut"], v2["setting"]["prong_count"]) == (
        "marquise", 6,
    )
    assert v2["setting"]["style"] == "6_prong_basket"
    assert v2["metal"] == v1["metal"]
    assert v2["band"] == v1["band"]
    assert v2["side_stones"] == v1["side_stones"]
    assert client.get(f"/assets/{asset_v2}").json()["design_version"] == 2
    assert len(client.get(f"/assets/{asset_v1}/history").json()["history"]) == 2
    assert plans[0].operation.value == "LOCAL_EDIT"
    assert plans[0].source_spec_facts is not None


def test_invalid_inventory_change_never_calls_image_agent_or_creates_revision(
    client,
    monkeypatch,
):
    _install_planner(monkeypatch, _inventory_planner("impossible"))
    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: pytest.fail("invalid inventory must not reach image generation"),
    )
    asset_v1, design_id = _linked_asset(client)

    response = _apply_inventory(
        client,
        asset_v1,
        expected_version=1,
        instruction="increase the halo to sixty-four stones",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["final_asset_id"] is None
    assert body["revision"] is None
    assert body["steps"][0]["rejected"] is True
    assert any(issue["type"] == "fit" for issue in body["steps"][0]["detail"])
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1
    history = client.get(f"/assets/{asset_v1}/history").json()["history"]
    assert [item["asset_id"] for item in history] == [asset_v1]


def test_inventory_image_and_spec_roll_back_together_on_version_write_failure(
    client,
    monkeypatch,
):
    import facetta.api.designs as designs_mod

    _install_passing_image_agent(monkeypatch)
    _install_planner(monkeypatch, _inventory_planner("add"))
    asset_v1, design_id = _linked_asset(client)

    def fail_version(*args, **kwargs):
        raise RuntimeError("simulated inventory version insert failure")

    monkeypatch.setattr(designs_mod, "_store_version", fail_version)
    with pytest.raises(RuntimeError, match="inventory version insert failure"):
        _apply_inventory(
            client,
            asset_v1,
            expected_version=1,
            instruction="add six round diamonds to the shoulders",
        )

    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1
    history = client.get(f"/assets/{asset_v1}/history").json()["history"]
    assert [item["asset_id"] for item in history] == [asset_v1]
