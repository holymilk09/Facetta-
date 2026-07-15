"""Acceptance contract for persisted, reference-defined design-form edits.

These tests intentionally exercise the public trusted-workspace boundary.  A
free-form shoulder is not a numeric shank tweak: it must be addressed through
one stable element ID, an immutable designer-confirmed description and visual
reference, and a markup-derived isolation mask.  AI produces the candidate
pixels; the server owns scope, optimistic concurrency, QA, atomic persistence,
and factory-readiness truth.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import facetta.api.assets as assets_mod
from conftest import HALO_SPEC, audited_import_spec
from facetta.agent import Annotation, ScopedEditResult
from facetta.db import (
    Base,
    Design,
    DesignVersion,
    ImageAsset,
    ImageRun,
    Project,
    get_db,
    new_id,
    utcnow,
)
from facetta.design_form import apply_scoped_form_element
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
from facetta.validation import validate_spec
from facetta.vocabulary import get_vocabulary
from facetta.warning_candidates import clear_warning_candidates_for_tests


ART_DECO_DESCRIPTION = (
    "Bilateral stepped Art Deco shoulders with three crisp descending planes "
    "between the halo and the plain lower shank."
)
SMOOTH_DESCRIPTION = (
    "Bilateral smooth continuous shoulders flowing without steps from the "
    "halo into the plain lower shank."
)
EDIT_INSTRUCTION = (
    "Replace only the stepped Art Deco shoulders with smooth continuous "
    "shoulders; keep the halo, center stone, gallery, lower shank, metal, "
    "camera, and lighting unchanged."
)
SOURCE_IMAGE = None
CANDIDATE_IMAGE = None


def _png(
    color: tuple[int, int, int] = (188, 181, 172),
    *,
    size: tuple[int, int] = (240, 240),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


SOURCE_IMAGE = _png()
CANDIDATE_IMAGE = _png((105, 98, 90))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _marked_reference(source: bytes) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGB")
    draw = ImageDraw.Draw(image)
    # Two explicit shoulder regions.  The red markup is converted into the
    # actual edit mask by markup/read -> markup/apply, not trusted as prose.
    draw.rectangle((34, 88, 87, 150), outline=(255, 0, 0), width=5)
    draw.rectangle((153, 88, 206, 150), outline=(255, 0, 0), width=5)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _polygon(points: list[tuple[float, float]]) -> dict:
    return {"points": [{"x": x, "y": y} for x, y in points]}


def _design_form(root_id: str, image: bytes = SOURCE_IMAGE) -> dict:
    source_hash = _sha256(image)
    return {
        "elements": [
            {
                "element_id": "shoulder_architecture",
                "role": "shoulder_architecture",
                "label": "Ring shoulders",
                "confirmed_form_description": ART_DECO_DESCRIPTION,
                "symmetry": "bilateral",
                "instance_count": 2,
                "regions": [{
                    "view": "three_quarter",
                    "polygons": [
                        _polygon([
                            (0.14, 0.36), (0.36, 0.33),
                            (0.36, 0.63), (0.14, 0.66),
                        ]),
                        _polygon([
                            (0.64, 0.33), (0.86, 0.36),
                            (0.86, 0.66), (0.64, 0.63),
                        ]),
                    ],
                }],
                "definition": {
                    "kind": "visual_reference_only",
                    "asset_id": root_id,
                    "asset_sha256": source_hash,
                },
            },
            {
                "element_id": "gallery_outline",
                "role": "gallery_architecture",
                "label": "Center gallery outline",
                "confirmed_form_description": (
                    "Open four-prong gallery centered beneath the oval stone."
                ),
                "symmetry": "bilateral",
                "instance_count": 1,
                "regions": [{
                    "view": "three_quarter",
                    "polygons": [_polygon([
                        (0.38, 0.17), (0.62, 0.17),
                        (0.60, 0.42), (0.40, 0.42),
                    ])],
                }],
                "definition": {
                    "kind": "visual_reference_only",
                    "asset_id": root_id,
                    "asset_sha256": source_hash,
                },
            },
        ],
    }


@pytest.fixture
def workflow(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    clear_warning_candidates_for_tests()
    app.dependency_overrides[get_db] = override
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
    yield TestClient(app), session_factory
    clear_warning_candidates_for_tests()
    app.dependency_overrides.clear()


def _seed_design_form_project(session_factory) -> tuple[str, str]:
    root_id = new_id("ast")
    design_id = new_id("dsn")
    now = utcnow()
    raw = copy.deepcopy(HALO_SPEC)
    raw.update({
        "design_id": design_id,
        "version": 1,
        "created_by": "usr_designer",
        "created_at": now.isoformat(),
        "design_form": _design_form(root_id),
    })
    validation = validate_spec(Spec.model_validate(raw), get_vocabulary())
    assert validation.ok, validation.issues
    spec = validation.spec
    stored = spec.model_dump(mode="json")

    with session_factory() as db:
        db.add_all([
            Design(id=design_id, created_by="usr_designer", created_at=now),
            DesignVersion(
                design_id=design_id,
                version=1,
                spec=stored,
                created_by="usr_designer",
                created_at=now,
            ),
            ImageAsset(
                id=root_id,
                root_id=root_id,
                parent_asset_id=None,
                design_id=design_id,
                design_version=1,
                capability="IMPORTED_REFERENCE",
                instruction="designer-confirmed imported Art Deco ring",
                image=SOURCE_IMAGE,
                media_type="image/png",
                created_by="usr_designer",
                created_at=now,
            ),
            Project(
                root_id=root_id,
                owner="usr_designer",
                title="Art Deco shoulder study",
                tags=["ring", "shoulders"],
                created_at=now,
                updated_at=now,
            ),
        ])
        db.commit()
    return root_id, design_id


def _read_shoulder_markup(
    client: TestClient,
    monkeypatch,
    asset_id: str,
) -> tuple[str, str]:
    reading = {
        "annotations": [{
            "region_description": "both stepped shoulders",
            "change_instruction": EDIT_INSTRUCTION,
            "target_section": "design_form",
            "target_element_id": "shoulder_architecture",
            "handwriting": "smooth shoulders",
            "confidence": 0.99,
        }],
        "understood_as": (
            "Replace only shoulder_architecture: Art Deco steps to a smooth "
            "continuous shoulder; freeze every other element."
        ),
        "needs_clarification": False,
        "clarification": "",
    }
    monkeypatch.setattr(
        assets_mod,
        "read_markup",
        lambda clean, marked, form_elements=(): copy.deepcopy(reading),
    )
    response = client.post(
        f"/assets/{asset_id}/markup/read",
        json={
            "marked_image_base64": base64.b64encode(
                _marked_reference(SOURCE_IMAGE)
            ).decode(),
            "created_by": "usr_designer",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["annotations"][0]["target_element_id"] == (
        "shoulder_architecture"
    )
    assert body["expected_design_version"] == 1
    confirmed = client.post(
        f"/assets/{asset_id}/markup/interpretations/"
        f"{body['interpretation_id']}/confirm",
        json={"created_by": "usr_designer"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return body["markup_asset_id"], body["interpretation_id"]


def _install_scoped_planner(monkeypatch) -> None:
    import facetta.grokedit as grokedit

    def planner(annotation: Annotation, current: Spec) -> ScopedEditResult:
        assert annotation.section == "design_form"
        assert annotation.target_element_id == "shoulder_architecture"
        proposed_raw = current.model_dump(mode="json")
        shoulder = next(
            item for item in proposed_raw["design_form"]["elements"]
            if item["element_id"] == "shoulder_architecture"
        )
        shoulder["confirmed_form_description"] = SMOOTH_DESCRIPTION
        proposed = Spec.model_validate(proposed_raw)
        guarded_form = apply_scoped_form_element(
            current.design_form,
            proposed.design_form,
            element_id="shoulder_architecture",
        )
        edited = current.model_copy(update={"design_form": guarded_form})
        return ScopedEditResult(
            spec=edited,
            target="design_form:shoulder_architecture",
            changed_fields=[
                "design_form.shoulder_architecture.confirmed_form_description "
                "Art Deco stepped shoulders -> smooth continuous shoulders"
            ],
            ignored_fields=[],
            message="Only the confirmed shoulder architecture changed.",
        )

    monkeypatch.setattr(grokedit, "grok_plan_scoped_edit", planner)


def _install_image_agent(
    monkeypatch,
    verdict: QualityVerdict,
) -> tuple[list, list[bytes | None]]:
    plans = []
    masks: list[bytes | None] = []

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
            masks.append(mask_bytes)
            return ProviderImage(image_bytes=CANDIDATE_IMAGE)

    class Evaluator:
        def evaluate(self, plan, candidate, *, source_image, mask_bytes):
            if verdict is QualityVerdict.FAIL:
                checks = (QualityCheck(
                    code="outside_mask_drift",
                    passed=False,
                    severity=CheckSeverity.HARD,
                    message="the halo and lower shank changed outside the mask",
                    evidence={"drift": 0.47, "threshold": 0.18},
                ),)
                score = 31
            elif verdict is QualityVerdict.WARN:
                checks = (QualityCheck(
                    code="form_definition_review",
                    passed=False,
                    severity=CheckSeverity.WARNING,
                    message="designer must confirm the new smooth contour",
                ),)
                score = 88
            else:
                checks = (
                    QualityCheck(
                        code="requested_change",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="the shoulders are now smooth",
                    ),
                    QualityCheck(
                        code="outside_mask_drift",
                        passed=True,
                        severity=CheckSeverity.HARD,
                        message="untargeted pixels stayed within tolerance",
                        evidence={"drift": 0.02, "threshold": 0.18},
                    ),
                )
                score = 98
            return ImageQualityReport(
                verdict=verdict,
                checks=checks,
                score=score,
            )

    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: JewelryImageAgent(Provider(), Evaluator()),
    )
    return plans, masks


def _apply_body(markup_authority: tuple[str, str]) -> dict:
    markup_asset_id, interpretation_id = markup_authority
    return {
        "expected_design_version": 1,
        "update_spec": True,
        "markup_asset_id": markup_asset_id,
        "confirmed_interpretation_id": interpretation_id,
        "created_by": "usr_designer",
        "annotations": [{
            "region_description": "both stepped shoulders",
            "change_instruction": EDIT_INSTRUCTION,
            "target_section": "design_form",
            "target_element_id": "shoulder_architecture",
        }],
    }


def _approve(client: TestClient, asset_id: str) -> dict:
    created = client.post(
        f"/assets/{asset_id}/checklist",
        json={"created_by": "usr_designer", "mode": "auto_pin"},
    )
    assert created.status_code == 201, created.text
    checklist = created.json()
    for item in checklist["items"]:
        response = client.post(
            f"/assets/{asset_id}/checklist/respond",
            json={
                "item_key": item["key"],
                "approved": True,
                "created_by": "usr_designer",
            },
        )
        assert response.status_code == 201, response.text
    return checklist


def test_art_deco_to_smooth_requires_full_trusted_target_contract(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    asset_id, design_id = _seed_design_form_project(session_factory)
    markup_id = _read_shoulder_markup(client, monkeypatch, asset_id)

    import facetta.grokedit as grokedit

    monkeypatch.setattr(
        grokedit,
        "grok_plan_scoped_edit",
        lambda *args, **kwargs: pytest.fail(
            "an incomplete design-form request must not reach the planner"
        ),
    )
    monkeypatch.setattr(
        assets_mod,
        "_trusted_image_agent",
        lambda: pytest.fail(
            "an incomplete design-form request must not reach image work"
        ),
    )
    monkeypatch.setattr(
        assets_mod,
        "localized_edit",
        lambda *args, **kwargs: pytest.fail(
            "design-form work must not fall through to compatibility editing"
        ),
    )

    valid = _apply_body(markup_id)
    cases: list[tuple[str, dict, int]] = []

    missing_version = copy.deepcopy(valid)
    missing_version.pop("expected_design_version")
    cases.append(("expected design version", missing_version, 422))

    stale_version = copy.deepcopy(valid)
    stale_version["expected_design_version"] = 2
    cases.append(("current design version", stale_version, 409))

    image_only = copy.deepcopy(valid)
    image_only["update_spec"] = False
    cases.append(("spec synchronization", image_only, 422))

    missing_markup = copy.deepcopy(valid)
    missing_markup.pop("markup_asset_id")
    missing_markup.pop("confirmed_interpretation_id")
    cases.append(("markup-derived mask", missing_markup, 422))

    client_mask_only = copy.deepcopy(missing_markup)
    client_mask_only["annotations"][0]["mask_base64"] = base64.b64encode(
        _png((255, 255, 255))
    ).decode()
    cases.append(("server-derived markup mask", client_mask_only, 422))

    missing_element = copy.deepcopy(valid)
    missing_element["annotations"][0].pop("target_element_id")
    cases.append(("stable element ID", missing_element, 422))

    unknown_element = copy.deepcopy(valid)
    unknown_element["annotations"][0]["target_element_id"] = "unknown_shoulder"
    cases.append(("confirmed form element", unknown_element, 422))

    for requirement, body, expected_status in cases:
        response = client.post(
            f"/assets/{asset_id}/markup/apply",
            json=body,
        )
        assert response.status_code == expected_status, (
            requirement,
            response.text,
        )

    project = client.get(f"/projects/{asset_id}").json()
    assert project["active_asset_id"] == asset_id
    assert project["primary_revision_count"] == 1
    assert project["latest_design_version"] == 1
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1


def test_art_deco_to_smooth_persists_exactly_one_masked_element_revision(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    asset_v1, design_id = _seed_design_form_project(session_factory)
    markup_id = _read_shoulder_markup(client, monkeypatch, asset_v1)
    _install_scoped_planner(monkeypatch)
    plans, masks = _install_image_agent(monkeypatch, QualityVerdict.PASS)

    response = client.post(
        f"/assets/{asset_v1}/markup/apply",
        json=_apply_body(markup_id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    asset_v2 = body["final_asset_id"]
    assert asset_v2 != asset_v1
    assert body["spec_version"] == 2
    assert body["revision"]["asset"]["design_version"] == 2
    assert body["qa"]["verdict"] == "pass"

    assert len(plans) == 1
    assert [domain.value for domain in plans[0].edit_domains] == ["design_form"]
    assert plans[0].mask_hash == _sha256(masks[0])
    assert masks[0] is not None
    mask = Image.open(io.BytesIO(masks[0])).convert("L")
    assert mask.getbbox() is not None
    assert mask.getpixel((5, 5)) == 0

    v1 = client.get(f"/designs/{design_id}/versions/1").json()
    v2 = client.get(f"/designs/{design_id}/versions/2").json()
    before_by_id = {
        item["element_id"]: item for item in v1["design_form"]["elements"]
    }
    after_by_id = {
        item["element_id"]: item for item in v2["design_form"]["elements"]
    }
    assert tuple(before_by_id) == tuple(after_by_id) == (
        "shoulder_architecture",
        "gallery_outline",
    )
    assert after_by_id["gallery_outline"] == before_by_id["gallery_outline"]
    assert before_by_id["shoulder_architecture"][
        "confirmed_form_description"
    ] == ART_DECO_DESCRIPTION
    shoulder_v2 = after_by_id["shoulder_architecture"]
    assert shoulder_v2["confirmed_form_description"] == SMOOTH_DESCRIPTION
    assert shoulder_v2["definition"] == {
        "kind": "visual_reference_only",
        "asset_id": asset_v2,
        "asset_sha256": _sha256(CANDIDATE_IMAGE),
    }
    assert before_by_id["shoulder_architecture"]["definition"] == {
        "kind": "visual_reference_only",
        "asset_id": asset_v1,
        "asset_sha256": _sha256(SOURCE_IMAGE),
    }

    metadata = {"version", "created_by", "created_at"}
    for key in v1.keys() - metadata - {"design_form"}:
        assert v2[key] == v1[key], key
    changed_paths = {change["path"] for change in body["spec_change"]}
    assert changed_paths
    assert all(path.startswith("design_form.elements.0.") for path in changed_paths)

    project = client.get(f"/projects/{asset_v1}").json()
    assert project["active_asset_id"] == asset_v2
    assert project["active_design_version"] == 2
    assert project["primary_revision_count"] == 2
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 2
    assert client.get(f"/assets/{asset_v2}").json()["design_version"] == 2


def test_outside_mask_failure_records_evidence_but_no_product_revision(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    asset_id, design_id = _seed_design_form_project(session_factory)
    markup_id = _read_shoulder_markup(client, monkeypatch, asset_id)
    _install_scoped_planner(monkeypatch)
    plans, masks = _install_image_agent(monkeypatch, QualityVerdict.FAIL)

    response = client.post(
        f"/assets/{asset_id}/markup/apply",
        json=_apply_body(markup_id),
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "image_quality_failed"
    assert len(plans) == 3
    assert all(mask is not None for mask in masks)
    project = client.get(f"/projects/{asset_id}").json()
    assert project["active_asset_id"] == asset_id
    assert project["active_design_version"] == 1
    assert project["primary_revision_count"] == 1
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    with session_factory() as db:
        primary = list(db.scalars(select(ImageAsset).where(
            ImageAsset.root_id == asset_id,
            ImageAsset.capability.in_([
                "IMPORTED_REFERENCE",
                "LOCALIZED_EDIT",
            ]),
        )))
        runs = list(db.scalars(select(ImageRun).where(
            ImageRun.project_root_id == asset_id,
        )))
    assert [asset.id for asset in primary] == [asset_id]
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].accepted_asset_id is None


def test_warning_candidate_is_held_outside_active_asset_chain(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    asset_id, design_id = _seed_design_form_project(session_factory)
    markup_id = _read_shoulder_markup(client, monkeypatch, asset_id)
    _install_scoped_planner(monkeypatch)
    _install_image_agent(monkeypatch, QualityVerdict.WARN)

    response = client.post(
        f"/assets/{asset_id}/markup/apply",
        json=_apply_body(markup_id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["revision"] is None
    assert body["final_asset_id"] is None
    assert body["warning_candidate"]["qa"]["verdict"] == "warn"
    project = client.get(f"/projects/{asset_id}").json()
    assert project["active_asset_id"] == asset_id
    assert project["active_design_version"] == 1
    assert project["primary_revision_count"] == 1
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 1

    with session_factory() as db:
        stored_candidate = db.scalar(select(ImageAsset).where(
            ImageAsset.root_id == asset_id,
            ImageAsset.image == CANDIDATE_IMAGE,
        ))
        run = db.get(ImageRun, body["image_run_id"])
    assert stored_candidate is None
    assert run.status == "review_required"
    assert run.accepted_asset_id is None


def test_accepting_form_warning_binds_reserved_asset_and_spec_exactly_once(
    workflow,
    monkeypatch,
):
    client, session_factory = workflow
    asset_v1, design_id = _seed_design_form_project(session_factory)
    markup_id = _read_shoulder_markup(client, monkeypatch, asset_v1)
    _install_scoped_planner(monkeypatch)
    _install_image_agent(monkeypatch, QualityVerdict.WARN)

    held = client.post(
        f"/assets/{asset_v1}/markup/apply",
        json=_apply_body(markup_id),
    )
    assert held.status_code == 201, held.text
    candidate = held.json()["warning_candidate"]

    accepted = client.post(
        f"/image-runs/{candidate['run_id']}/candidates/"
        f"{candidate['candidate_id']}/accept",
        json={
            "expected_design_version": 1,
            "created_by": "usr_designer",
        },
    )

    assert accepted.status_code == 201, accepted.text
    project = accepted.json()
    asset_v2 = project["active_asset_id"]
    assert asset_v2 != asset_v1
    assert project["active_design_version"] == 2
    assert project["primary_revision_count"] == 2
    assert len(client.get(f"/designs/{design_id}").json()["versions"]) == 2

    v2 = client.get(f"/designs/{design_id}/versions/2").json()
    shoulder = next(
        element for element in v2["design_form"]["elements"]
        if element["element_id"] == "shoulder_architecture"
    )
    assert shoulder["confirmed_form_description"] == SMOOTH_DESCRIPTION
    assert shoulder["definition"] == {
        "kind": "visual_reference_only",
        "asset_id": asset_v2,
        "asset_sha256": _sha256(CANDIDATE_IMAGE),
    }
    # Public render endpoints watermark non-technical images, so compare the
    # immutable stored bytes at the persistence boundary.
    with session_factory() as db:
        persisted = db.get(ImageAsset, asset_v2)
        assert bytes(persisted.image) == CANDIDATE_IMAGE

    reviewed_run = client.get(f"/image-runs/{candidate['run_id']}").json()
    assert reviewed_run["stored_status"] == "review_required"
    assert reviewed_run["status"] == "accepted"
    assert reviewed_run["accepted_asset_id"] == asset_v2

    _approve(client, asset_v2)
    reviewed_project = client.get(f"/projects/{asset_v1}").json()
    assert reviewed_project["state"] == "approved"
    assert reviewed_project["factory_ready"] is False
    pack = client.get(f"/projects/{asset_v1}/factory-pack")
    assert pack.status_code == 409, pack.text
    assert pack.json()["code"].startswith("design_form")


def test_visual_approval_does_not_make_reference_only_form_factory_ready(
    workflow,
):
    client, session_factory = workflow
    asset_id, _ = _seed_design_form_project(session_factory)
    checklist = _approve(client, asset_id)

    project = client.get(f"/projects/{asset_id}")
    assert project.status_code == 200, project.text
    body = project.json()
    assert body["approval"]["checklist_id"] == checklist["checklist_id"]
    assert body["approval"]["all_approved"] is True
    assert body["state"] == "approved"
    assert body["factory_ready"] is False

    pack = client.get(f"/projects/{asset_id}/factory-pack")
    assert pack.status_code == 409, pack.text
    payload = pack.json()
    assert payload["code"].startswith("design_form")
    serialized = json.dumps(payload)
    assert "shoulder_architecture" in serialized
    assert "gallery_outline" in serialized
    assert "visual_reference_only" in serialized


@pytest.mark.parametrize("future_kind", ["dimensioned_profile", "cad_reference"])
def test_future_factory_definitions_are_rejected_not_fabricated(future_kind):
    raw = copy.deepcopy(HALO_SPEC)
    raw["design_form"] = _design_form("ast_imported_reference")
    raw["design_form"]["elements"][0]["definition"] = {
        "kind": future_kind,
    }

    with pytest.raises(ValidationError):
        Spec.model_validate(raw)

    visual = Spec.model_validate({
        **copy.deepcopy(HALO_SPEC),
        "design_form": _design_form("ast_imported_reference"),
    })
    definition = visual.design_form.elements[0].definition.model_dump()
    assert definition == {
        "kind": "visual_reference_only",
        "asset_id": "ast_imported_reference",
        "asset_sha256": _sha256(SOURCE_IMAGE),
    }
    assert not ({"dimensions", "profile", "cad"} & set(definition))


def test_legacy_project_without_design_form_remains_readable_and_factory_ready(
    workflow,
):
    client, session_factory = workflow
    response = client.post(
        "/projects/from-image",
        json={
            "image_base64": base64.b64encode(SOURCE_IMAGE).decode(),
            "media_type": "image/png",
            "spec": audited_import_spec(HALO_SPEC),
            "owner": "usr_legacy",
            "title": "Legacy halo",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["spec"]["design_form"] == {"elements": []}

    # Emulate a DesignVersion persisted before the additive field existed.
    with session_factory() as db:
        row = db.get(DesignVersion, (created["design_id"], 1))
        historical = dict(row.spec)
        historical.pop("design_form")
        # Bypass the ORM immutability guard only to emulate a row written by
        # an older application version before this additive field existed.
        db.execute(
            update(DesignVersion)
            .where(
                DesignVersion.design_id == created["design_id"],
                DesignVersion.version == 1,
            )
            .values(spec=historical)
        )
        db.commit()

    loaded = client.get(f"/projects/{created['root_id']}")
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["active_asset_id"] == created["active_asset_id"]
    assert loaded.json()["latest_design_version"] == 1
    assert "design_form" not in loaded.json()["spec"]

    _approve(client, created["active_asset_id"])
    ready = client.get(f"/projects/{created['root_id']}").json()
    assert ready["state"] == "factory_ready"
    assert ready["factory_ready"] is True
    pack = client.get(f"/projects/{created['root_id']}/factory-pack")
    assert pack.status_code == 200, pack.text
    assert pack.json()["design_version"] == 1
